"""
Dịch vụ kiểm tra sức khỏe cho WiFi-DensePose API
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Liệt kê trạng thái sức khỏe."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Kết quả kiểm tra sức khỏe."""
    name: str
    status: HealthStatus
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceHealth:
    """Thông tin sức khỏe dịch vụ."""
    name: str
    status: HealthStatus
    last_check: Optional[datetime] = None
    checks: List[HealthCheck] = field(default_factory=list)
    uptime: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None


class HealthCheckService:
    """Dịch vụ giám sát sức khỏe ứng dụng."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._services: Dict[str, ServiceHealth] = {}
        self._start_time = time.time()
        self._initialized = False
        self._running = False

    async def initialize(self):
        """Khởi tạo dịch vụ kiểm tra sức khỏe."""
        if self._initialized:
            return

        logger.info("Đang khởi tạo dịch vụ kiểm tra sức khỏe")

        # Khởi tạo theo dõi sức khỏe dịch vụ
        self._services = {
            "api": ServiceHealth("api", HealthStatus.UNKNOWN),
            "database": ServiceHealth("database", HealthStatus.UNKNOWN),
            "redis": ServiceHealth("redis", HealthStatus.UNKNOWN),
            "hardware": ServiceHealth("hardware", HealthStatus.UNKNOWN),
            "pose": ServiceHealth("pose", HealthStatus.UNKNOWN),
            "stream": ServiceHealth("stream", HealthStatus.UNKNOWN),
        }

        self._initialized = True
        logger.info("Dịch vụ kiểm tra sức khỏe đã khởi tạo")

    async def start(self):
        """Khởi động dịch vụ kiểm tra sức khỏe."""
        if not self._initialized:
            await self.initialize()

        self._running = True
        logger.info("Dịch vụ kiểm tra sức khỏe đã khởi động")

    async def shutdown(self):
        """Tắt dịch vụ kiểm tra sức khỏe."""
        self._running = False
        logger.info("Dịch vụ kiểm tra sức khỏe đã tắt")

    async def perform_health_checks(self) -> Dict[str, HealthCheck]:
        """Thực hiện tất cả kiểm tra sức khỏe."""
        if not self._running:
            return {}

        logger.debug("Đang thực hiện kiểm tra sức khỏe")
        results = {}

        # Thực hiện các kiểm tra sức khỏe riêng lẻ
        checks = [
            self._check_api_health(),
            self._check_database_health(),
            self._check_redis_health(),
            self._check_hardware_health(),
            self._check_pose_health(),
            self._check_stream_health(),
        ]

        # Chạy các kiểm tra đồng thời
        check_results = await asyncio.gather(*checks, return_exceptions=True)

        # Xử lý kết quả
        for i, result in enumerate(check_results):
            check_name = ["api", "database", "redis", "hardware", "pose", "stream"][i]

            if isinstance(result, Exception):
                health_check = HealthCheck(
                    name=check_name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Kiểm tra sức khỏe thất bại: {result}"
                )
            else:
                health_check = result

            results[check_name] = health_check
            self._update_service_health(check_name, health_check)

        logger.debug(f"Đã hoàn thành {len(results)} kiểm tra sức khỏe")
        return results

    async def _check_api_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe API."""
        start_time = time.time()

        try:
            # Kiểm tra sức khỏe API cơ bản
            uptime = time.time() - self._start_time

            status = HealthStatus.HEALTHY
            message = "API đang chạy bình thường"
            details = {
                "uptime_seconds": uptime,
                "uptime_formatted": str(timedelta(seconds=int(uptime)))
            }

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe API thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="api",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    async def _check_database_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe cơ sở dữ liệu."""
        start_time = time.time()

        try:
            # Import tại đây để tránh import vòng
            from src.database.connection import get_database_manager

            db_manager = get_database_manager()

            if not db_manager.is_connected():
                status = HealthStatus.UNHEALTHY
                message = "Cơ sở dữ liệu chưa kết nối"
                details = {"connected": False}
            else:
                # Kiểm tra kết nối cơ sở dữ liệu
                await db_manager.test_connection()

                status = HealthStatus.HEALTHY
                message = "Cơ sở dữ liệu đã kết nối và phản hồi"
                details = {
                    "connected": True,
                    "pool_size": db_manager.get_pool_size(),
                    "active_connections": db_manager.get_active_connections()
                }

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe cơ sở dữ liệu thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="database",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    async def _check_redis_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe Redis."""
        start_time = time.time()

        try:
            redis_config = self.settings.get_redis_url()

            if not redis_config:
                status = HealthStatus.UNKNOWN
                message = "Redis chưa được cấu hình"
                details = {"configured": False}
            else:
                # Kiểm tra kết nối Redis
                import redis.asyncio as redis

                redis_client = redis.from_url(redis_config)
                await redis_client.ping()
                await redis_client.close()

                status = HealthStatus.HEALTHY
                message = "Redis đã kết nối và phản hồi"
                details = {"connected": True}

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe Redis thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="redis",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    async def _check_hardware_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe dịch vụ phần cứng."""
        start_time = time.time()

        try:
            # Import tại đây để tránh import vòng
            from src.api.dependencies import get_hardware_service

            hardware_service = get_hardware_service()

            if hasattr(hardware_service, 'get_status'):
                status_info = await hardware_service.get_status()

                if status_info.get("status") == "healthy":
                    status = HealthStatus.HEALTHY
                    message = "Dịch vụ phần cứng đang hoạt động"
                else:
                    status = HealthStatus.DEGRADED
                    message = f"Trạng thái dịch vụ phần cứng: {status_info.get('status', 'không xác định')}"

                details = status_info
            else:
                status = HealthStatus.UNKNOWN
                message = "Không có thông tin trạng thái dịch vụ phần cứng"
                details = {}

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe phần cứng thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="hardware",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    async def _check_pose_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe dịch vụ tư thế."""
        start_time = time.time()

        try:
            # Import tại đây để tránh import vòng
            from src.api.dependencies import get_pose_service

            pose_service = get_pose_service()

            if hasattr(pose_service, 'get_status'):
                status_info = await pose_service.get_status()

                if status_info.get("status") == "healthy":
                    status = HealthStatus.HEALTHY
                    message = "Dịch vụ tư thế đang hoạt động"
                else:
                    status = HealthStatus.DEGRADED
                    message = f"Trạng thái dịch vụ tư thế: {status_info.get('status', 'không xác định')}"

                details = status_info
            else:
                status = HealthStatus.UNKNOWN
                message = "Không có thông tin trạng thái dịch vụ tư thế"
                details = {}

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe tư thế thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="pose",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    async def _check_stream_health(self) -> HealthCheck:
        """Kiểm tra sức khỏe dịch vụ truyền phát."""
        start_time = time.time()

        try:
            # Import tại đây để tránh import vòng
            from src.api.dependencies import get_stream_service

            stream_service = get_stream_service()

            if hasattr(stream_service, 'get_status'):
                status_info = await stream_service.get_status()

                if status_info.get("status") == "healthy":
                    status = HealthStatus.HEALTHY
                    message = "Dịch vụ truyền phát đang hoạt động"
                else:
                    status = HealthStatus.DEGRADED
                    message = f"Trạng thái dịch vụ truyền phát: {status_info.get('status', 'không xác định')}"

                details = status_info
            else:
                status = HealthStatus.UNKNOWN
                message = "Không có thông tin trạng thái dịch vụ truyền phát"
                details = {}

        except Exception as e:
            status = HealthStatus.UNHEALTHY
            message = f"Kiểm tra sức khỏe truyền phát thất bại: {e}"
            details = {"error": str(e)}

        duration_ms = (time.time() - start_time) * 1000

        return HealthCheck(
            name="stream",
            status=status,
            message=message,
            duration_ms=duration_ms,
            details=details
        )

    def _update_service_health(self, service_name: str, health_check: HealthCheck):
        """Cập nhật thông tin sức khỏe dịch vụ."""
        if service_name not in self._services:
            self._services[service_name] = ServiceHealth(service_name, HealthStatus.UNKNOWN)

        service_health = self._services[service_name]
        service_health.status = health_check.status
        service_health.last_check = health_check.timestamp
        service_health.uptime = time.time() - self._start_time

        # Giữ lại 10 lần kiểm tra gần nhất
        service_health.checks.append(health_check)
        if len(service_health.checks) > 10:
            service_health.checks.pop(0)

        # Cập nhật theo dõi lỗi
        if health_check.status == HealthStatus.UNHEALTHY:
            service_health.error_count += 1
            service_health.last_error = health_check.message

    async def get_overall_health(self) -> Dict[str, Any]:
        """Lấy sức khỏe tổng thể hệ thống."""
        if not self._services:
            return {
                "status": HealthStatus.UNKNOWN.value,
                "message": "Kiểm tra sức khỏe chưa được khởi tạo"
            }

        # Xác định trạng thái tổng thể
        statuses = [service.status for service in self._services.values()]

        if all(status == HealthStatus.HEALTHY for status in statuses):
            overall_status = HealthStatus.HEALTHY
            message = "Tất cả dịch vụ đều khỏe mạnh"
        elif any(status == HealthStatus.UNHEALTHY for status in statuses):
            overall_status = HealthStatus.UNHEALTHY
            unhealthy_services = [
                name for name, service in self._services.items()
                if service.status == HealthStatus.UNHEALTHY
            ]
            message = f"Dịch vụ không khỏe mạnh: {', '.join(unhealthy_services)}"
        elif any(status == HealthStatus.DEGRADED for status in statuses):
            overall_status = HealthStatus.DEGRADED
            degraded_services = [
                name for name, service in self._services.items()
                if service.status == HealthStatus.DEGRADED
            ]
            message = f"Dịch vụ suy giảm: {', '.join(degraded_services)}"
        else:
            overall_status = HealthStatus.UNKNOWN
            message = "Trạng thái sức khỏe hệ thống không xác định"

        return {
            "status": overall_status.value,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": time.time() - self._start_time,
            "services": {
                name: {
                    "status": service.status.value,
                    "last_check": service.last_check.isoformat() if service.last_check else None,
                    "error_count": service.error_count,
                    "last_error": service.last_error
                }
                for name, service in self._services.items()
            }
        }

    async def get_service_health(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin sức khỏe cho dịch vụ cụ thể."""
        service = self._services.get(service_name)
        if not service:
            return None

        return {
            "name": service.name,
            "status": service.status.value,
            "last_check": service.last_check.isoformat() if service.last_check else None,
            "uptime": service.uptime,
            "error_count": service.error_count,
            "last_error": service.last_error,
            "recent_checks": [
                {
                    "timestamp": check.timestamp.isoformat(),
                    "status": check.status.value,
                    "message": check.message,
                    "duration_ms": check.duration_ms,
                    "details": check.details
                }
                for check in service.checks[-5:]  # 5 lần kiểm tra gần nhất
            ]
        }

    async def get_status(self) -> Dict[str, Any]:
        """Lấy trạng thái dịch vụ kiểm tra sức khỏe."""
        return {
            "status": "healthy" if self._running else "stopped",
            "initialized": self._initialized,
            "running": self._running,
            "services_monitored": len(self._services),
            "uptime": time.time() - self._start_time
        }
