"""Đầu DensePose cho hệ thống WiFi-DensePose."""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Any, Tuple, List


class DensePoseError(Exception):
    """Ngoại lệ phát sinh khi gặp lỗi đầu DensePose."""
    pass


class DensePoseHead(nn.Module):
    """Đầu DensePose cho phân đoạn bộ phận cơ thể và hồi quy tọa độ UV."""

    def __init__(self, config: Dict[str, Any]):
        """Khởi tạo đầu DensePose.

        Args:
            config: Từ điển cấu hình với các tham số đầu
        """
        super().__init__()

        self._validate_config(config)
        self.config = config

        self.input_channels = config['input_channels']
        self.num_body_parts = config['num_body_parts']
        self.num_uv_coordinates = config['num_uv_coordinates']
        self.hidden_channels = config.get('hidden_channels', [128, 64])
        self.kernel_size = config.get('kernel_size', 3)
        self.padding = config.get('padding', 1)
        self.dropout_rate = config.get('dropout_rate', 0.1)
        self.use_deformable_conv = config.get('use_deformable_conv', False)
        self.use_fpn = config.get('use_fpn', False)
        self.fpn_levels = config.get('fpn_levels', [2, 3, 4, 5])
        self.output_stride = config.get('output_stride', 4)

        # Mạng kim tự tháp đặc trưng (tùy chọn)
        if self.use_fpn:
            self.fpn = self._build_fpn()

        # Xử lý đặc trưng dùng chung
        self.shared_conv = self._build_shared_layers()

        # Đầu phân đoạn cho phân loại bộ phận cơ thể
        self.segmentation_head = self._build_segmentation_head()

        # Đầu hồi quy UV cho dự đoán tọa độ
        self.uv_regression_head = self._build_uv_regression_head()

        # Khởi tạo trọng số
        self._initialize_weights()

    def _validate_config(self, config: Dict[str, Any]):
        """Xác thực tham số cấu hình."""
        required_fields = ['input_channels', 'num_body_parts', 'num_uv_coordinates']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Thiếu trường bắt buộc: {field}")

        if config['input_channels'] <= 0:
            raise ValueError("input_channels phải là số dương")

        if config['num_body_parts'] <= 0:
            raise ValueError("num_body_parts phải là số dương")

        if config['num_uv_coordinates'] <= 0:
            raise ValueError("num_uv_coordinates phải là số dương")

    def _build_fpn(self) -> nn.Module:
        """Xây dựng Mạng kim tự tháp đặc trưng."""
        return nn.ModuleDict({
            f'level_{level}': nn.Conv2d(self.input_channels, self.input_channels, 1)
            for level in self.fpn_levels
        })

    def _build_shared_layers(self) -> nn.Module:
        """Xây dựng các lớp xử lý đặc trưng dùng chung."""
        layers = []
        in_channels = self.input_channels

        for hidden_dim in self.hidden_channels:
            layers.extend([
                nn.Conv2d(in_channels, hidden_dim,
                         kernel_size=self.kernel_size,
                         padding=self.padding),
                nn.BatchNorm2d(hidden_dim),
                nn.ReLU(inplace=True),
                nn.Dropout2d(self.dropout_rate)
            ])
            in_channels = hidden_dim

        return nn.Sequential(*layers)

    def _build_segmentation_head(self) -> nn.Module:
        """Xây dựng đầu phân đoạn cho phân loại bộ phận cơ thể."""
        final_hidden = self.hidden_channels[-1] if self.hidden_channels else self.input_channels

        return nn.Sequential(
            nn.Conv2d(final_hidden, final_hidden // 2,
                     kernel_size=self.kernel_size,
                     padding=self.padding),
            nn.BatchNorm2d(final_hidden // 2),
            nn.ReLU(inplace=True),
            nn.Dropout2d(self.dropout_rate),

            # Tăng mẫu để nâng độ phân giải
            nn.ConvTranspose2d(final_hidden // 2, final_hidden // 4,
                             kernel_size=4, stride=2, padding=1),
            nn.BatchNorm2d(final_hidden // 4),
            nn.ReLU(inplace=True),

            nn.Conv2d(final_hidden // 4, self.num_body_parts + 1, kernel_size=1),
            # +1 cho lớp nền
        )

    def _build_uv_regression_head(self) -> nn.Module:
        """Xây dựng đầu hồi quy UV cho dự đoán tọa độ."""
        final_hidden = self.hidden_channels[-1] if self.hidden_channels else self.input_channels

        return nn.Sequential(
            nn.Conv2d(final_hidden, final_hidden // 2,
                     kernel_size=self.kernel_size,
                     padding=self.padding),
            nn.BatchNorm2d(final_hidden // 2),
            nn.ReLU(inplace=True),
            nn.Dropout2d(self.dropout_rate),

            # Tăng mẫu để nâng độ phân giải
            nn.ConvTranspose2d(final_hidden // 2, final_hidden // 4,
                             kernel_size=4, stride=2, padding=1),
            nn.BatchNorm2d(final_hidden // 4),
            nn.ReLU(inplace=True),

            nn.Conv2d(final_hidden // 4, self.num_uv_coordinates, kernel_size=1),
        )

    def _initialize_weights(self):
        """Khởi tạo trọng số mạng."""
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Lan truyền tiến qua đầu DensePose.

        Args:
            x: Tensor đặc trưng đầu vào có hình dạng (batch_size, channels, height, width)

        Returns:
            Từ điển chứa:
            - segmentation: Logit bộ phận cơ thể (batch_size, num_parts+1, height, width)
            - uv_coordinates: Tọa độ UV (batch_size, 2, height, width)
        """
        # Xác thực hình dạng đầu vào
        if x.shape[1] != self.input_channels:
            raise DensePoseError(f"Mong đợi {self.input_channels} kênh đầu vào, nhận được {x.shape[1]}")

        # Áp dụng FPN nếu được bật
        if self.use_fpn:
            # Xử lý FPN đơn giản - trong thực tế sẽ phức tạp hơn
            x = self.fpn['level_2'](x)

        # Xử lý đặc trưng dùng chung
        shared_features = self.shared_conv(x)

        # Nhánh phân đoạn
        segmentation_logits = self.segmentation_head(shared_features)

        # Nhánh hồi quy UV
        uv_coordinates = self.uv_regression_head(shared_features)
        uv_coordinates = torch.sigmoid(uv_coordinates)  # Chuẩn hóa về [0, 1]

        return {
            'segmentation': segmentation_logits,
            'uv_coordinates': uv_coordinates
        }

    def compute_segmentation_loss(self, pred_logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """Tính tổn thất phân đoạn.

        Args:
            pred_logits: Logit phân đoạn dự đoán
            target: Mặt nạ phân đoạn mục tiêu

        Returns:
            Tổn thất entropy chéo đã tính
        """
        return F.cross_entropy(pred_logits, target, ignore_index=-1)

    def compute_uv_loss(self, pred_uv: torch.Tensor, target_uv: torch.Tensor) -> torch.Tensor:
        """Tính tổn thất hồi quy tọa độ UV.

        Args:
            pred_uv: Tọa độ UV dự đoán
            target_uv: Tọa độ UV mục tiêu

        Returns:
            Tổn thất L1 đã tính
        """
        return F.l1_loss(pred_uv, target_uv)

    def compute_total_loss(self, predictions: Dict[str, torch.Tensor],
                          seg_target: torch.Tensor,
                          uv_target: torch.Tensor,
                          seg_weight: float = 1.0,
                          uv_weight: float = 1.0) -> torch.Tensor:
        """Tính tổng tổn thất kết hợp tổn thất phân đoạn và UV.

        Args:
            predictions: Từ điển các dự đoán
            seg_target: Mặt nạ phân đoạn mục tiêu
            uv_target: Tọa độ UV mục tiêu
            seg_weight: Trọng số cho tổn thất phân đoạn
            uv_weight: Trọng số cho tổn thất UV

        Returns:
            Tổn thất kết hợp
        """
        seg_loss = self.compute_segmentation_loss(predictions['segmentation'], seg_target)
        uv_loss = self.compute_uv_loss(predictions['uv_coordinates'], uv_target)

        return seg_weight * seg_loss + uv_weight * uv_loss

    def get_prediction_confidence(self, predictions: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Lấy điểm tin cậy dự đoán.

        Args:
            predictions: Từ điển các dự đoán

        Returns:
            Từ điển điểm tin cậy
        """
        seg_logits = predictions['segmentation']
        uv_coords = predictions['uv_coordinates']

        # Độ tin cậy phân đoạn: xác suất lớn nhất
        seg_probs = F.softmax(seg_logits, dim=1)
        seg_confidence = torch.max(seg_probs, dim=1)[0]

        # Độ tin cậy UV: nghịch đảo phương sai dự đoán
        uv_variance = torch.var(uv_coords, dim=1, keepdim=True)
        uv_confidence = 1.0 / (1.0 + uv_variance)

        return {
            'segmentation_confidence': seg_confidence,
            'uv_confidence': uv_confidence.squeeze(1)
        }

    def post_process_predictions(self, predictions: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Hậu xử lý dự đoán cho đầu ra cuối cùng.

        Args:
            predictions: Dự đoán thô từ lan truyền tiến

        Returns:
            Dự đoán đã hậu xử lý
        """
        seg_logits = predictions['segmentation']
        uv_coords = predictions['uv_coordinates']

        # Chuyển logit thành dự đoán lớp
        body_parts = torch.argmax(seg_logits, dim=1)

        # Lấy điểm tin cậy
        confidence = self.get_prediction_confidence(predictions)

        return {
            'body_parts': body_parts,
            'uv_coordinates': uv_coords,
            'confidence_scores': confidence
        }
