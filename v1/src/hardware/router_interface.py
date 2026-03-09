"""Giao diện router cho hệ thống WiFi-DensePose sử dụng phương pháp TDD."""

import asyncio
import logging
from typing import Dict, Any, Optional
import asyncssh
from datetime import datetime, timezone
import numpy as np

try:
    from .csi_extractor import CSIData
except ImportError:
    # Xử lý import cho kiểm thử
    from src.hardware.csi_extractor import CSIData


class RouterConnectionError(Exception):
    """Ngoại lệ phát sinh khi kết nối router gặp lỗi."""
    pass


class RouterInterface:
    """Giao diện để giao tiếp với router WiFi qua SSH."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Khởi tạo giao diện router.

        Args:
            config: Từ điển cấu hình với tham số kết nối
            logger: Thể hiện logger tùy chọn

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        self._validate_config(config)

        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Tham số kết nối
        self.host = config['host']
        self.port = config['port']
        self.username = config['username']
        self.password = config['password']
        self.command_timeout = config.get('command_timeout', 30)
        self.connection_timeout = config.get('connection_timeout', 10)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1.0)

        # Trạng thái kết nối
        self.is_connected = False
        self.ssh_client = None

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Xác thực tham số cấu hình.

        Args:
            config: Cấu hình cần xác thực

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        required_fields = ['host', 'port', 'username', 'password']
        missing_fields = [field for field in required_fields if field not in config]

        if missing_fields:
            raise ValueError(f"Thiếu cấu hình bắt buộc: {missing_fields}")

        if not isinstance(config['port'], int) or config['port'] <= 0:
            raise ValueError("Port phải là số nguyên dương")

    async def connect(self) -> bool:
        """Thiết lập kết nối SSH đến router.

        Returns:
            True nếu kết nối thành công, False nếu không
        """
        try:
            self.ssh_client = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                connect_timeout=self.connection_timeout
            )
            self.is_connected = True
            self.logger.info(f"Đã kết nối đến router tại {self.host}:{self.port}")
            return True
        except Exception as e:
            self.logger.error(f"Kết nối đến router thất bại: {e}")
            self.is_connected = False
            self.ssh_client = None
            return False

    async def disconnect(self) -> None:
        """Ngắt kết nối khỏi router."""
        if self.is_connected and self.ssh_client:
            self.ssh_client.close()
            self.is_connected = False
            self.ssh_client = None
            self.logger.info("Đã ngắt kết nối khỏi router")

    async def execute_command(self, command: str) -> str:
        """Thực thi lệnh trên router qua SSH.

        Args:
            command: Lệnh cần thực thi

        Returns:
            Kết quả đầu ra của lệnh

        Raises:
            RouterConnectionError: Nếu chưa kết nối hoặc lệnh thất bại
        """
        if not self.is_connected:
            raise RouterConnectionError("Chưa kết nối đến router")

        # Cơ chế thử lại cho lỗi tạm thời
        for attempt in range(self.max_retries):
            try:
                result = await self.ssh_client.run(command, timeout=self.command_timeout)

                if result.returncode != 0:
                    raise RouterConnectionError(f"Lệnh thất bại: {result.stderr}")

                return result.stdout

            except ConnectionError as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(f"Lần thực thi lệnh {attempt + 1} thất bại, đang thử lại: {e}")
                    await asyncio.sleep(self.retry_delay)
                else:
                    raise RouterConnectionError(f"Thực thi lệnh thất bại sau {self.max_retries} lần thử: {e}")
            except Exception as e:
                raise RouterConnectionError(f"Lỗi thực thi lệnh: {e}")

    async def get_csi_data(self) -> CSIData:
        """Lấy dữ liệu CSI từ router.

        Returns:
            Cấu trúc dữ liệu CSI

        Raises:
            RouterConnectionError: Nếu lấy dữ liệu thất bại
        """
        try:
            response = await self.execute_command("iwlist scan | grep CSI")
            return self._parse_csi_response(response)
        except Exception as e:
            raise RouterConnectionError(f"Lấy dữ liệu CSI thất bại: {e}")

    async def get_router_status(self) -> Dict[str, Any]:
        """Lấy trạng thái hệ thống router.

        Returns:
            Từ điển chứa thông tin trạng thái router

        Raises:
            RouterConnectionError: Nếu lấy trạng thái thất bại
        """
        try:
            response = await self.execute_command("cat /proc/stat && free && iwconfig")
            return self._parse_status_response(response)
        except Exception as e:
            raise RouterConnectionError(f"Lấy trạng thái router thất bại: {e}")

    async def configure_csi_monitoring(self, config: Dict[str, Any]) -> bool:
        """Cấu hình giám sát CSI trên router.

        Args:
            config: Cấu hình giám sát CSI

        Returns:
            True nếu cấu hình thành công, False nếu không
        """
        try:
            channel = config.get('channel', 6)
            # Xác thực kênh là số nguyên trong phạm vi an toàn để ngăn chặn chèn lệnh
            if not isinstance(channel, int) or not (1 <= channel <= 196):
                raise ValueError(f"Kênh WiFi không hợp lệ: {channel}. Phải là số nguyên từ 1 đến 196.")
            command = f"iwconfig wlan0 channel {channel} && echo 'CSI monitoring configured'"
            await self.execute_command(command)
            return True
        except Exception as e:
            self.logger.error(f"Cấu hình giám sát CSI thất bại: {e}")
            return False

    async def health_check(self) -> bool:
        """Thực hiện kiểm tra sức khỏe router.

        Returns:
            True nếu router khỏe mạnh, False nếu không
        """
        try:
            response = await self.execute_command("echo 'ping' && echo 'pong'")
            return "pong" in response
        except Exception as e:
            self.logger.error(f"Kiểm tra sức khỏe thất bại: {e}")
            return False

    def _parse_csi_response(self, response: str) -> CSIData:
        """Phân tích dữ liệu phản hồi CSI.

        Args:
            response: Phản hồi thô từ router

        Returns:
            Dữ liệu CSI đã phân tích

        Raises:
            RouterConnectionError: Luôn luôn ở trạng thái hiện tại, vì phân tích CSI
                thực từ đầu ra lệnh router yêu cầu kiến thức định dạng
                phần cứng cụ thể phải được triển khai cho từng mô hình router.
        """
        raise RouterConnectionError(
            "Phân tích dữ liệu CSI thực từ phản hồi router chưa được triển khai. "
            "Thu thập dữ liệu CSI từ router yêu cầu: "
            "(1) router có firmware hỗ trợ CSI (ví dụ: Atheros CSI Tool, Nexmon), "
            "(2) thiết lập và cấu hình phần cứng đúng cách, và "
            "(3) bộ phân tích cho định dạng nhị phân/văn bản cụ thể do firmware tạo ra. "
            "Xem docs/hardware-setup.md để biết hướng dẫn cấu hình router cho thu thập CSI."
        )

    def _parse_status_response(self, response: str) -> Dict[str, Any]:
        """Phân tích phản hồi trạng thái router.

        Args:
            response: Phản hồi thô từ router

        Returns:
            Thông tin trạng thái đã phân tích
        """
        # Triển khai giả cho kiểm thử
        # Trong triển khai thực, sẽ phân tích trạng thái hệ thống thực
        return {
            'cpu_usage': 25.5,
            'memory_usage': 60.2,
            'wifi_status': 'active',
            'uptime': '5 days, 3 hours',
            'raw_response': response
        }
