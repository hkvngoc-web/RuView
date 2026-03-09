"""
Giao diện router cho thu thập dữ liệu WiFi CSI
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)


class RouterInterface:
    """Giao diện kết nối đến router WiFi và thu thập dữ liệu CSI."""

    def __init__(
        self,
        router_id: str,
        host: str,
        port: int = 22,
        username: str = "admin",
        password: str = "",
        interface: str = "wlan0",
        mock_mode: bool = False
    ):
        """Khởi tạo giao diện router.

        Tham số:
            router_id: Mã định danh duy nhất của router
            host: Địa chỉ IP hoặc tên máy chủ của router
            port: Cổng SSH để kết nối
            username: Tên người dùng SSH
            password: Mật khẩu SSH
            interface: Tên giao diện WiFi
            mock_mode: Có sử dụng dữ liệu giả lập thay vì kết nối thực không
        """
        self.router_id = router_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.interface = interface
        self.mock_mode = mock_mode

        self.logger = logging.getLogger(f"{__name__}.{router_id}")

        # Trạng thái kết nối
        self.is_connected = False
        self.connection = None
        self.last_error = None

        # Trạng thái thu thập dữ liệu
        self.last_data_time = None
        self.error_count = 0
        self.sample_count = 0

        # Trình tạo dữ liệu giả lập (ủy quyền cho module testing)
        self._mock_csi_generator = None
        if mock_mode:
            self._initialize_mock_generator()

    def _initialize_mock_generator(self):
        """Khởi tạo trình tạo dữ liệu giả lập từ module testing."""
        from src.testing.mock_csi_generator import MockCSIGenerator
        self._mock_csi_generator = MockCSIGenerator()
        self._mock_csi_generator.show_banner()

    async def connect(self):
        """Kết nối đến router."""
        if self.mock_mode:
            self.is_connected = True
            self.logger.info(f"Kết nối giả lập đã thiết lập đến router {self.router_id}")
            return

        try:
            self.logger.info(f"Đang kết nối đến router {self.router_id} tại {self.host}:{self.port}")

            # Trong triển khai thực tế, đây sẽ thiết lập kết nối SSH
            # Hiện tại, chúng ta mô phỏng kết nối
            await asyncio.sleep(0.1)  # Mô phỏng độ trễ kết nối

            self.is_connected = True
            self.error_count = 0
            self.logger.info(f"Đã kết nối đến router {self.router_id}")

        except Exception as e:
            self.last_error = str(e)
            self.error_count += 1
            self.logger.error(f"Kết nối đến router {self.router_id} thất bại: {e}")
            raise

    async def disconnect(self):
        """Ngắt kết nối khỏi router."""
        try:
            if self.connection:
                # Đóng kết nối SSH
                self.connection = None

            self.is_connected = False
            self.logger.info(f"Đã ngắt kết nối khỏi router {self.router_id}")

        except Exception as e:
            self.logger.error(f"Lỗi khi ngắt kết nối khỏi router {self.router_id}: {e}")

    async def reconnect(self):
        """Kết nối lại đến router."""
        await self.disconnect()
        await asyncio.sleep(1)  # Chờ trước khi kết nối lại
        await self.connect()

    async def get_csi_data(self) -> Optional[np.ndarray]:
        """Lấy dữ liệu CSI từ router.

        Trả về:
            Dữ liệu CSI dưới dạng mảng numpy, hoặc None nếu không có dữ liệu
        """
        if not self.is_connected:
            raise RuntimeError(f"Router {self.router_id} chưa được kết nối")

        try:
            if self.mock_mode:
                csi_data = self._generate_mock_csi_data()
            else:
                csi_data = await self._collect_real_csi_data()

            if csi_data is not None:
                self.last_data_time = datetime.now()
                self.sample_count += 1
                self.error_count = 0

            return csi_data

        except Exception as e:
            self.last_error = str(e)
            self.error_count += 1
            self.logger.error(f"Lỗi khi lấy dữ liệu CSI từ router {self.router_id}: {e}")
            return None

    def _generate_mock_csi_data(self) -> np.ndarray:
        """Tạo dữ liệu CSI giả lập để kiểm thử.

        Ủy quyền cho MockCSIGenerator trong module testing.
        Phương thức này chỉ có thể gọi được khi mock_mode là True.
        """
        if self._mock_csi_generator is None:
            self._initialize_mock_generator()
        return self._mock_csi_generator.generate()

    async def _collect_real_csi_data(self) -> Optional[np.ndarray]:
        """Thu thập dữ liệu CSI thực từ router.

        Ném ra:
            RuntimeError: Luôn luôn trong trạng thái hiện tại, vì việc thu thập
                dữ liệu CSI thực cần thiết lập phần cứng chưa được cấu hình.
                Phương thức này không bao giờ được trả về dữ liệu ngẫu nhiên
                hoặc dữ liệu tạm thời một cách âm thầm.
        """
        raise RuntimeError(
            f"Thu thập dữ liệu CSI thực từ router '{self.router_id}' yêu cầu "
            "thiết lập phần cứng chưa được cấu hình. Bạn phải: "
            "(1) cài đặt firmware hỗ trợ CSI (ví dụ: Atheros CSI Tool, Nexmon CSI) trên router, "
            "(2) cấu hình kết nối SSH đến router, và "
            "(3) triển khai lệnh trích xuất CSI cho firmware cụ thể của bạn. "
            "Để phát triển/kiểm thử, sử dụng mock_mode=True. "
            "Xem docs/hardware-setup.md để biết hướng dẫn thiết lập đầy đủ."
        )

    async def check_health(self) -> bool:
        """Kiểm tra xem kết nối router có khỏe mạnh không.

        Trả về:
            True nếu khỏe mạnh, False nếu không
        """
        if not self.is_connected:
            return False

        try:
            # Trong chế độ giả lập, luôn khỏe mạnh
            if self.mock_mode:
                return True

            # Đối với kết nối thực, chúng ta có thể ping router hoặc kiểm tra kết nối SSH
            # Hiện tại, coi là khỏe mạnh nếu số lỗi thấp
            return self.error_count < 5

        except Exception as e:
            self.logger.error(f"Lỗi kiểm tra sức khỏe của router {self.router_id}: {e}")
            return False

    async def get_status(self) -> Dict[str, Any]:
        """Lấy thông tin trạng thái router.

        Trả về:
            Dictionary chứa trạng thái router
        """
        return {
            "router_id": self.router_id,
            "connected": self.is_connected,
            "mock_mode": self.mock_mode,
            "last_data_time": self.last_data_time.isoformat() if self.last_data_time else None,
            "error_count": self.error_count,
            "sample_count": self.sample_count,
            "last_error": self.last_error,
            "configuration": {
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "interface": self.interface
            }
        }

    async def get_router_info(self) -> Dict[str, Any]:
        """Lấy thông tin phần cứng router.

        Trả về:
            Dictionary chứa thông tin router
        """
        if self.mock_mode:
            if self._mock_csi_generator is None:
                self._initialize_mock_generator()
            return self._mock_csi_generator.get_router_info()

        # Đối với router thực, đây sẽ truy vấn phần cứng thực tế
        return {
            "model": "Không xác định",
            "firmware": "Không xác định",
            "wifi_standard": "Không xác định",
            "antennas": 1,
            "supported_bands": ["Không xác định"],
            "csi_capabilities": {
                "max_subcarriers": 64,
                "max_antennas": 1,
                "sampling_rate": 100
            }
        }

    async def configure_csi_collection(self, config: Dict[str, Any]) -> bool:
        """Cấu hình tham số thu thập dữ liệu CSI.

        Tham số:
            config: Dictionary cấu hình

        Trả về:
            True nếu cấu hình thành công, False nếu không
        """
        try:
            if self.mock_mode:
                if self._mock_csi_generator is None:
                    self._initialize_mock_generator()
                self._mock_csi_generator.configure(config)
                self.logger.info(f"Đã cấu hình thu thập CSI giả lập cho router {self.router_id}")
                return True

            # Đối với router thực, đây sẽ gửi lệnh cấu hình
            self.logger.warning("Chưa triển khai cấu hình CSI thực")
            return False

        except Exception as e:
            self.logger.error(f"Lỗi cấu hình thu thập CSI cho router {self.router_id}: {e}")
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu giao diện router.

        Trả về:
            Dictionary chứa số liệu
        """
        uptime = 0
        if self.last_data_time:
            uptime = (datetime.now() - self.last_data_time).total_seconds()

        success_rate = 0
        if self.sample_count > 0:
            success_rate = (self.sample_count - self.error_count) / self.sample_count

        return {
            "router_id": self.router_id,
            "sample_count": self.sample_count,
            "error_count": self.error_count,
            "success_rate": success_rate,
            "uptime_seconds": uptime,
            "is_connected": self.is_connected,
            "mock_mode": self.mock_mode
        }

    def reset_stats(self):
        """Đặt lại bộ đếm thống kê."""
        self.error_count = 0
        self.sample_count = 0
        self.last_error = None
        self.logger.info(f"Đã đặt lại thống kê cho router {self.router_id}")
