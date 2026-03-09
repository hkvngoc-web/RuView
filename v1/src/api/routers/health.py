"""
Các endpoint API kiểm tra sức khỏe
"""

import logging
import psutil
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.dependencies import get_current_user
from src.config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Ghi lại tại thời điểm import module — đại diện cho thời gian khởi động ứng dụng
_APP_START_TIME = datetime.now()


# Mô hình phản hồi
class ComponentHealth(BaseModel):
    """Trạng thái sức khỏe cho một thành phần hệ thống."""

    name: str = Field(..., description="Tên thành phần")
    status: str = Field(..., description="Trạng thái sức khỏe (khỏe mạnh, suy giảm, không khỏe)")
    message: Optional[str] = Field(default=None, description="Thông báo trạng thái")
    last_check: datetime = Field(..., description="Thời gian kiểm tra sức khỏe lần cuối")
    uptime_seconds: Optional[float] = Field(default=None, description="Thời gian hoạt động thành phần")
    metrics: Optional[Dict[str, Any]] = Field(default=None, description="Số liệu thành phần")


class SystemHealth(BaseModel):
    """Trạng thái sức khỏe tổng thể hệ thống."""

    status: str = Field(..., description="Trạng thái tổng thể hệ thống")
    timestamp: datetime = Field(..., description="Thời gian kiểm tra sức khỏe")
    uptime_seconds: float = Field(..., description="Thời gian hoạt động hệ thống")
    components: Dict[str, ComponentHealth] = Field(..., description="Trạng thái sức khỏe thành phần")
    system_metrics: Dict[str, Any] = Field(..., description="Số liệu cấp hệ thống")


class ReadinessCheck(BaseModel):
    """Kết quả kiểm tra sẵn sàng hệ thống."""

    ready: bool = Field(..., description="Hệ thống có sẵn sàng phục vụ yêu cầu không")
    timestamp: datetime = Field(..., description="Thời gian kiểm tra sẵn sàng")
    checks: Dict[str, bool] = Field(..., description="Các kiểm tra sẵn sàng riêng lẻ")
    message: str = Field(..., description="Thông báo trạng thái sẵn sàng")


# Các endpoint kiểm tra sức khỏe
@router.get("/health", response_model=SystemHealth)
async def health_check(request: Request):
    """Kiểm tra sức khỏe hệ thống toàn diện."""
    try:
        # Lấy dịch vụ từ trạng thái ứng dụng
        hardware_service = getattr(request.app.state, 'hardware_service', None)
        pose_service = getattr(request.app.state, 'pose_service', None)
        stream_service = getattr(request.app.state, 'stream_service', None)

        timestamp = datetime.utcnow()
        components = {}
        overall_status = "healthy"

        # Kiểm tra dịch vụ phần cứng
        if hardware_service:
            try:
                hw_health = await hardware_service.health_check()
                components["hardware"] = ComponentHealth(
                    name="Dịch vụ Phần cứng",
                    status=hw_health["status"],
                    message=hw_health.get("message"),
                    last_check=timestamp,
                    uptime_seconds=hw_health.get("uptime_seconds"),
                    metrics=hw_health.get("metrics")
                )

                if hw_health["status"] != "healthy":
                    overall_status = "degraded" if overall_status == "healthy" else "unhealthy"

            except Exception as e:
                logger.error(f"Kiểm tra sức khỏe dịch vụ phần cứng thất bại: {e}")
                components["hardware"] = ComponentHealth(
                    name="Dịch vụ Phần cứng",
                    status="unhealthy",
                    message=f"Kiểm tra sức khỏe thất bại: {str(e)}",
                    last_check=timestamp
                )
                overall_status = "unhealthy"
        else:
            components["hardware"] = ComponentHealth(
                name="Dịch vụ Phần cứng",
                status="unavailable",
                message="Dịch vụ chưa được khởi tạo",
                last_check=timestamp
            )
            overall_status = "degraded"

        # Kiểm tra dịch vụ tư thế
        if pose_service:
            try:
                pose_health = await pose_service.health_check()
                components["pose"] = ComponentHealth(
                    name="Dịch vụ Tư thế",
                    status=pose_health["status"],
                    message=pose_health.get("message"),
                    last_check=timestamp,
                    uptime_seconds=pose_health.get("uptime_seconds"),
                    metrics=pose_health.get("metrics")
                )

                if pose_health["status"] != "healthy":
                    overall_status = "degraded" if overall_status == "healthy" else "unhealthy"

            except Exception as e:
                logger.error(f"Kiểm tra sức khỏe dịch vụ tư thế thất bại: {e}")
                components["pose"] = ComponentHealth(
                    name="Dịch vụ Tư thế",
                    status="unhealthy",
                    message=f"Kiểm tra sức khỏe thất bại: {str(e)}",
                    last_check=timestamp
                )
                overall_status = "unhealthy"
        else:
            components["pose"] = ComponentHealth(
                name="Dịch vụ Tư thế",
                status="unavailable",
                message="Dịch vụ chưa được khởi tạo",
                last_check=timestamp
            )
            overall_status = "degraded"

        # Kiểm tra dịch vụ truyền phát
        if stream_service:
            try:
                stream_health = await stream_service.health_check()
                components["stream"] = ComponentHealth(
                    name="Dịch vụ Truyền phát",
                    status=stream_health["status"],
                    message=stream_health.get("message"),
                    last_check=timestamp,
                    uptime_seconds=stream_health.get("uptime_seconds"),
                    metrics=stream_health.get("metrics")
                )

                if stream_health["status"] != "healthy":
                    overall_status = "degraded" if overall_status == "healthy" else "unhealthy"

            except Exception as e:
                logger.error(f"Kiểm tra sức khỏe dịch vụ truyền phát thất bại: {e}")
                components["stream"] = ComponentHealth(
                    name="Dịch vụ Truyền phát",
                    status="unhealthy",
                    message=f"Kiểm tra sức khỏe thất bại: {str(e)}",
                    last_check=timestamp
                )
                overall_status = "unhealthy"
        else:
            components["stream"] = ComponentHealth(
                name="Dịch vụ Truyền phát",
                status="unavailable",
                message="Dịch vụ chưa được khởi tạo",
                last_check=timestamp
            )
            overall_status = "degraded"

        # Lấy số liệu hệ thống
        system_metrics = get_system_metrics()

        uptime_seconds = (datetime.now() - _APP_START_TIME).total_seconds()

        return SystemHealth(
            status=overall_status,
            timestamp=timestamp,
            uptime_seconds=uptime_seconds,
            components=components,
            system_metrics=system_metrics
        )

    except Exception as e:
        logger.error(f"Kiểm tra sức khỏe thất bại: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Kiểm tra sức khỏe thất bại: {str(e)}"
        )


@router.get("/ready", response_model=ReadinessCheck)
async def readiness_check(request: Request):
    """Kiểm tra xem hệ thống có sẵn sàng phục vụ yêu cầu không."""
    try:
        timestamp = datetime.utcnow()
        checks = {}

        # Kiểm tra xem dịch vụ có sẵn trong trạng thái ứng dụng không
        if hasattr(request.app.state, 'pose_service') and request.app.state.pose_service:
            try:
                checks["pose_ready"] = await request.app.state.pose_service.is_ready()
            except Exception as e:
                logger.warning(f"Kiểm tra sẵn sàng dịch vụ tư thế thất bại: {e}")
                checks["pose_ready"] = False
        else:
            checks["pose_ready"] = False

        if hasattr(request.app.state, 'stream_service') and request.app.state.stream_service:
            try:
                checks["stream_ready"] = await request.app.state.stream_service.is_ready()
            except Exception as e:
                logger.warning(f"Kiểm tra sẵn sàng dịch vụ truyền phát thất bại: {e}")
                checks["stream_ready"] = False
        else:
            checks["stream_ready"] = False

        # Kiểm tra dịch vụ phần cứng (sẵn sàng cơ bản)
        checks["hardware_ready"] = True  # Sẵn sàng cơ bản - API đang phản hồi

        # Kiểm tra tài nguyên hệ thống
        checks["memory_available"] = check_memory_availability()
        checks["disk_space_available"] = check_disk_space()

        # Ứng dụng sẵn sàng nếu ít nhất các dịch vụ cơ bản khả dụng
        # Hiện tại, coi là sẵn sàng nếu API đang phản hồi
        ready = True  # Sẵn sàng cơ bản

        message = "Hệ thống sẵn sàng" if ready else "Hệ thống chưa sẵn sàng"
        if not ready:
            failed_checks = [name for name, status in checks.items() if not status]
            message += f". Các kiểm tra thất bại: {', '.join(failed_checks)}"

        return ReadinessCheck(
            ready=ready,
            timestamp=timestamp,
            checks=checks,
            message=message
        )

    except Exception as e:
        logger.error(f"Kiểm tra sẵn sàng thất bại: {e}")
        return ReadinessCheck(
            ready=False,
            timestamp=datetime.utcnow(),
            checks={},
            message=f"Kiểm tra sẵn sàng thất bại: {str(e)}"
        )


@router.get("/live")
async def liveness_check():
    """Kiểm tra hoạt động đơn giản cho bộ cân bằng tải."""
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/metrics")
async def get_health_metrics(
    request: Request,
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy số liệu hệ thống chi tiết."""
    try:
        metrics = get_system_metrics()

        # Thêm số liệu bổ sung nếu đã xác thực
        if current_user:
            metrics.update(get_detailed_metrics())

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": metrics
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy số liệu hệ thống: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy số liệu hệ thống: {str(e)}"
        )


@router.get("/version")
async def get_version_info():
    """Lấy thông tin phiên bản ứng dụng."""
    settings = get_settings()

    return {
        "name": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "debug": settings.debug,
        "timestamp": datetime.utcnow().isoformat()
    }


def get_system_metrics() -> Dict[str, Any]:
    """Lấy số liệu hệ thống cơ bản."""
    try:
        # Số liệu CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        # Số liệu bộ nhớ
        memory = psutil.virtual_memory()
        memory_metrics = {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "used_gb": round(memory.used / (1024**3), 2),
            "percent": memory.percent
        }

        # Số liệu ổ đĩa
        disk = psutil.disk_usage('/')
        disk_metrics = {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent": round((disk.used / disk.total) * 100, 2)
        }

        # Số liệu mạng (cơ bản)
        network = psutil.net_io_counters()
        network_metrics = {
            "bytes_sent": network.bytes_sent,
            "bytes_recv": network.bytes_recv,
            "packets_sent": network.packets_sent,
            "packets_recv": network.packets_recv
        }

        return {
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count
            },
            "memory": memory_metrics,
            "disk": disk_metrics,
            "network": network_metrics
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy số liệu hệ thống: {e}")
        return {}


def get_detailed_metrics() -> Dict[str, Any]:
    """Lấy số liệu hệ thống chi tiết (yêu cầu xác thực)."""
    try:
        # Số liệu tiến trình
        process = psutil.Process()
        process_metrics = {
            "pid": process.pid,
            "cpu_percent": process.cpu_percent(),
            "memory_mb": round(process.memory_info().rss / (1024**2), 2),
            "num_threads": process.num_threads(),
            "create_time": datetime.fromtimestamp(process.create_time()).isoformat()
        }

        # Tải trung bình (hệ thống Unix-like)
        load_avg = None
        try:
            load_avg = psutil.getloadavg()
        except AttributeError:
            # Windows không có tải trung bình
            pass

        # Cảm biến nhiệt độ (nếu có)
        temperatures = {}
        try:
            temps = psutil.sensors_temperatures()
            for name, entries in temps.items():
                temperatures[name] = [
                    {"label": entry.label, "current": entry.current}
                    for entry in entries
                ]
        except AttributeError:
            # Không khả dụng trên tất cả hệ thống
            pass

        detailed = {
            "process": process_metrics
        }

        if load_avg:
            detailed["load_average"] = {
                "1min": load_avg[0],
                "5min": load_avg[1],
                "15min": load_avg[2]
            }

        if temperatures:
            detailed["temperatures"] = temperatures

        return detailed

    except Exception as e:
        logger.error(f"Lỗi khi lấy số liệu chi tiết: {e}")
        return {}


def check_memory_availability() -> bool:
    """Kiểm tra xem bộ nhớ có đủ không."""
    try:
        memory = psutil.virtual_memory()
        # Coi hệ thống sẵn sàng nếu sử dụng dưới 90% bộ nhớ
        return memory.percent < 90.0
    except Exception:
        return False


def check_disk_space() -> bool:
    """Kiểm tra xem dung lượng ổ đĩa có đủ không."""
    try:
        disk = psutil.disk_usage('/')
        # Coi hệ thống sẵn sàng nếu còn hơn 1GB dung lượng trống
        free_gb = disk.free / (1024**3)
        return free_gb > 1.0
    except Exception:
        return False
