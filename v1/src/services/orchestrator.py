"""
Bộ điều phối dịch vụ chính cho WiFi-DensePose API
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from src.config.settings import Settings
from src.services.health_check import HealthCheckService
from src.services.metrics import MetricsService
from src.api.dependencies import (
    get_hardware_service,
    get_pose_service,
    get_stream_service
)
from src.api.websocket.connection_manager import connection_manager
from src.api.websocket.pose_stream import PoseStreamHandler

logger = logging.getLogger(__name__)


class ServiceOrchestrator:
    """Bộ điều phối dịch vụ chính quản lý tất cả các dịch vụ ứng dụng."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._services: Dict[str, Any] = {}
        self._background_tasks: List[asyncio.Task] = []
        self._initialized = False
        self._started = False

        # Dịch vụ cốt lõi
        self.health_service = HealthCheckService(settings)
        self.metrics_service = MetricsService(settings)

        # Dịch vụ ứng dụng (sẽ được khởi tạo sau)
        self.hardware_service = None
        self.pose_service = None
        self.stream_service = None
        self.pose_stream_handler = None

    async def initialize(self):
        """Khởi tạo tất cả các dịch vụ."""
        if self._initialized:
            logger.warning("Các dịch vụ đã được khởi tạo rồi")
            return

        logger.info("Đang khởi tạo các dịch vụ...")

        try:
            # Khởi tạo dịch vụ cốt lõi
            await self.health_service.initialize()
            await self.metrics_service.initialize()

            # Khởi tạo dịch vụ ứng dụng
            await self._initialize_application_services()

            # Lưu trữ dịch vụ trong registry
            self._services = {
                'health': self.health_service,
                'metrics': self.metrics_service,
                'hardware': self.hardware_service,
                'pose': self.pose_service,
                'stream': self.stream_service,
                'pose_stream_handler': self.pose_stream_handler,
                'connection_manager': connection_manager
            }

            self._initialized = True
            logger.info("Tất cả dịch vụ đã được khởi tạo thành công")

        except Exception as e:
            logger.error(f"Không thể khởi tạo dịch vụ: {e}")
            await self.shutdown()
            raise

    async def _initialize_application_services(self):
        """Khởi tạo các dịch vụ ứng dụng cụ thể."""
        try:
            # Khởi tạo dịch vụ phần cứng
            self.hardware_service = get_hardware_service()
            await self.hardware_service.initialize()
            logger.info("Dịch vụ phần cứng đã khởi tạo")

            # Khởi tạo dịch vụ tư thế
            self.pose_service = get_pose_service()
            await self.pose_service.initialize()
            logger.info("Dịch vụ tư thế đã khởi tạo")

            # Khởi tạo dịch vụ truyền phát
            self.stream_service = get_stream_service()
            await self.stream_service.initialize()
            logger.info("Dịch vụ truyền phát đã khởi tạo")

            # Khởi tạo trình xử lý luồng tư thế
            self.pose_stream_handler = PoseStreamHandler(
                connection_manager=connection_manager,
                pose_service=self.pose_service,
                stream_service=self.stream_service
            )
            logger.info("Trình xử lý luồng tư thế đã khởi tạo")

        except Exception as e:
            logger.error(f"Không thể khởi tạo dịch vụ ứng dụng: {e}")
            raise

    async def start(self):
        """Khởi động tất cả dịch vụ và tác vụ nền."""
        if not self._initialized:
            await self.initialize()

        if self._started:
            logger.warning("Các dịch vụ đã được khởi động rồi")
            return

        logger.info("Đang khởi động các dịch vụ...")

        try:
            # Khởi động dịch vụ cốt lõi
            await self.health_service.start()
            await self.metrics_service.start()

            # Khởi động dịch vụ ứng dụng
            await self._start_application_services()

            # Khởi động tác vụ nền
            await self._start_background_tasks()

            self._started = True
            logger.info("Tất cả dịch vụ đã khởi động thành công")

        except Exception as e:
            logger.error(f"Không thể khởi động dịch vụ: {e}")
            await self.shutdown()
            raise

    async def _start_application_services(self):
        """Khởi động các dịch vụ ứng dụng cụ thể."""
        try:
            # Khởi động dịch vụ phần cứng
            if hasattr(self.hardware_service, 'start'):
                await self.hardware_service.start()

            # Khởi động dịch vụ tư thế
            if hasattr(self.pose_service, 'start'):
                await self.pose_service.start()

            # Khởi động dịch vụ truyền phát
            if hasattr(self.stream_service, 'start'):
                await self.stream_service.start()

            logger.info("Dịch vụ ứng dụng đã khởi động")

        except Exception as e:
            logger.error(f"Không thể khởi động dịch vụ ứng dụng: {e}")
            raise

    async def _start_background_tasks(self):
        """Khởi động các tác vụ nền."""
        try:
            # Khởi động giám sát kiểm tra sức khỏe
            if self.settings.health_check_interval > 0:
                task = asyncio.create_task(self._health_check_loop())
                self._background_tasks.append(task)

            # Khởi động thu thập số liệu
            if self.settings.metrics_enabled:
                task = asyncio.create_task(self._metrics_collection_loop())
                self._background_tasks.append(task)

            # Khởi động truyền phát tư thế nếu được bật
            if self.settings.enable_real_time_processing:
                await self.pose_stream_handler.start_streaming()

            logger.info(f"Đã khởi động {len(self._background_tasks)} tác vụ nền")

        except Exception as e:
            logger.error(f"Không thể khởi động tác vụ nền: {e}")
            raise

    async def _health_check_loop(self):
        """Vòng lặp kiểm tra sức khỏe nền."""
        logger.info("Đang bắt đầu vòng lặp kiểm tra sức khỏe")

        while True:
            try:
                await self.health_service.perform_health_checks()
                await asyncio.sleep(self.settings.health_check_interval)
            except asyncio.CancelledError:
                logger.info("Vòng lặp kiểm tra sức khỏe đã bị hủy")
                break
            except Exception as e:
                logger.error(f"Lỗi trong vòng lặp kiểm tra sức khỏe: {e}")
                await asyncio.sleep(self.settings.health_check_interval)

    async def _metrics_collection_loop(self):
        """Vòng lặp thu thập số liệu nền."""
        logger.info("Đang bắt đầu vòng lặp thu thập số liệu")

        while True:
            try:
                await self.metrics_service.collect_metrics()
                await asyncio.sleep(60)  # Thu thập số liệu mỗi phút
            except asyncio.CancelledError:
                logger.info("Vòng lặp thu thập số liệu đã bị hủy")
                break
            except Exception as e:
                logger.error(f"Lỗi trong vòng lặp thu thập số liệu: {e}")
                await asyncio.sleep(60)

    async def shutdown(self):
        """Tắt tất cả dịch vụ và dọn dẹp tài nguyên."""
        logger.info("Đang tắt các dịch vụ...")

        try:
            # Hủy tác vụ nền
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()

            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
                self._background_tasks.clear()

            # Dừng truyền phát tư thế
            if self.pose_stream_handler:
                await self.pose_stream_handler.shutdown()

            # Tắt trình quản lý kết nối
            await connection_manager.shutdown()

            # Tắt dịch vụ ứng dụng
            await self._shutdown_application_services()

            # Tắt dịch vụ cốt lõi
            await self.health_service.shutdown()
            await self.metrics_service.shutdown()

            self._started = False
            self._initialized = False

            logger.info("Tất cả dịch vụ đã tắt thành công")

        except Exception as e:
            logger.error(f"Lỗi trong quá trình tắt: {e}")

    async def _shutdown_application_services(self):
        """Tắt các dịch vụ ứng dụng cụ thể."""
        try:
            # Tắt dịch vụ theo thứ tự ngược
            if self.stream_service and hasattr(self.stream_service, 'shutdown'):
                await self.stream_service.shutdown()

            if self.pose_service and hasattr(self.pose_service, 'shutdown'):
                await self.pose_service.shutdown()

            if self.hardware_service and hasattr(self.hardware_service, 'shutdown'):
                await self.hardware_service.shutdown()

            logger.info("Dịch vụ ứng dụng đã tắt")

        except Exception as e:
            logger.error(f"Lỗi khi tắt dịch vụ ứng dụng: {e}")

    async def restart_service(self, service_name: str):
        """Khởi động lại một dịch vụ cụ thể."""
        logger.info(f"Đang khởi động lại dịch vụ: {service_name}")

        service = self._services.get(service_name)
        if not service:
            raise ValueError(f"Không tìm thấy dịch vụ: {service_name}")

        try:
            # Dừng dịch vụ
            if hasattr(service, 'stop'):
                await service.stop()
            elif hasattr(service, 'shutdown'):
                await service.shutdown()

            # Khởi tạo lại dịch vụ
            if hasattr(service, 'initialize'):
                await service.initialize()

            # Khởi động dịch vụ
            if hasattr(service, 'start'):
                await service.start()

            logger.info(f"Dịch vụ đã khởi động lại thành công: {service_name}")

        except Exception as e:
            logger.error(f"Không thể khởi động lại dịch vụ {service_name}: {e}")
            raise

    async def reset_services(self):
        """Đặt lại tất cả dịch vụ về trạng thái ban đầu."""
        logger.info("Đang đặt lại tất cả dịch vụ")

        try:
            # Đặt lại dịch vụ ứng dụng
            if self.hardware_service and hasattr(self.hardware_service, 'reset'):
                await self.hardware_service.reset()

            if self.pose_service and hasattr(self.pose_service, 'reset'):
                await self.pose_service.reset()

            if self.stream_service and hasattr(self.stream_service, 'reset'):
                await self.stream_service.reset()

            # Đặt lại trình quản lý kết nối
            await connection_manager.reset()

            logger.info("Tất cả dịch vụ đã đặt lại thành công")

        except Exception as e:
            logger.error(f"Không thể đặt lại dịch vụ: {e}")
            raise

    async def get_service_status(self) -> Dict[str, Any]:
        """Lấy trạng thái của tất cả dịch vụ."""
        status = {}

        for name, service in self._services.items():
            try:
                if hasattr(service, 'get_status'):
                    status[name] = await service.get_status()
                else:
                    status[name] = {"status": "không xác định"}
            except Exception as e:
                status[name] = {"status": "lỗi", "error": str(e)}

        return status

    async def get_service_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu từ tất cả dịch vụ."""
        metrics = {}

        for name, service in self._services.items():
            try:
                if hasattr(service, 'get_metrics'):
                    metrics[name] = await service.get_metrics()
                elif hasattr(service, 'get_performance_metrics'):
                    metrics[name] = await service.get_performance_metrics()
            except Exception as e:
                logger.error(f"Không thể lấy số liệu từ {name}: {e}")
                metrics[name] = {"error": str(e)}

        return metrics

    async def get_service_info(self) -> Dict[str, Any]:
        """Lấy thông tin về tất cả dịch vụ."""
        info = {
            "total_services": len(self._services),
            "initialized": self._initialized,
            "started": self._started,
            "background_tasks": len(self._background_tasks),
            "services": {}
        }

        for name, service in self._services.items():
            service_info = {
                "type": type(service).__name__,
                "module": type(service).__module__
            }

            # Thêm thông tin dịch vụ cụ thể nếu có
            if hasattr(service, 'get_info'):
                try:
                    service_info.update(await service.get_info())
                except Exception as e:
                    service_info["error"] = str(e)

            info["services"][name] = service_info

        return info

    def get_service(self, name: str) -> Optional[Any]:
        """Lấy một dịch vụ cụ thể theo tên."""
        return self._services.get(name)

    @property
    def is_healthy(self) -> bool:
        """Kiểm tra xem tất cả dịch vụ có khỏe mạnh không."""
        return self._initialized and self._started

    @asynccontextmanager
    async def service_context(self):
        """Trình quản lý ngữ cảnh cho vòng đời dịch vụ."""
        try:
            await self.initialize()
            await self.start()
            yield self
        finally:
            await self.shutdown()
