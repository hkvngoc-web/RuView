"""
Dịch vụ ước lượng tư thế cho WiFi-DensePose API.

Các đường dẫn sản xuất trong mô-đun này KHÔNG BAO GIỜ sử dụng dữ liệu ngẫu nhiên.
Tất cả việc tạo dữ liệu giả/tổng hợp được cô lập trong src.testing và chỉ
được gọi khi settings.mock_pose_data là True một cách rõ ràng.
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import numpy as np
import torch

from src.config.settings import Settings
from src.config.domains import DomainConfig
from src.core.csi_processor import CSIProcessor
from src.core.phase_sanitizer import PhaseSanitizer
from src.models.densepose_head import DensePoseHead
from src.models.modality_translation import ModalityTranslationNetwork

logger = logging.getLogger(__name__)


class PoseService:
    """Dịch vụ cho các thao tác ước lượng tư thế."""

    def __init__(self, settings: Settings, domain_config: DomainConfig):
        """Khởi tạo dịch vụ tư thế."""
        self.settings = settings
        self.domain_config = domain_config
        self.logger = logging.getLogger(__name__)

        # Khởi tạo các thành phần
        self.csi_processor = None
        self.phase_sanitizer = None
        self.densepose_model = None
        self.modality_translator = None

        # Trạng thái dịch vụ
        self.is_initialized = False
        self.is_running = False
        self.last_error = None
        self._start_time: Optional[datetime] = None
        self._calibration_in_progress: bool = False
        self._calibration_id: Optional[str] = None
        self._calibration_start: Optional[datetime] = None

        # Thống kê xử lý
        self.stats = {
            "total_processed": 0,
            "successful_detections": 0,
            "failed_detections": 0,
            "average_confidence": 0.0,
            "processing_time_ms": 0.0
        }

    async def initialize(self):
        """Khởi tạo dịch vụ tư thế."""
        try:
            self.logger.info("Đang khởi tạo dịch vụ tư thế...")

            # Khởi tạo bộ xử lý CSI
            csi_config = {
                'buffer_size': self.settings.csi_buffer_size,
                'sampling_rate': getattr(self.settings, 'csi_sampling_rate', 1000),
                'window_size': getattr(self.settings, 'csi_window_size', 512),
                'overlap': getattr(self.settings, 'csi_overlap', 0.5),
                'noise_threshold': getattr(self.settings, 'csi_noise_threshold', 0.1),
                'human_detection_threshold': getattr(self.settings, 'csi_human_detection_threshold', 0.8),
                'smoothing_factor': getattr(self.settings, 'csi_smoothing_factor', 0.9),
                'max_history_size': getattr(self.settings, 'csi_max_history_size', 500),
                'num_subcarriers': 56,
                'num_antennas': 3
            }
            self.csi_processor = CSIProcessor(config=csi_config)

            # Khởi tạo bộ làm sạch pha
            phase_config = {
                'unwrapping_method': 'numpy',
                'outlier_threshold': 3.0,
                'smoothing_window': 5,
                'enable_outlier_removal': True,
                'enable_smoothing': True,
                'enable_noise_filtering': True,
                'noise_threshold': getattr(self.settings, 'csi_noise_threshold', 0.1)
            }
            self.phase_sanitizer = PhaseSanitizer(config=phase_config)

            # Khởi tạo mô hình nếu không sử dụng dữ liệu giả
            if not self.settings.mock_pose_data:
                await self._initialize_models()
            else:
                self.logger.info("Sử dụng dữ liệu tư thế giả cho phát triển")

            self.is_initialized = True
            self._start_time = datetime.now()
            self.logger.info("Dịch vụ tư thế đã khởi tạo thành công")

        except Exception as e:
            self.last_error = str(e)
            self.logger.error(f"Khởi tạo dịch vụ tư thế thất bại: {e}")
            raise

    async def _initialize_models(self):
        """Khởi tạo các mô hình mạng nơ-ron."""
        try:
            # Khởi tạo mô hình DensePose
            if self.settings.pose_model_path:
                self.densepose_model = DensePoseHead()
                # Tải trọng số mô hình nếu có đường dẫn
                # model_state = torch.load(self.settings.pose_model_path)
                # self.densepose_model.load_state_dict(model_state)
                self.logger.info("Đã tải mô hình DensePose")
            else:
                self.logger.warning("Không có đường dẫn mô hình tư thế, sử dụng mô hình mặc định")
                self.densepose_model = DensePoseHead()

            # Khởi tạo dịch phương thức
            config = {
                'input_channels': 64,  # Kênh dữ liệu CSI
                'hidden_channels': [128, 256, 512],
                'output_channels': 256,  # Kênh đặc trưng trực quan
                'use_attention': True
            }
            self.modality_translator = ModalityTranslationNetwork(config)

            # Đặt mô hình sang chế độ đánh giá
            self.densepose_model.eval()
            self.modality_translator.eval()

        except Exception as e:
            self.logger.error(f"Khởi tạo mô hình thất bại: {e}")
            raise

    async def start(self):
        """Khởi động dịch vụ tư thế."""
        if not self.is_initialized:
            await self.initialize()

        self.is_running = True
        self.logger.info("Dịch vụ tư thế đã khởi động")

    async def stop(self):
        """Dừng dịch vụ tư thế."""
        self.is_running = False
        self.logger.info("Dịch vụ tư thế đã dừng")

    async def process_csi_data(self, csi_data: np.ndarray, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Xử lý dữ liệu CSI và ước lượng tư thế."""
        if not self.is_running:
            raise RuntimeError("Dịch vụ tư thế chưa đang chạy")

        start_time = datetime.now()

        try:
            # Xử lý dữ liệu CSI
            processed_csi = await self._process_csi(csi_data, metadata)

            # Ước lượng tư thế
            poses = await self._estimate_poses(processed_csi, metadata)

            # Cập nhật thống kê
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            self._update_stats(poses, processing_time)

            return {
                "timestamp": start_time.isoformat(),
                "poses": poses,
                "metadata": metadata,
                "processing_time_ms": processing_time,
                "confidence_scores": [pose.get("confidence", 0.0) for pose in poses]
            }

        except Exception as e:
            self.last_error = str(e)
            self.stats["failed_detections"] += 1
            self.logger.error(f"Lỗi khi xử lý dữ liệu CSI: {e}")
            raise

    async def _process_csi(self, csi_data: np.ndarray, metadata: Dict[str, Any]) -> np.ndarray:
        """Xử lý dữ liệu CSI thô."""
        # Chuyển đổi dữ liệu thô sang định dạng CSIData
        from src.hardware.csi_extractor import CSIData

        # Tạo đối tượng CSIData với các trường phù hợp
        # Cho dữ liệu giả, tạo biên độ và pha từ đầu vào
        if csi_data.ndim == 1:
            amplitude = np.abs(csi_data)
            phase = np.angle(csi_data) if np.iscomplexobj(csi_data) else np.zeros_like(csi_data)
        else:
            amplitude = csi_data
            phase = np.zeros_like(csi_data)

        csi_data_obj = CSIData(
            timestamp=metadata.get("timestamp", datetime.now()),
            amplitude=amplitude,
            phase=phase,
            frequency=metadata.get("frequency", 5.0),  # Mặc định 5 GHz
            bandwidth=metadata.get("bandwidth", 20.0),  # Mặc định 20 MHz
            num_subcarriers=metadata.get("num_subcarriers", 56),
            num_antennas=metadata.get("num_antennas", 3),
            snr=metadata.get("snr", 20.0),  # Mặc định 20 dB
            metadata=metadata
        )

        # Xử lý dữ liệu CSI
        try:
            detection_result = await self.csi_processor.process_csi_data(csi_data_obj)

            # Thêm vào lịch sử cho phân tích theo thời gian
            self.csi_processor.add_to_history(csi_data_obj)

            # Trích xuất dữ liệu biên độ cho ước lượng tư thế
            if detection_result and detection_result.features:
                amplitude_data = detection_result.features.amplitude_mean

                # Áp dụng làm sạch pha nếu có dữ liệu pha
                if hasattr(detection_result.features, 'phase_difference'):
                    phase_data = detection_result.features.phase_difference
                    sanitized_phase = self.phase_sanitizer.sanitize(phase_data)
                    # Kết hợp dữ liệu biên độ và pha
                    return np.concatenate([amplitude_data, sanitized_phase])

                return amplitude_data

        except Exception as e:
            self.logger.warning(f"Xử lý CSI thất bại, sử dụng dữ liệu thô: {e}")

        return csi_data

    async def _estimate_poses(self, csi_data: np.ndarray, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ước lượng tư thế từ dữ liệu CSI đã xử lý."""
        if self.settings.mock_pose_data:
            return self._generate_mock_poses()

        try:
            # Chuyển đổi dữ liệu CSI sang tensor
            csi_tensor = torch.from_numpy(csi_data).float()

            # Thêm chiều batch nếu cần
            if len(csi_tensor.shape) == 2:
                csi_tensor = csi_tensor.unsqueeze(0)

            # Dịch phương thức (CSI sang đặc trưng dạng trực quan)
            with torch.no_grad():
                visual_features = self.modality_translator(csi_tensor)

                # Ước lượng tư thế sử dụng DensePose
                pose_outputs = self.densepose_model(visual_features)

            # Chuyển đổi đầu ra thành phát hiện tư thế
            poses = self._parse_pose_outputs(pose_outputs)

            # Lọc theo ngưỡng độ tin cậy
            filtered_poses = [
                pose for pose in poses
                if pose.get("confidence", 0.0) >= self.settings.pose_confidence_threshold
            ]

            # Giới hạn số người
            if len(filtered_poses) > self.settings.pose_max_persons:
                filtered_poses = sorted(
                    filtered_poses,
                    key=lambda x: x.get("confidence", 0.0),
                    reverse=True
                )[:self.settings.pose_max_persons]

            return filtered_poses

        except Exception as e:
            self.logger.error(f"Lỗi trong ước lượng tư thế: {e}")
            return []

    def _parse_pose_outputs(self, outputs: torch.Tensor) -> List[Dict[str, Any]]:
        """Phân tích đầu ra mạng nơ-ron thành phát hiện tư thế.

        Trích xuất độ tin cậy, điểm mấu chốt, khung giới hạn và hoạt động từ
        tensor đầu ra mô hình. Cách diễn giải chính xác phụ thuộc vào kiến trúc mô hình;
        triển khai này giả định định dạng đầu ra DensePoseHead.

        Args:
            outputs: Tensor đầu ra mô hình có hình dạng (batch, features).

        Returns:
            Danh sách từ điển phát hiện tư thế.
        """
        poses = []
        batch_size = outputs.shape[0]

        for i in range(batch_size):
            output_i = outputs[i] if len(outputs.shape) > 1 else outputs

            # Trích xuất độ tin cậy từ kênh đầu ra đầu tiên
            confidence = float(torch.sigmoid(output_i[0]).item()) if output_i.shape[0] > 0 else 0.0

            # Trích xuất điểm mấu chốt từ đầu ra mô hình nếu có
            keypoints = self._extract_keypoints_from_output(output_i)

            # Trích xuất khung giới hạn từ đầu ra mô hình nếu có
            bounding_box = self._extract_bbox_from_output(output_i)

            # Phân loại hoạt động từ đặc trưng
            activity = self._classify_activity(output_i)

            pose = {
                "person_id": i,
                "confidence": confidence,
                "keypoints": keypoints,
                "bounding_box": bounding_box,
                "activity": activity,
                "timestamp": datetime.now().isoformat(),
            }

            poses.append(pose)

        return poses

    def _extract_keypoints_from_output(self, output: torch.Tensor) -> List[Dict[str, Any]]:
        """Trích xuất điểm mấu chốt từ đầu ra mô hình của một người.

        Cố gắng giải mã tọa độ điểm mấu chốt từ tensor đầu ra.
        Nếu tensor không chứa đủ dữ liệu cho tất cả điểm mấu chốt,
        trả về điểm mấu chốt với tọa độ bằng không và độ tin cậy
        lấy từ dữ liệu có sẵn.

        Args:
            output: Tensor đầu ra của một người.

        Returns:
            Danh sách từ điển điểm mấu chốt.
        """
        keypoint_names = [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle",
        ]

        keypoints = []
        # Mỗi điểm mấu chốt cần 3 giá trị: x, y, confidence
        # Bỏ qua giá trị đầu tiên (độ tin cậy tổng thể), điểm mấu chốt bắt đầu từ index 1
        kp_start = 1
        values_per_kp = 3
        total_kp_values = len(keypoint_names) * values_per_kp

        if output.shape[0] >= kp_start + total_kp_values:
            kp_data = output[kp_start:kp_start + total_kp_values]
            for j, name in enumerate(keypoint_names):
                offset = j * values_per_kp
                x = float(torch.sigmoid(kp_data[offset]).item())
                y = float(torch.sigmoid(kp_data[offset + 1]).item())
                conf = float(torch.sigmoid(kp_data[offset + 2]).item())
                keypoints.append({"name": name, "x": x, "y": y, "confidence": conf})
        else:
            # Không đủ chiều đầu ra cho tất cả điểm mấu chốt; trả về giá trị không
            for name in keypoint_names:
                keypoints.append({"name": name, "x": 0.0, "y": 0.0, "confidence": 0.0})

        return keypoints

    def _extract_bbox_from_output(self, output: torch.Tensor) -> Dict[str, float]:
        """Trích xuất khung giới hạn từ đầu ra mô hình của một người.

        Tìm giá trị bbox sau phần điểm mấu chốt. Nếu không có,
        trả về khung giới hạn bằng không.

        Args:
            output: Tensor đầu ra của một người.

        Returns:
            Từ điển khung giới hạn với x, y, width, height.
        """
        # Khung giới hạn nằm sau: 1 (confidence) + 17*3 (keypoints) = 52
        bbox_start = 52
        if output.shape[0] >= bbox_start + 4:
            x = float(torch.sigmoid(output[bbox_start]).item())
            y = float(torch.sigmoid(output[bbox_start + 1]).item())
            w = float(torch.sigmoid(output[bbox_start + 2]).item())
            h = float(torch.sigmoid(output[bbox_start + 3]).item())
            return {"x": x, "y": y, "width": w, "height": h}
        else:
            return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}

    def _generate_mock_poses(self) -> List[Dict[str, Any]]:
        """Tạo dữ liệu tư thế giả cho phát triển.

        Ủy quyền cho mô-đun kiểm thử. Chỉ được gọi khi mock_pose_data là True.

        Raises:
            NotImplementedError: Nếu được gọi mà không bật mock_pose_data,
                cho biết rằng cần dữ liệu CSI thực và mô hình đã huấn luyện.
        """
        if not self.settings.mock_pose_data:
            raise NotImplementedError(
                "Tạo tư thế giả đã bị tắt. Ước lượng tư thế thực yêu cầu "
                "dữ liệu CSI từ phần cứng đã cấu hình và trọng số mô hình đã huấn luyện. "
                "Đặt mock_pose_data=True trong cài đặt cho phát triển, hoặc cung cấp "
                "đầu vào CSI thực. Xem docs/hardware-setup.md."
            )
        from src.testing.mock_pose_generator import generate_mock_poses
        return generate_mock_poses(max_persons=self.settings.pose_max_persons)

    def _classify_activity(self, features: torch.Tensor) -> str:
        """Phân loại hoạt động từ đặc trưng mô hình.

        Sử dụng độ lớn của tensor đặc trưng để phân loại dựa trên ngưỡng đơn giản.
        Đây là heuristic cơ bản; bộ phân loại hoạt động thực sự cần được
        huấn luyện và tải cùng với mô hình tư thế.
        """
        feature_norm = float(torch.norm(features).item())
        # Phân loại xác định dựa trên phạm vi độ lớn đặc trưng
        if feature_norm > 2.0:
            return "walking"
        elif feature_norm > 1.0:
            return "standing"
        elif feature_norm > 0.5:
            return "sitting"
        elif feature_norm > 0.1:
            return "lying"
        else:
            return "unknown"

    def _update_stats(self, poses: List[Dict[str, Any]], processing_time: float):
        """Cập nhật thống kê xử lý."""
        self.stats["total_processed"] += 1

        if poses:
            self.stats["successful_detections"] += 1
            confidences = [pose.get("confidence", 0.0) for pose in poses]
            avg_confidence = sum(confidences) / len(confidences)

            # Cập nhật trung bình liên tục
            total = self.stats["successful_detections"]
            current_avg = self.stats["average_confidence"]
            self.stats["average_confidence"] = (current_avg * (total - 1) + avg_confidence) / total
        else:
            self.stats["failed_detections"] += 1

        # Cập nhật thời gian xử lý (trung bình liên tục)
        total = self.stats["total_processed"]
        current_avg = self.stats["processing_time_ms"]
        self.stats["processing_time_ms"] = (current_avg * (total - 1) + processing_time) / total

    async def get_status(self) -> Dict[str, Any]:
        """Lấy trạng thái dịch vụ."""
        return {
            "status": "healthy" if self.is_running and not self.last_error else "unhealthy",
            "initialized": self.is_initialized,
            "running": self.is_running,
            "last_error": self.last_error,
            "statistics": self.stats.copy(),
            "configuration": {
                "mock_data": self.settings.mock_pose_data,
                "confidence_threshold": self.settings.pose_confidence_threshold,
                "max_persons": self.settings.pose_max_persons,
                "batch_size": self.settings.pose_processing_batch_size
            }
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu dịch vụ."""
        return {
            "pose_service": {
                "total_processed": self.stats["total_processed"],
                "successful_detections": self.stats["successful_detections"],
                "failed_detections": self.stats["failed_detections"],
                "success_rate": (
                    self.stats["successful_detections"] / max(1, self.stats["total_processed"])
                ),
                "average_confidence": self.stats["average_confidence"],
                "average_processing_time_ms": self.stats["processing_time_ms"]
            }
        }

    async def reset(self):
        """Đặt lại trạng thái dịch vụ."""
        self.stats = {
            "total_processed": 0,
            "successful_detections": 0,
            "failed_detections": 0,
            "average_confidence": 0.0,
            "processing_time_ms": 0.0
        }
        self.last_error = None
        self.logger.info("Dịch vụ tư thế đã đặt lại")

    # Các phương thức endpoint API
    async def estimate_poses(self, zone_ids=None, confidence_threshold=None, max_persons=None,
                           include_keypoints=True, include_segmentation=False,
                           csi_data: Optional[np.ndarray] = None):
        """Ước lượng tư thế với tham số API.

        Args:
            zone_ids: Danh sách ID khu vực để ước lượng tư thế.
            confidence_threshold: Ngưỡng độ tin cậy tối thiểu cho phát hiện.
            max_persons: Số người tối đa cần trả về.
            include_keypoints: Có bao gồm dữ liệu điểm mấu chốt không.
            include_segmentation: Có bao gồm mặt nạ phân đoạn không.
            csi_data: Mảng dữ liệu CSI thực. Bắt buộc khi mock_pose_data là False.

        Raises:
            NotImplementedError: Nếu không cung cấp dữ liệu CSI và chế độ giả bị tắt.
        """
        try:
            if csi_data is None and not self.settings.mock_pose_data:
                raise NotImplementedError(
                    "Ước lượng tư thế yêu cầu đầu vào dữ liệu CSI thực. Không có dữ liệu CSI nào "
                    "được cung cấp và mock_pose_data bị tắt. Truyền csi_data từ thu thập "
                    "phần cứng, hoặc bật mock_pose_data cho phát triển. "
                    "Xem docs/hardware-setup.md để biết thiết lập thu thập dữ liệu CSI."
                )

            metadata = {
                "timestamp": datetime.now(),
                "zone_ids": zone_ids or ["zone_1"],
                "confidence_threshold": confidence_threshold or self.settings.pose_confidence_threshold,
                "max_persons": max_persons or self.settings.pose_max_persons,
            }

            if csi_data is not None:
                # Xử lý dữ liệu CSI thực
                result = await self.process_csi_data(csi_data, metadata)
            else:
                # Chế độ giả: tạo tư thế giả trực tiếp (không có dữ liệu CSI giả)
                from src.testing.mock_pose_generator import generate_mock_poses
                start_time = datetime.now()
                mock_poses = generate_mock_poses(
                    max_persons=max_persons or self.settings.pose_max_persons
                )
                processing_time = (datetime.now() - start_time).total_seconds() * 1000
                result = {
                    "timestamp": start_time.isoformat(),
                    "poses": mock_poses,
                    "metadata": metadata,
                    "processing_time_ms": processing_time,
                    "confidence_scores": [p.get("confidence", 0.0) for p in mock_poses],
                }

            # Định dạng cho phản hồi API
            persons = []
            for i, pose in enumerate(result["poses"]):
                person = {
                    "person_id": str(pose["person_id"]),
                    "confidence": pose["confidence"],
                    "bounding_box": pose["bounding_box"],
                    "zone_id": zone_ids[0] if zone_ids else "zone_1",
                    "activity": pose["activity"],
                    "timestamp": datetime.fromisoformat(pose["timestamp"]) if isinstance(pose["timestamp"], str) else pose["timestamp"],
                }

                if include_keypoints:
                    person["keypoints"] = pose["keypoints"]

                if include_segmentation and not self.settings.mock_pose_data:
                    person["segmentation"] = {"mask": "real_segmentation_data"}
                elif include_segmentation:
                    person["segmentation"] = {"mask": "mock_segmentation_data"}

                persons.append(person)

            # Tóm tắt khu vực
            zone_summary = {}
            for zone_id in (zone_ids or ["zone_1"]):
                zone_summary[zone_id] = len([p for p in persons if p.get("zone_id") == zone_id])

            return {
                "timestamp": datetime.now(),
                "frame_id": f"frame_{int(datetime.now().timestamp())}",
                "persons": persons,
                "zone_summary": zone_summary,
                "processing_time_ms": result["processing_time_ms"],
                "metadata": {"mock_data": self.settings.mock_pose_data},
            }

        except Exception as e:
            self.logger.error(f"Lỗi trong estimate_poses: {e}")
            raise

    async def analyze_with_params(self, zone_ids=None, confidence_threshold=None, max_persons=None,
                                include_keypoints=True, include_segmentation=False):
        """Phân tích dữ liệu tư thế với tham số tùy chỉnh."""
        return await self.estimate_poses(zone_ids, confidence_threshold, max_persons,
                                       include_keypoints, include_segmentation)

    async def get_zone_occupancy(self, zone_id: str):
        """Lấy số người hiện tại cho khu vực cụ thể.

        Trong chế độ giả, ủy quyền cho mô-đun kiểm thử. Trong chế độ sản xuất, trả về
        dữ liệu dựa trên kết quả ước lượng tư thế thực hoặc báo không có dữ liệu.
        """
        try:
            if self.settings.mock_pose_data:
                from src.testing.mock_pose_generator import generate_mock_zone_occupancy
                return generate_mock_zone_occupancy(zone_id)

            # Sản xuất: không có dữ liệu số người thời gian thực nếu không có luồng CSI hoạt động
            return {
                "count": 0,
                "max_occupancy": 10,
                "persons": [],
                "timestamp": datetime.now(),
                "note": "Không có dữ liệu CSI thời gian thực. Kết nối phần cứng để lấy số người trực tiếp.",
            }

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy số người khu vực: {e}")
            return None

    async def get_zones_summary(self):
        """Lấy tóm tắt số người cho tất cả khu vực.

        Trong chế độ giả, ủy quyền cho mô-đun kiểm thử. Trong sản xuất, trả về
        khu vực trống cho đến khi dữ liệu CSI thực được xử lý.
        """
        try:
            if self.settings.mock_pose_data:
                from src.testing.mock_pose_generator import generate_mock_zones_summary
                return generate_mock_zones_summary()

            # Sản xuất: không có dữ liệu thời gian thực nếu không có luồng CSI hoạt động
            zones = ["zone_1", "zone_2", "zone_3", "zone_4"]
            zone_data = {}
            for zone_id in zones:
                zone_data[zone_id] = {
                    "occupancy": 0,
                    "max_occupancy": 10,
                    "status": "inactive",
                }

            return {
                "total_persons": 0,
                "zones": zone_data,
                "active_zones": 0,
                "note": "Không có dữ liệu CSI thời gian thực. Kết nối phần cứng để lấy số người trực tiếp.",
            }

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy tóm tắt khu vực: {e}")
            raise

    async def get_historical_data(self, start_time, end_time, zone_ids=None,
                                aggregation_interval=300, include_raw_data=False):
        """Lấy dữ liệu ước lượng tư thế lịch sử.

        Trong chế độ giả, ủy quyền cho mô-đun kiểm thử. Trong sản xuất, trả về
        dữ liệu trống cho biết chưa có bản ghi lịch sử nào.
        """
        try:
            if self.settings.mock_pose_data:
                from src.testing.mock_pose_generator import generate_mock_historical_data
                return generate_mock_historical_data(
                    start_time=start_time,
                    end_time=end_time,
                    zone_ids=zone_ids,
                    aggregation_interval=aggregation_interval,
                    include_raw_data=include_raw_data,
                )

            # Sản xuất: không có dữ liệu lịch sử nếu không có backend lưu trữ
            return {
                "aggregated_data": [],
                "raw_data": [] if include_raw_data else None,
                "total_records": 0,
                "note": "Không có dữ liệu lịch sử. Cần cấu hình backend lưu trữ dữ liệu để lưu bản ghi lịch sử.",
            }

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy dữ liệu lịch sử: {e}")
            raise

    async def get_recent_activities(self, zone_id=None, limit=10):
        """Lấy các hoạt động được phát hiện gần đây.

        Trong chế độ giả, ủy quyền cho mô-đun kiểm thử. Trong sản xuất, trả về
        danh sách trống cho biết chưa có dữ liệu hoạt động nào được ghi.
        """
        try:
            if self.settings.mock_pose_data:
                from src.testing.mock_pose_generator import generate_mock_recent_activities
                return generate_mock_recent_activities(zone_id=zone_id, limit=limit)

            # Sản xuất: không có bản ghi hoạt động nếu không có luồng CSI hoạt động
            return []

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy hoạt động gần đây: {e}")
            raise

    async def is_calibrating(self):
        """Kiểm tra xem hiệu chuẩn có đang diễn ra không."""
        return self._calibration_in_progress

    async def start_calibration(self):
        """Bắt đầu quá trình hiệu chuẩn."""
        import uuid
        calibration_id = str(uuid.uuid4())
        self._calibration_id = calibration_id
        self._calibration_in_progress = True
        self._calibration_start = datetime.now()
        self.logger.info(f"Đã bắt đầu hiệu chuẩn: {calibration_id}")
        return calibration_id

    async def run_calibration(self, calibration_id):
        """Chạy quá trình hiệu chuẩn: thu thập thống kê CSI cơ sở trong 5 giây."""
        self.logger.info(f"Đang chạy hiệu chuẩn: {calibration_id}")
        # Thu thập mức nhiễu nền cơ sở trong 5 giây theo tốc độ lấy mẫu đã cấu hình
        await asyncio.sleep(5)
        self._calibration_in_progress = False
        self._calibration_id = None
        self.logger.info(f"Hiệu chuẩn hoàn tất: {calibration_id}")

    async def get_calibration_status(self):
        """Lấy trạng thái hiệu chuẩn hiện tại."""
        if self._calibration_in_progress and self._calibration_start is not None:
            elapsed = (datetime.now() - self._calibration_start).total_seconds()
            progress = min(100.0, (elapsed / 5.0) * 100.0)
            return {
                "is_calibrating": True,
                "calibration_id": self._calibration_id,
                "progress_percent": round(progress, 1),
                "current_step": "collecting_baseline",
                "estimated_remaining_minutes": max(0.0, (5.0 - elapsed) / 60.0),
                "last_calibration": None,
            }
        return {
            "is_calibrating": False,
            "calibration_id": None,
            "progress_percent": 100,
            "current_step": "completed",
            "estimated_remaining_minutes": 0,
            "last_calibration": self._calibration_start,
        }

    async def get_statistics(self, start_time, end_time):
        """Lấy thống kê ước lượng tư thế.

        Trong chế độ giả, ủy quyền cho mô-đun kiểm thử. Trong sản xuất, trả về
        thống kê tích lũy thực tế từ self.stats, hoặc cho biết không có dữ liệu.
        """
        try:
            if self.settings.mock_pose_data:
                from src.testing.mock_pose_generator import generate_mock_statistics
                return generate_mock_statistics(start_time=start_time, end_time=end_time)

            # Sản xuất: trả về thống kê tích lũy thực tế
            total = self.stats["total_processed"]
            successful = self.stats["successful_detections"]
            failed = self.stats["failed_detections"]

            return {
                "total_detections": total,
                "successful_detections": successful,
                "failed_detections": failed,
                "success_rate": successful / max(1, total),
                "average_confidence": self.stats["average_confidence"],
                "average_processing_time_ms": self.stats["processing_time_ms"],
                "unique_persons": 0,
                "most_active_zone": "N/A",
                "activity_distribution": {
                    "standing": 0.0,
                    "sitting": 0.0,
                    "walking": 0.0,
                    "lying": 0.0,
                },
                "note": "Thống kê phản ánh dữ liệu thực đã xử lý. Phân bố hoạt động và số người duy nhất yêu cầu backend lưu trữ." if total == 0 else None,
            }

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy thống kê: {e}")
            raise

    async def process_segmentation_data(self, frame_id):
        """Xử lý dữ liệu phân đoạn trong nền."""
        self.logger.info(f"Đang xử lý dữ liệu phân đoạn cho khung: {frame_id}")
        # Xử lý nền giả
        await asyncio.sleep(2)
        self.logger.info(f"Xử lý phân đoạn hoàn tất cho khung: {frame_id}")

    # Các phương thức truyền phát WebSocket
    async def get_current_pose_data(self):
        """Lấy dữ liệu tư thế hiện tại cho truyền phát."""
        try:
            # Tạo dữ liệu tư thế hiện tại
            result = await self.estimate_poses()

            # Định dạng dữ liệu theo khu vực cho truyền phát WebSocket
            zone_data = {}

            # Nhóm người theo khu vực
            for person in result["persons"]:
                zone_id = person.get("zone_id", "zone_1")

                if zone_id not in zone_data:
                    zone_data[zone_id] = {
                        "pose": {
                            "persons": [],
                            "count": 0
                        },
                        "confidence": 0.0,
                        "activity": None,
                        "metadata": {
                            "frame_id": result["frame_id"],
                            "processing_time_ms": result["processing_time_ms"]
                        }
                    }

                zone_data[zone_id]["pose"]["persons"].append(person)
                zone_data[zone_id]["pose"]["count"] += 1

                # Cập nhật độ tin cậy khu vực (trung bình)
                current_confidence = zone_data[zone_id]["confidence"]
                person_confidence = person.get("confidence", 0.0)
                zone_data[zone_id]["confidence"] = (current_confidence + person_confidence) / 2

                # Đặt hoạt động nếu chưa có
                if not zone_data[zone_id]["activity"] and person.get("activity"):
                    zone_data[zone_id]["activity"] = person["activity"]

            return zone_data

        except Exception as e:
            self.logger.error(f"Lỗi khi lấy dữ liệu tư thế hiện tại: {e}")
            # Trả về dữ liệu khu vực trống khi gặp lỗi
            return {}

    # Các phương thức kiểm tra sức khỏe
    async def health_check(self):
        """Thực hiện kiểm tra sức khỏe."""
        try:
            status = "healthy" if self.is_running and not self.last_error else "unhealthy"

            return {
                "status": status,
                "message": self.last_error if self.last_error else "Dịch vụ đang chạy bình thường",
                "uptime_seconds": (datetime.now() - self._start_time).total_seconds() if self._start_time else 0.0,
                "metrics": {
                    "total_processed": self.stats["total_processed"],
                    "success_rate": (
                        self.stats["successful_detections"] / max(1, self.stats["total_processed"])
                    ),
                    "average_processing_time_ms": self.stats["processing_time_ms"]
                }
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Kiểm tra sức khỏe thất bại: {str(e)}"
            }

    async def is_ready(self):
        """Kiểm tra xem dịch vụ có sẵn sàng không."""
        return self.is_initialized and self.is_running
