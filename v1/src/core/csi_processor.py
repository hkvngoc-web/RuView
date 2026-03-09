"""Bộ xử lý dữ liệu CSI cho hệ thống WiFi-DensePose sử dụng phương pháp TDD."""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from collections import deque
import scipy.signal
import scipy.fft

try:
    from ..hardware.csi_extractor import CSIData
except ImportError:
    # Xử lý import cho kiểm thử
    from src.hardware.csi_extractor import CSIData


class CSIProcessingError(Exception):
    """Ngoại lệ phát sinh khi xử lý CSI gặp lỗi."""
    pass


@dataclass
class CSIFeatures:
    """Cấu trúc dữ liệu cho các đặc trưng CSI đã trích xuất."""
    amplitude_mean: np.ndarray
    amplitude_variance: np.ndarray
    phase_difference: np.ndarray
    correlation_matrix: np.ndarray
    doppler_shift: np.ndarray
    power_spectral_density: np.ndarray
    timestamp: datetime
    metadata: Dict[str, Any]


@dataclass
class HumanDetectionResult:
    """Cấu trúc dữ liệu cho kết quả phát hiện con người."""
    human_detected: bool
    confidence: float
    motion_score: float
    timestamp: datetime
    features: CSIFeatures
    metadata: Dict[str, Any]


class CSIProcessor:
    """Xử lý dữ liệu CSI cho phát hiện con người và ước lượng tư thế."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Khởi tạo bộ xử lý CSI.

        Args:
            config: Từ điển cấu hình
            logger: Thể hiện logger tùy chọn

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        self._validate_config(config)

        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Tham số xử lý
        self.sampling_rate = config['sampling_rate']
        self.window_size = config['window_size']
        self.overlap = config['overlap']
        self.noise_threshold = config['noise_threshold']
        self.human_detection_threshold = config.get('human_detection_threshold', 0.8)
        self.smoothing_factor = config.get('smoothing_factor', 0.9)
        self.max_history_size = config.get('max_history_size', 500)

        # Cờ trích xuất đặc trưng
        self.enable_preprocessing = config.get('enable_preprocessing', True)
        self.enable_feature_extraction = config.get('enable_feature_extraction', True)
        self.enable_human_detection = config.get('enable_human_detection', True)

        # Trạng thái xử lý
        self.csi_history = deque(maxlen=self.max_history_size)
        self.previous_detection_confidence = 0.0

        # Bộ đệm Doppler: pha trung bình được tính trước cho mỗi khung để thêm O(1)
        self._phase_cache = deque(maxlen=self.max_history_size)
        self._doppler_window = min(config.get('doppler_window', 64), self.max_history_size)

        # Theo dõi thống kê
        self._total_processed = 0
        self._processing_errors = 0
        self._human_detections = 0

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Xác thực tham số cấu hình.

        Args:
            config: Cấu hình cần xác thực

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        required_fields = ['sampling_rate', 'window_size', 'overlap', 'noise_threshold']
        missing_fields = [field for field in required_fields if field not in config]

        if missing_fields:
            raise ValueError(f"Thiếu cấu hình bắt buộc: {missing_fields}")

        if config['sampling_rate'] <= 0:
            raise ValueError("sampling_rate phải là số dương")

        if config['window_size'] <= 0:
            raise ValueError("window_size phải là số dương")

        if not 0 <= config['overlap'] < 1:
            raise ValueError("overlap phải nằm trong khoảng 0 đến 1")

    def preprocess_csi_data(self, csi_data: CSIData) -> CSIData:
        """Tiền xử lý dữ liệu CSI để trích xuất đặc trưng.

        Args:
            csi_data: Dữ liệu CSI thô

        Returns:
            Dữ liệu CSI đã tiền xử lý

        Raises:
            CSIProcessingError: Nếu tiền xử lý thất bại
        """
        if not self.enable_preprocessing:
            return csi_data

        try:
            # Loại bỏ nhiễu khỏi tín hiệu
            cleaned_data = self._remove_noise(csi_data)

            # Áp dụng hàm cửa sổ
            windowed_data = self._apply_windowing(cleaned_data)

            # Chuẩn hóa giá trị biên độ
            normalized_data = self._normalize_amplitude(windowed_data)

            return normalized_data

        except Exception as e:
            raise CSIProcessingError(f"Tiền xử lý dữ liệu CSI thất bại: {e}")

    def extract_features(self, csi_data: CSIData) -> Optional[CSIFeatures]:
        """Trích xuất đặc trưng từ dữ liệu CSI.

        Args:
            csi_data: Dữ liệu CSI đã tiền xử lý

        Returns:
            Đặc trưng đã trích xuất hoặc None nếu bị tắt

        Raises:
            CSIProcessingError: Nếu trích xuất đặc trưng thất bại
        """
        if not self.enable_feature_extraction:
            return None

        try:
            # Trích xuất đặc trưng dựa trên biên độ
            amplitude_mean, amplitude_variance = self._extract_amplitude_features(csi_data)

            # Trích xuất đặc trưng dựa trên pha
            phase_difference = self._extract_phase_features(csi_data)

            # Trích xuất đặc trưng tương quan
            correlation_matrix = self._extract_correlation_features(csi_data)

            # Trích xuất đặc trưng Doppler và miền tần số
            doppler_shift, power_spectral_density = self._extract_doppler_features(csi_data)

            return CSIFeatures(
                amplitude_mean=amplitude_mean,
                amplitude_variance=amplitude_variance,
                phase_difference=phase_difference,
                correlation_matrix=correlation_matrix,
                doppler_shift=doppler_shift,
                power_spectral_density=power_spectral_density,
                timestamp=datetime.now(timezone.utc),
                metadata={'processing_params': self.config}
            )

        except Exception as e:
            raise CSIProcessingError(f"Trích xuất đặc trưng thất bại: {e}")

    def detect_human_presence(self, features: CSIFeatures) -> Optional[HumanDetectionResult]:
        """Phát hiện sự hiện diện con người từ đặc trưng CSI.

        Args:
            features: Đặc trưng CSI đã trích xuất

        Returns:
            Kết quả phát hiện hoặc None nếu bị tắt

        Raises:
            CSIProcessingError: Nếu phát hiện thất bại
        """
        if not self.enable_human_detection:
            return None

        try:
            # Phân tích mẫu chuyển động
            motion_score = self._analyze_motion_patterns(features)

            # Tính độ tin cậy phát hiện
            raw_confidence = self._calculate_detection_confidence(features, motion_score)

            # Áp dụng làm mượt theo thời gian
            smoothed_confidence = self._apply_temporal_smoothing(raw_confidence)

            # Xác định liệu có phát hiện con người không
            human_detected = smoothed_confidence >= self.human_detection_threshold

            if human_detected:
                self._human_detections += 1

            return HumanDetectionResult(
                human_detected=human_detected,
                confidence=smoothed_confidence,
                motion_score=motion_score,
                timestamp=datetime.now(timezone.utc),
                features=features,
                metadata={'threshold': self.human_detection_threshold}
            )

        except Exception as e:
            raise CSIProcessingError(f"Phát hiện sự hiện diện con người thất bại: {e}")

    async def process_csi_data(self, csi_data: CSIData) -> HumanDetectionResult:
        """Xử lý dữ liệu CSI qua toàn bộ pipeline.

        Args:
            csi_data: Dữ liệu CSI thô

        Returns:
            Kết quả phát hiện con người

        Raises:
            CSIProcessingError: Nếu xử lý thất bại
        """
        try:
            self._total_processed += 1

            # Tiền xử lý dữ liệu
            preprocessed_data = self.preprocess_csi_data(csi_data)

            # Trích xuất đặc trưng
            features = self.extract_features(preprocessed_data)

            # Phát hiện sự hiện diện con người
            detection_result = self.detect_human_presence(features)

            # Thêm vào lịch sử
            self.add_to_history(csi_data)

            return detection_result

        except Exception as e:
            self._processing_errors += 1
            raise CSIProcessingError(f"Xử lý pipeline thất bại: {e}")

    def add_to_history(self, csi_data: CSIData) -> None:
        """Thêm dữ liệu CSI vào lịch sử xử lý.

        Args:
            csi_data: Dữ liệu CSI cần thêm vào lịch sử
        """
        self.csi_history.append(csi_data)
        # Cache pha trung bình để trích xuất Doppler nhanh
        if csi_data.phase.ndim == 2:
            self._phase_cache.append(np.mean(csi_data.phase, axis=0))
        else:
            self._phase_cache.append(csi_data.phase.flatten())

    def clear_history(self) -> None:
        """Xóa lịch sử dữ liệu CSI."""
        self.csi_history.clear()
        self._phase_cache.clear()

    def get_recent_history(self, count: int) -> List[CSIData]:
        """Lấy dữ liệu CSI gần đây từ lịch sử.

        Args:
            count: Số mục gần đây cần trả về

        Returns:
            Danh sách các mục dữ liệu CSI gần đây
        """
        if count >= len(self.csi_history):
            return list(self.csi_history)
        else:
            return list(self.csi_history)[-count:]

    def get_processing_statistics(self) -> Dict[str, Any]:
        """Lấy thống kê xử lý.

        Returns:
            Từ điển chứa thống kê xử lý
        """
        error_rate = self._processing_errors / self._total_processed if self._total_processed > 0 else 0
        detection_rate = self._human_detections / self._total_processed if self._total_processed > 0 else 0

        return {
            'total_processed': self._total_processed,
            'processing_errors': self._processing_errors,
            'human_detections': self._human_detections,
            'error_rate': error_rate,
            'detection_rate': detection_rate,
            'history_size': len(self.csi_history)
        }

    def reset_statistics(self) -> None:
        """Đặt lại thống kê xử lý."""
        self._total_processed = 0
        self._processing_errors = 0
        self._human_detections = 0

    # Các phương thức xử lý riêng
    def _remove_noise(self, csi_data: CSIData) -> CSIData:
        """Loại bỏ nhiễu khỏi dữ liệu CSI."""
        # Áp dụng lọc nhiễu dựa trên ngưỡng
        amplitude_db = 20 * np.log10(np.abs(csi_data.amplitude) + 1e-12)
        noise_mask = amplitude_db > self.noise_threshold

        filtered_amplitude = csi_data.amplitude.copy()
        filtered_amplitude[~noise_mask] = 0

        return CSIData(
            timestamp=csi_data.timestamp,
            amplitude=filtered_amplitude,
            phase=csi_data.phase,
            frequency=csi_data.frequency,
            bandwidth=csi_data.bandwidth,
            num_subcarriers=csi_data.num_subcarriers,
            num_antennas=csi_data.num_antennas,
            snr=csi_data.snr,
            metadata={**csi_data.metadata, 'noise_filtered': True}
        )

    def _apply_windowing(self, csi_data: CSIData) -> CSIData:
        """Áp dụng hàm cửa sổ cho dữ liệu CSI."""
        # Áp dụng cửa sổ Hamming để giảm rò rỉ phổ
        window = scipy.signal.windows.hamming(csi_data.num_subcarriers)
        windowed_amplitude = csi_data.amplitude * window[np.newaxis, :]

        return CSIData(
            timestamp=csi_data.timestamp,
            amplitude=windowed_amplitude,
            phase=csi_data.phase,
            frequency=csi_data.frequency,
            bandwidth=csi_data.bandwidth,
            num_subcarriers=csi_data.num_subcarriers,
            num_antennas=csi_data.num_antennas,
            snr=csi_data.snr,
            metadata={**csi_data.metadata, 'windowed': True}
        )

    def _normalize_amplitude(self, csi_data: CSIData) -> CSIData:
        """Chuẩn hóa giá trị biên độ."""
        # Chuẩn hóa về phương sai đơn vị
        normalized_amplitude = csi_data.amplitude / (np.std(csi_data.amplitude) + 1e-12)

        return CSIData(
            timestamp=csi_data.timestamp,
            amplitude=normalized_amplitude,
            phase=csi_data.phase,
            frequency=csi_data.frequency,
            bandwidth=csi_data.bandwidth,
            num_subcarriers=csi_data.num_subcarriers,
            num_antennas=csi_data.num_antennas,
            snr=csi_data.snr,
            metadata={**csi_data.metadata, 'normalized': True}
        )

    def _extract_amplitude_features(self, csi_data: CSIData) -> tuple:
        """Trích xuất đặc trưng dựa trên biên độ."""
        amplitude_mean = np.mean(csi_data.amplitude, axis=0)
        amplitude_variance = np.var(csi_data.amplitude, axis=0)
        return amplitude_mean, amplitude_variance

    def _extract_phase_features(self, csi_data: CSIData) -> np.ndarray:
        """Trích xuất đặc trưng dựa trên pha."""
        # Tính hiệu pha giữa các sóng mang con liền kề
        phase_diff = np.diff(csi_data.phase, axis=1)
        return np.mean(phase_diff, axis=0)

    def _extract_correlation_features(self, csi_data: CSIData) -> np.ndarray:
        """Trích xuất đặc trưng tương quan giữa các ăng-ten."""
        # Tính ma trận tương quan giữa các ăng-ten
        correlation_matrix = np.corrcoef(csi_data.amplitude)
        return correlation_matrix

    def _extract_doppler_features(self, csi_data: CSIData) -> tuple:
        """Trích xuất đặc trưng Doppler và miền tần số từ lịch sử CSI theo thời gian.

        Sử dụng giá trị pha trung bình đã cache để truy cập O(1) thay vì tính lại
        từ các khung CSI thô. Chỉ sử dụng `doppler_window` khung cuối cùng
        (mặc định 64) để đảm bảo thời gian tính toán có giới hạn.

        Returns:
            tuple: (doppler_shift, power_spectral_density) dưới dạng mảng numpy
        """
        n_doppler_bins = 64

        if len(self._phase_cache) >= 2:
            # Sử dụng giá trị pha trung bình đã cache (tính trước trong add_to_history)
            # Chỉ lấy doppler_window khung cuối để chi phí có giới hạn
            window = min(len(self._phase_cache), self._doppler_window)
            cache_list = list(self._phase_cache)
            phase_matrix = np.array(cache_list[-window:])

            # Hiệu pha theo thời gian giữa các khung liên tiếp
            phase_diffs = np.diff(phase_matrix, axis=0)

            # Trung bình qua các sóng mang con cho mỗi bước thời gian
            mean_phase_diff = np.mean(phase_diffs, axis=1)

            # FFT cho phổ Doppler
            doppler_spectrum = np.abs(scipy.fft.fft(mean_phase_diff, n=n_doppler_bins)) ** 2

            # Chuẩn hóa
            max_val = np.max(doppler_spectrum)
            if max_val > 0:
                doppler_spectrum = doppler_spectrum / max_val

            doppler_shift = doppler_spectrum
        else:
            doppler_shift = np.zeros(n_doppler_bins)

        # Mật độ phổ công suất của khung hiện tại
        psd = np.abs(scipy.fft.fft(csi_data.amplitude.flatten(), n=128)) ** 2

        return doppler_shift, psd

    def _analyze_motion_patterns(self, features: CSIFeatures) -> float:
        """Phân tích mẫu chuyển động từ đặc trưng."""
        # Phân tích phương sai và mẫu tương quan để phát hiện chuyển động
        variance_score = np.mean(features.amplitude_variance)
        correlation_score = np.mean(np.abs(features.correlation_matrix - np.eye(features.correlation_matrix.shape[0])))

        # Kết hợp điểm (phương pháp đơn giản)
        motion_score = 0.6 * variance_score + 0.4 * correlation_score
        return np.clip(motion_score, 0.0, 1.0)

    def _calculate_detection_confidence(self, features: CSIFeatures, motion_score: float) -> float:
        """Tính độ tin cậy phát hiện dựa trên đặc trưng."""
        # Kết hợp nhiều chỉ số đặc trưng
        amplitude_indicator = np.mean(features.amplitude_mean) > 0.1
        phase_indicator = np.std(features.phase_difference) > 0.05
        motion_indicator = motion_score > 0.3

        # Đánh trọng số các chỉ số
        confidence = (0.4 * amplitude_indicator + 0.3 * phase_indicator + 0.3 * motion_indicator)
        return np.clip(confidence, 0.0, 1.0)

    def _apply_temporal_smoothing(self, raw_confidence: float) -> float:
        """Áp dụng làm mượt theo thời gian cho độ tin cậy phát hiện."""
        # Trung bình động hàm mũ
        smoothed_confidence = (self.smoothing_factor * self.previous_detection_confidence +
                             (1 - self.smoothing_factor) * raw_confidence)

        self.previous_detection_confidence = smoothed_confidence
        return smoothed_confidence
