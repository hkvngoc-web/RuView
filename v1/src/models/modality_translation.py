"""Mạng dịch chuyển phương thức cho hệ thống WiFi-DensePose."""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Any, List


class ModalityTranslationError(Exception):
    """Ngoại lệ phát sinh khi gặp lỗi dịch chuyển phương thức."""
    pass


class ModalityTranslationNetwork(nn.Module):
    """Mạng nơ-ron để dịch chuyển dữ liệu CSI sang không gian đặc trưng trực quan."""

    def __init__(self, config: Dict[str, Any]):
        """Khởi tạo mạng dịch chuyển phương thức.

        Args:
            config: Từ điển cấu hình với các tham số mạng
        """
        super().__init__()

        self._validate_config(config)
        self.config = config

        self.input_channels = config['input_channels']
        self.hidden_channels = config['hidden_channels']
        self.output_channels = config['output_channels']
        self.kernel_size = config.get('kernel_size', 3)
        self.stride = config.get('stride', 1)
        self.padding = config.get('padding', 1)
        self.dropout_rate = config.get('dropout_rate', 0.1)
        self.activation = config.get('activation', 'relu')
        self.normalization = config.get('normalization', 'batch')
        self.use_attention = config.get('use_attention', False)
        self.attention_heads = config.get('attention_heads', 8)

        # Bộ mã hóa: CSI -> Không gian đặc trưng
        self.encoder = self._build_encoder()

        # Bộ giải mã: Không gian đặc trưng -> Đặc trưng dạng trực quan
        self.decoder = self._build_decoder()

        # Cơ chế chú ý
        if self.use_attention:
            self.attention = self._build_attention()

        # Khởi tạo trọng số
        self._initialize_weights()

    def _validate_config(self, config: Dict[str, Any]):
        """Xác thực tham số cấu hình."""
        required_fields = ['input_channels', 'hidden_channels', 'output_channels']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Thiếu trường bắt buộc: {field}")

        if config['input_channels'] <= 0:
            raise ValueError("input_channels phải là số dương")

        if not config['hidden_channels'] or len(config['hidden_channels']) == 0:
            raise ValueError("hidden_channels phải là danh sách không rỗng")

        if config['output_channels'] <= 0:
            raise ValueError("output_channels phải là số dương")

    def _build_encoder(self) -> nn.ModuleList:
        """Xây dựng mạng bộ mã hóa."""
        layers = nn.ModuleList()

        # Tích chập ban đầu
        in_channels = self.input_channels

        for i, out_channels in enumerate(self.hidden_channels):
            layer_block = nn.Sequential(
                nn.Conv2d(in_channels, out_channels,
                         kernel_size=self.kernel_size,
                         stride=self.stride if i == 0 else 2,
                         padding=self.padding),
                self._get_normalization(out_channels),
                self._get_activation(),
                nn.Dropout2d(self.dropout_rate)
            )
            layers.append(layer_block)
            in_channels = out_channels

        return layers

    def _build_decoder(self) -> nn.ModuleList:
        """Xây dựng mạng bộ giải mã."""
        layers = nn.ModuleList()

        # Bắt đầu với kích thước kênh ẩn cuối cùng
        in_channels = self.hidden_channels[-1]

        # Tăng mẫu tiến bộ (ngược lại bộ mã hóa)
        for i, out_channels in enumerate(reversed(self.hidden_channels[:-1])):
            layer_block = nn.Sequential(
                nn.ConvTranspose2d(in_channels, out_channels,
                                 kernel_size=self.kernel_size,
                                 stride=2,
                                 padding=self.padding,
                                 output_padding=1),
                self._get_normalization(out_channels),
                self._get_activation(),
                nn.Dropout2d(self.dropout_rate)
            )
            layers.append(layer_block)
            in_channels = out_channels

        # Lớp đầu ra cuối cùng
        final_layer = nn.Sequential(
            nn.Conv2d(in_channels, self.output_channels,
                     kernel_size=self.kernel_size,
                     padding=self.padding),
            nn.Tanh()  # Chuẩn hóa đầu ra
        )
        layers.append(final_layer)

        return layers

    def _get_normalization(self, channels: int) -> nn.Module:
        """Lấy lớp chuẩn hóa."""
        if self.normalization == 'batch':
            return nn.BatchNorm2d(channels)
        elif self.normalization == 'instance':
            return nn.InstanceNorm2d(channels)
        elif self.normalization == 'layer':
            return nn.GroupNorm(1, channels)
        else:
            return nn.Identity()

    def _get_activation(self) -> nn.Module:
        """Lấy hàm kích hoạt."""
        if self.activation == 'relu':
            return nn.ReLU(inplace=True)
        elif self.activation == 'leaky_relu':
            return nn.LeakyReLU(0.2, inplace=True)
        elif self.activation == 'gelu':
            return nn.GELU()
        else:
            return nn.ReLU(inplace=True)

    def _build_attention(self) -> nn.Module:
        """Xây dựng cơ chế chú ý."""
        return nn.MultiheadAttention(
            embed_dim=self.hidden_channels[-1],
            num_heads=self.attention_heads,
            dropout=self.dropout_rate,
            batch_first=True
        )

    def _initialize_weights(self):
        """Khởi tạo trọng số mạng."""
        for m in self.modules():
            if isinstance(m, (nn.Conv2d, nn.ConvTranspose2d)):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Lan truyền tiến qua mạng.

        Args:
            x: Tensor CSI đầu vào có hình dạng (batch_size, channels, height, width)

        Returns:
            Tensor đặc trưng đã dịch chuyển
        """
        # Xác thực hình dạng đầu vào
        if x.shape[1] != self.input_channels:
            raise ModalityTranslationError(f"Mong đợi {self.input_channels} kênh đầu vào, nhận được {x.shape[1]}")

        # Mã hóa dữ liệu CSI
        encoded_features = self.encode(x)

        # Giải mã sang đặc trưng dạng trực quan
        decoded = self.decode(encoded_features)

        return decoded

    def encode(self, x: torch.Tensor) -> List[torch.Tensor]:
        """Mã hóa đầu vào qua các lớp bộ mã hóa.

        Args:
            x: Tensor đầu vào

        Returns:
            Danh sách bản đồ đặc trưng từ mỗi lớp bộ mã hóa
        """
        features = []
        current = x

        for layer in self.encoder:
            current = layer(current)
            features.append(current)

        return features

    def decode(self, encoded_features: List[torch.Tensor]) -> torch.Tensor:
        """Giải mã đặc trưng qua các lớp bộ giải mã.

        Args:
            encoded_features: Danh sách bản đồ đặc trưng đã mã hóa

        Returns:
            Tensor đầu ra đã giải mã
        """
        # Bắt đầu với đặc trưng đã mã hóa cuối cùng
        current = encoded_features[-1]

        # Áp dụng chú ý nếu được bật
        if self.use_attention:
            batch_size, channels, height, width = current.shape
            # Thay đổi hình dạng cho chú ý: (batch, seq_len, embed_dim)
            current_flat = current.view(batch_size, channels, -1).transpose(1, 2)
            attended, _ = self.attention(current_flat, current_flat, current_flat)
            current = attended.transpose(1, 2).view(batch_size, channels, height, width)

        # Áp dụng các lớp bộ giải mã
        for layer in self.decoder:
            current = layer(current)

        return current

    def compute_translation_loss(self, predicted: torch.Tensor, target: torch.Tensor, loss_type: str = 'mse') -> torch.Tensor:
        """Tính tổn thất dịch chuyển giữa đặc trưng dự đoán và mục tiêu.

        Args:
            predicted: Tensor đặc trưng dự đoán
            target: Tensor đặc trưng mục tiêu
            loss_type: Loại tổn thất ('mse', 'l1', 'smooth_l1')

        Returns:
            Tensor tổn thất đã tính
        """
        if loss_type == 'mse':
            return F.mse_loss(predicted, target)
        elif loss_type == 'l1':
            return F.l1_loss(predicted, target)
        elif loss_type == 'smooth_l1':
            return F.smooth_l1_loss(predicted, target)
        else:
            return F.mse_loss(predicted, target)

    def get_feature_statistics(self, features: torch.Tensor) -> Dict[str, float]:
        """Lấy thống kê của tensor đặc trưng.

        Args:
            features: Tensor đặc trưng cần phân tích

        Returns:
            Từ điển thống kê đặc trưng
        """
        with torch.no_grad():
            return {
                'mean': features.mean().item(),
                'std': features.std().item(),
                'min': features.min().item(),
                'max': features.max().item(),
                'sparsity': (features == 0).float().mean().item()
            }

    def get_intermediate_features(self, x: torch.Tensor) -> Dict[str, Any]:
        """Lấy đặc trưng trung gian để trực quan hóa.

        Args:
            x: Tensor đầu vào

        Returns:
            Từ điển chứa các đặc trưng trung gian
        """
        result = {}

        # Lấy đặc trưng bộ mã hóa
        encoder_features = self.encode(x)
        result['encoder_features'] = encoder_features

        # Lấy đặc trưng bộ giải mã
        decoder_features = []
        current = encoder_features[-1]

        if self.use_attention:
            batch_size, channels, height, width = current.shape
            current_flat = current.view(batch_size, channels, -1).transpose(1, 2)
            attended, attention_weights = self.attention(current_flat, current_flat, current_flat)
            current = attended.transpose(1, 2).view(batch_size, channels, height, width)
            result['attention_weights'] = attention_weights

        for layer in self.decoder:
            current = layer(current)
            decoder_features.append(current)

        result['decoder_features'] = decoder_features

        return result
