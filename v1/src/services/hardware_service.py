"""
Dịch vụ giao diện phần cứng cho WiFi-DensePose API
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import numpy as np

from src.config.settings import Settings
from src.config.domains import DomainConfig
from src.core.router_interface import RouterInterface

logger = logging.getLogger(__name__)


class HardwareService:
    """Dịch vụ cho các thao tác giao diện phần cứng."""

    def __init__(self, settings: Settings, domain_config: DomainConfig):
        """Khởi tạo dịch vụ phần cứng."""
        self.settings = settings
        self.domain_config = domain_config
        self.logger = logging.getLogger(__name__)

        # Giao diện router
        self.router_interfaces: Dict[str, RouterInterface] = {}

        # Trạng thái dịch vụ
        self.is_running = False
        self.last_error = None

        # Thống kê thu thập dữ liệu
        self.stats = {
            "total_samples": 0,
            "successful_samples": 0,
            "failed_samples": 0,
            "average_sample_rate": 0.0,
            "last_sample_time": None,
            "connected_routers": 0
        }

        # Tác vụ nền
        self.collection_task = None
        self.monitoring_task = None

        # Bộ đệm dữ liệu
        self.recent_samples = []
        self.max_recent_samples = 1000

    async def initialize(self):
        """Khởi tạo dịch vụ phần cứng."""
        await self.start()

    async def start(self):
        """Khởi động dịch vụ phần cứng."""
        if self.is_running:
            return

        try:
            self.logger.info("Đang khởi động dịch vụ phần cứng...")

            # Khởi tạo giao diện router
            await self._initialize_routers()

            self.is_running = True

            # Khởi động tác vụ nền
            if not self.settings.mock_hardware:
                self.collection_task = asyncio.create_task(self._data_collection_loop())

            self.monitoring_task = asyncio.create_task(self._monitoring_loop())

            self.logger.info("Dịch vụ phần cứng đã khởi động thành công")

        except Exception as e:
            self.last_error = str(e)
            self.logger.error(f"Khởi động dịch vụ phần cứng thất bại: {e}")
            raise

    async def stop(self):
        """Dừng dịch vụ phần cứng."""
        self.is_running = False

        # Hủy tác vụ nền
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass

        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        # Ngắt kết nối khỏi router
        await self._disconnect_routers()

        self.logger.info("Dịch vụ phần cứng đã dừng")

    async def _initialize_routers(self):
        """Khởi tạo giao diện router."""
        try:
            # Lấy cấu hình router từ cấu hình miền
            routers = self.domain_config.get_all_routers()

            for router_config in routers:
                if not router_config.enabled:
                    continue

                router_id = router_config.router_id

                # Tạo giao diện router
                router_interface = RouterInterface(
                    router_id=router_id,
                    host=router_config.ip_address,
                    port=getattr(router_config, 'ssh_port', 22),
                    username=getattr(router_config, 'ssh_username', None) or self.settings.router_ssh_username,
                    password=getattr(router_config, 'ssh_password', None) or self.settings.router_ssh_password,
                    interface=router_config.interface,
                    mock_mode=self.settings.mock_hardware
                )

                # Kết nối đến router (luôn kết nối, kể cả chế độ giả)
                await router_interface.connect()

                self.router_interfaces[router_id] = router_interface
                self.logger.info(f"Giao diện router đã khởi tạo: {router_id}")

            self.stats["connected_routers"] = len(self.router_interfaces)

            if not self.router_interfaces:
                self.logger.warning("Không có giao diện router nào được cấu hình")

        except Exception as e:
            self.logger.error(f"Khởi tạo router thất bại: {e}")
            raise

    async def _disconnect_routers(self):
        """Ngắt kết nối khỏi tất cả router."""
        for router_id, interface in self.router_interfaces.items():
            try:
                await interface.disconnect()
                self.logger.info(f"Đã ngắt kết nối khỏi router: {router_id}")
            except Exception as e:
                self.logger.error(f"Lỗi khi ngắt kết nối khỏi router {router_id}: {e}")

        self.router_interfaces.clear()
        self.stats["connected_routers"] = 0

    async def _data_collection_loop(self):
        """Vòng lặp nền cho thu thập dữ liệu."""
        try:
            while self.is_running:
                start_time = time.time()

                # Thu thập dữ liệu từ tất cả router
                await self._collect_data_from_routers()

                # Tính thời gian chờ để duy trì khoảng thời gian lấy mẫu
                elapsed = time.time() - start_time
                sleep_time = max(0, self.settings.hardware_polling_interval - elapsed)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            self.logger.info("Vòng lặp thu thập dữ liệu đã bị hủy")
        except Exception as e:
            self.logger.error(f"Lỗi trong vòng lặp thu thập dữ liệu: {e}")
            self.last_error = str(e)

    async def _monitoring_loop(self):
        """Vòng lặp nền cho giám sát phần cứng."""
        try:
            while self.is_running:
                # Giám sát kết nối router
                await self._monitor_router_health()

                # Cập nhật thống kê
                self._update_sample_rate_stats()

                # Chờ trước lần kiểm tra tiếp theo
                await asyncio.sleep(30)  # Kiểm tra mỗi 30 giây

        except asyncio.CancelledError:
            self.logger.info("Vòng lặp giám sát đã bị hủy")
        except Exception as e:
            self.logger.error(f"Lỗi trong vòng lặp giám sát: {e}")

    async def _collect_data_from_routers(self):
        """Thu thập dữ liệu CSI từ tất cả router đã kết nối."""
        for router_id, interface in self.router_interfaces.items():
            try:
                # Lấy dữ liệu CSI từ router
                csi_data = await interface.get_csi_data()

                if csi_data is not None:
                    # Xử lý dữ liệu đã thu thập
                    await self._process_collected_data(router_id, csi_data)

                    self.stats["successful_samples"] += 1
                    self.stats["last_sample_time"] = datetime.now().isoformat()
                else:
                    self.stats["failed_samples"] += 1

                self.stats["total_samples"] += 1

            except Exception as e:
                self.logger.error(f"Lỗi khi thu thập dữ liệu từ router {router_id}: {e}")
                self.stats["failed_samples"] += 1
                self.stats["total_samples"] += 1

    async def _process_collected_data(self, router_id: str, csi_data: np.ndarray):
        """Xử lý dữ liệu CSI đã thu thập."""
        try:
            # Tạo siêu dữ liệu mẫu
            metadata = {
                "router_id": router_id,
                "timestamp": datetime.now().isoformat(),
                "sample_rate": self.stats["average_sample_rate"],
                "data_shape": csi_data.shape if hasattr(csi_data, 'shape') else None
            }

            # Thêm vào bộ đệm mẫu gần đây
            sample = {
                "router_id": router_id,
                "timestamp": metadata["timestamp"],
                "data": csi_data,
                "metadata": metadata
            }

            self.recent_samples.append(sample)

            # Duy trì kích thước bộ đệm
            if len(self.recent_samples) > self.max_recent_samples:
                self.recent_samples.pop(0)

            # Thông báo các dịch vụ khác (thường sẽ thông qua hệ thống sự kiện)
            # Tạm thời, chỉ ghi log việc thu thập dữ liệu
            self.logger.debug(f"Đã thu thập dữ liệu CSI từ {router_id}: hình dạng {csi_data.shape if hasattr(csi_data, 'shape') else 'không xác định'}")

        except Exception as e:
            self.logger.error(f"Lỗi khi xử lý dữ liệu đã thu thập: {e}")

    async def _monitor_router_health(self):
        """Giám sát sức khỏe kết nối router."""
        healthy_routers = 0

        for router_id, interface in self.router_interfaces.items():
            try:
                is_healthy = await interface.check_health()

                if is_healthy:
                    healthy_routers += 1
                else:
                    self.logger.warning(f"Router {router_id} không khỏe mạnh")

                    # Thử kết nối lại nếu không ở chế độ giả
                    if not self.settings.mock_hardware:
                        try:
                            await interface.reconnect()
                            self.logger.info(f"Đã kết nối lại đến router {router_id}")
                        except Exception as e:
                            self.logger.error(f"Kết nối lại đến router {router_id} thất bại: {e}")

            except Exception as e:
                self.logger.error(f"Lỗi khi kiểm tra sức khỏe router {router_id}: {e}")

        self.stats["connected_routers"] = healthy_routers

    def _update_sample_rate_stats(self):
        """Cập nhật thống kê tốc độ lấy mẫu."""
        if len(self.recent_samples) < 2:
            return

        # Tính tốc độ lấy mẫu từ các mẫu gần đây
        recent_count = min(100, len(self.recent_samples))
        recent_samples = self.recent_samples[-recent_count:]

        if len(recent_samples) >= 2:
            # Tính hiệu thời gian
            time_diffs = []
            for i in range(1, len(recent_samples)):
                try:
                    t1 = datetime.fromisoformat(recent_samples[i-1]["timestamp"])
                    t2 = datetime.fromisoformat(recent_samples[i]["timestamp"])
                    diff = (t2 - t1).total_seconds()
                    if diff > 0:
                        time_diffs.append(diff)
                except Exception:
                    continue

            if time_diffs:
                avg_interval = sum(time_diffs) / len(time_diffs)
                self.stats["average_sample_rate"] = 1.0 / avg_interval if avg_interval > 0 else 0.0

    async def get_router_status(self, router_id: str) -> Dict[str, Any]:
        """Lấy trạng thái của router cụ thể."""
        if router_id not in self.router_interfaces:
            raise ValueError(f"Không tìm thấy router {router_id}")

        interface = self.router_interfaces[router_id]

        try:
            is_healthy = await interface.check_health()
            status = await interface.get_status()

            return {
                "router_id": router_id,
                "healthy": is_healthy,
                "connected": status.get("connected", False),
                "last_data_time": status.get("last_data_time"),
                "error_count": status.get("error_count", 0),
                "configuration": status.get("configuration", {})
            }

        except Exception as e:
            return {
                "router_id": router_id,
                "healthy": False,
                "connected": False,
                "error": str(e)
            }

    async def get_all_router_status(self) -> List[Dict[str, Any]]:
        """Lấy trạng thái của tất cả router."""
        statuses = []

        for router_id in self.router_interfaces:
            try:
                status = await self.get_router_status(router_id)
                statuses.append(status)
            except Exception as e:
                statuses.append({
                    "router_id": router_id,
                    "healthy": False,
                    "error": str(e)
                })

        return statuses

    async def get_recent_data(self, router_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Lấy các mẫu dữ liệu CSI gần đây."""
        samples = self.recent_samples[-limit:] if limit else self.recent_samples

        if router_id:
            samples = [s for s in samples if s["router_id"] == router_id]

        # Chuyển đổi mảng numpy sang danh sách cho tuần tự hóa JSON
        result = []
        for sample in samples:
            sample_copy = sample.copy()
            if isinstance(sample_copy["data"], np.ndarray):
                sample_copy["data"] = sample_copy["data"].tolist()
            result.append(sample_copy)

        return result

    async def get_status(self) -> Dict[str, Any]:
        """Lấy trạng thái dịch vụ."""
        return {
            "status": "healthy" if self.is_running and not self.last_error else "unhealthy",
            "running": self.is_running,
            "last_error": self.last_error,
            "statistics": self.stats.copy(),
            "configuration": {
                "mock_hardware": self.settings.mock_hardware,
                "wifi_interface": self.settings.wifi_interface,
                "polling_interval": self.settings.hardware_polling_interval,
                "buffer_size": self.settings.csi_buffer_size
            },
            "routers": await self.get_all_router_status()
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu dịch vụ."""
        total_samples = self.stats["total_samples"]
        success_rate = self.stats["successful_samples"] / max(1, total_samples)

        return {
            "hardware_service": {
                "total_samples": total_samples,
                "successful_samples": self.stats["successful_samples"],
                "failed_samples": self.stats["failed_samples"],
                "success_rate": success_rate,
                "average_sample_rate": self.stats["average_sample_rate"],
                "connected_routers": self.stats["connected_routers"],
                "last_sample_time": self.stats["last_sample_time"]
            }
        }

    async def reset(self):
        """Đặt lại trạng thái dịch vụ."""
        self.stats = {
            "total_samples": 0,
            "successful_samples": 0,
            "failed_samples": 0,
            "average_sample_rate": 0.0,
            "last_sample_time": None,
            "connected_routers": len(self.router_interfaces)
        }

        self.recent_samples.clear()
        self.last_error = None

        self.logger.info("Dịch vụ phần cứng đã đặt lại")

    async def trigger_manual_collection(self, router_id: Optional[str] = None) -> Dict[str, Any]:
        """Kích hoạt thu thập dữ liệu thủ công."""
        if not self.is_running:
            raise RuntimeError("Dịch vụ phần cứng chưa đang chạy")

        results = {}

        if router_id:
            # Thu thập từ router cụ thể
            if router_id not in self.router_interfaces:
                raise ValueError(f"Không tìm thấy router {router_id}")

            interface = self.router_interfaces[router_id]
            try:
                csi_data = await interface.get_csi_data()
                if csi_data is not None:
                    await self._process_collected_data(router_id, csi_data)
                    results[router_id] = {"success": True, "data_shape": csi_data.shape if hasattr(csi_data, 'shape') else None}
                else:
                    results[router_id] = {"success": False, "error": "Không nhận được dữ liệu"}
            except Exception as e:
                results[router_id] = {"success": False, "error": str(e)}
        else:
            # Thu thập từ tất cả router
            await self._collect_data_from_routers()
            results = {"message": "Đã kích hoạt thu thập thủ công cho tất cả router"}

        return results

    async def health_check(self) -> Dict[str, Any]:
        """Thực hiện kiểm tra sức khỏe."""
        try:
            status = "healthy" if self.is_running and not self.last_error else "unhealthy"

            # Kiểm tra sức khỏe router
            healthy_routers = 0
            total_routers = len(self.router_interfaces)

            for router_id, interface in self.router_interfaces.items():
                try:
                    if await interface.check_health():
                        healthy_routers += 1
                except Exception:
                    pass

            return {
                "status": status,
                "message": self.last_error if self.last_error else "Dịch vụ phần cứng đang chạy bình thường",
                "connected_routers": f"{healthy_routers}/{total_routers}",
                "metrics": {
                    "total_samples": self.stats["total_samples"],
                    "success_rate": (
                        self.stats["successful_samples"] / max(1, self.stats["total_samples"])
                    ),
                    "average_sample_rate": self.stats["average_sample_rate"]
                }
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Kiểm tra sức khỏe thất bại: {str(e)}"
            }

    async def is_ready(self) -> bool:
        """Kiểm tra xem dịch vụ có sẵn sàng không."""
        return self.is_running and len(self.router_interfaces) > 0
