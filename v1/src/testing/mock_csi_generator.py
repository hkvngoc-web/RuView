"""
Trình tạo dữ liệu CSI giả lập cho kiểm thử và phát triển.

Module này cung cấp khả năng tạo dữ liệu CSI (Thông tin Trạng thái Kênh) tổng hợp
để sử dụng trong môi trường phát triển và kiểm thử CHỈ. Dữ liệu được tạo mô phỏng
các mẫu CSI WiFi thực tế bao gồm hiệu ứng đa đường, chữ ký chuyển động của con người,
và đặc tính nhiễu.

CẢNH BÁO: Module này sử dụng np.random có chủ đích cho việc tạo dữ liệu kiểm thử.
KHÔNG sử dụng module này trong đường dẫn dữ liệu sản xuất.
"""

import logging
import numpy as np
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Biểu ngữ hiển thị khi chế độ giả lập đang hoạt động
MOCK_MODE_BANNER = """
================================================================================
  CẢNH BÁO: CHẾ ĐỘ GIẢ LẬP ĐANG HOẠT ĐỘNG - Sử dụng dữ liệu CSI tổng hợp

  Tất cả dữ liệu CSI được tạo ngẫu nhiên và KHÔNG đại diện cho tín hiệu WiFi thực.
  Để ước lượng tư thế thực, cấu hình phần cứng theo docs/hardware-setup.md.
================================================================================
"""


class MockCSIGenerator:
    """Trình tạo dữ liệu CSI tổng hợp dùng trong kiểm thử và phát triển.

    Lớp này tạo ra ma trận CSI giá trị phức mô phỏng các đặc tính
    kênh WiFi thực tế bao gồm:
    - Biến đổi biên độ/pha theo từng anten và sóng mang con
    - Chữ ký chuyển động con người mô phỏng
    - Mức nhiễu có thể cấu hình
    - Tính nhất quán thời gian giữa các khung hình liên tiếp

    Đây CHỈ dành cho kiểm thử. Mã sản xuất phải sử dụng dữ liệu phần cứng thực.
    """

    def __init__(
        self,
        num_subcarriers: int = 64,
        num_antennas: int = 4,
        num_samples: int = 100,
        noise_level: float = 0.1,
        movement_freq: float = 0.5,
        movement_amplitude: float = 0.3,
    ):
        """Khởi tạo trình tạo CSI giả lập.

        Tham số:
            num_subcarriers: Số sóng mang con OFDM để mô phỏng
            num_antennas: Số phần tử anten
            num_samples: Số mẫu thời gian mỗi khung hình
            noise_level: Độ lệch chuẩn của nhiễu Gauss cộng thêm
            movement_freq: Tần số chuyển động con người mô phỏng (Hz)
            movement_amplitude: Biên độ biến đổi CSI do chuyển động gây ra
        """
        self.num_subcarriers = num_subcarriers
        self.num_antennas = num_antennas
        self.num_samples = num_samples
        self.noise_level = noise_level
        self.movement_freq = movement_freq
        self.movement_amplitude = movement_amplitude

        # Trạng thái nội bộ cho tính nhất quán thời gian
        self._phase = 0.0
        self._frequency = 0.1
        self._amplitude_base = 1.0

        self._banner_shown = False

    def show_banner(self) -> None:
        """Hiển thị biểu ngữ cảnh báo chế độ giả lập (một lần mỗi phiên)."""
        if not self._banner_shown:
            logger.warning(MOCK_MODE_BANNER)
            self._banner_shown = True

    def generate(self) -> np.ndarray:
        """Tạo một khung hình dữ liệu CSI giả lập.

        Trả về:
            Mảng numpy giá trị phức có hình dạng
            (num_antennas, num_subcarriers, num_samples).
        """
        self.show_banner()

        # Tiến pha nội bộ cho tính nhất quán thời gian
        self._phase += self._frequency

        time_axis = np.linspace(0, 1, self.num_samples)

        csi_data = np.zeros(
            (self.num_antennas, self.num_subcarriers, self.num_samples),
            dtype=complex,
        )

        for antenna in range(self.num_antennas):
            for subcarrier in range(self.num_subcarriers):
                # Biên độ cơ bản biến đổi theo anten và sóng mang con
                amplitude = (
                    self._amplitude_base
                    * (1 + 0.2 * np.sin(2 * np.pi * subcarrier / self.num_subcarriers))
                    * (1 + 0.1 * antenna)
                )

                # Pha với biến đổi không gian và tần số
                phase_offset = (
                    self._phase
                    + 2 * np.pi * subcarrier / self.num_subcarriers
                    + np.pi * antenna / self.num_antennas
                )

                # Chuyển động con người mô phỏng
                movement = self.movement_amplitude * np.sin(
                    2 * np.pi * self.movement_freq * time_axis
                )

                signal_amplitude = amplitude * (1 + movement)
                signal_phase = phase_offset + movement * 0.5

                # Nhiễu Gauss phức cộng thêm
                noise = np.random.normal(0, self.noise_level, self.num_samples) + 1j * np.random.normal(
                    0, self.noise_level, self.num_samples
                )

                csi_data[antenna, subcarrier, :] = (
                    signal_amplitude * np.exp(1j * signal_phase) + noise
                )

        return csi_data

    def configure(self, config: Dict[str, Any]) -> None:
        """Cập nhật tham số trình tạo.

        Tham số:
            config: Dictionary với các khóa tùy chọn:
                - sampling_rate: Điều chỉnh tần số nội bộ
                - noise_level: Đặt độ lệch chuẩn nhiễu
                - num_subcarriers: Cập nhật số sóng mang con
                - num_antennas: Cập nhật số anten
                - movement_freq: Cập nhật tần số chuyển động mô phỏng
                - movement_amplitude: Cập nhật biên độ chuyển động
        """
        if "sampling_rate" in config:
            self._frequency = config["sampling_rate"] / 1000.0
        if "noise_level" in config:
            self.noise_level = config["noise_level"]
        if "num_subcarriers" in config:
            self.num_subcarriers = config["num_subcarriers"]
        if "num_antennas" in config:
            self.num_antennas = config["num_antennas"]
        if "movement_freq" in config:
            self.movement_freq = config["movement_freq"]
        if "movement_amplitude" in config:
            self.movement_amplitude = config["movement_amplitude"]

    def get_router_info(self) -> Dict[str, Any]:
        """Trả về thông tin phần cứng router giả lập.

        Trả về:
            Dictionary mô phỏng thông tin phần cứng router cho kiểm thử.
        """
        return {
            "model": "Router Giả lập",
            "firmware": "1.0.0-mock",
            "wifi_standard": "802.11ac",
            "antennas": self.num_antennas,
            "supported_bands": ["2.4GHz", "5GHz"],
            "csi_capabilities": {
                "max_subcarriers": self.num_subcarriers,
                "max_antennas": self.num_antennas,
                "sampling_rate": 1000,
            },
        }
