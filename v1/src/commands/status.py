"""
Triển khai lệnh trạng thái cho WiFi-DensePose API
"""

import asyncio
import json
import psutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from src.config.settings import Settings
from src.logger import get_logger

logger = get_logger(__name__)


async def status_command(
    settings: Settings,
    output_format: str = "text",
    detailed: bool = False
) -> None:
    """Hiển thị trạng thái máy chủ WiFi-DensePose API."""

    logger.debug("Đang thu thập thông tin trạng thái máy chủ...")

    try:
        # Thu thập thông tin trạng thái
        status_data = await _collect_status_data(settings, detailed)

        # Xuất trạng thái
        if output_format == "json":
            print(json.dumps(status_data, indent=2, default=str))
        else:
            _print_text_status(status_data, detailed)

    except Exception as e:
        logger.error(f"Không thể lấy trạng thái: {e}")
        raise


async def _collect_status_data(settings: Settings, detailed: bool) -> Dict[str, Any]:
    """Thu thập dữ liệu trạng thái toàn diện."""

    status_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "server": await _get_server_status(settings),
        "system": _get_system_status(),
        "configuration": _get_configuration_status(settings),
    }

    if detailed:
        status_data.update({
            "database": await _get_database_status(settings),
            "background_tasks": await _get_background_tasks_status(settings),
            "resources": _get_resource_usage(),
            "health": await _get_health_status(settings),
        })

    return status_data


async def _get_server_status(settings: Settings) -> Dict[str, Any]:
    """Lấy trạng thái tiến trình máy chủ."""

    from src.commands.stop import get_server_status

    status = get_server_status(settings)

    server_info = {
        "running": status["running"],
        "pid": status["pid"],
        "pid_file": status["pid_file"],
        "pid_file_exists": status["pid_file_exists"],
    }

    if status["running"] and status["pid"]:
        try:
            # Lấy thông tin tiến trình
            process = psutil.Process(status["pid"])

            server_info.update({
                "start_time": datetime.fromtimestamp(process.create_time()).isoformat(),
                "uptime_seconds": time.time() - process.create_time(),
                "memory_usage_mb": process.memory_info().rss / (1024 * 1024),
                "cpu_percent": process.cpu_percent(),
                "status": process.status(),
                "num_threads": process.num_threads(),
                "connections": len(process.connections()) if hasattr(process, 'connections') else None,
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            server_info["error"] = f"Không thể truy cập thông tin tiến trình: {e}"

    return server_info


def _get_system_status() -> Dict[str, Any]:
    """Lấy thông tin trạng thái hệ thống."""

    uname_info = psutil.os.uname()
    return {
        "hostname": uname_info.nodename,
        "platform": uname_info.sysname,
        "architecture": uname_info.machine,
        "python_version": f"{psutil.sys.version_info.major}.{psutil.sys.version_info.minor}.{psutil.sys.version_info.micro}",
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "uptime_seconds": time.time() - psutil.boot_time(),
    }


def _get_configuration_status(settings: Settings) -> Dict[str, Any]:
    """Lấy trạng thái cấu hình."""

    return {
        "environment": settings.environment,
        "debug": settings.debug,
        "version": settings.version,
        "host": settings.host,
        "port": settings.port,
        "database_configured": bool(settings.database_url or (settings.db_host and settings.db_name)),
        "redis_enabled": settings.redis_enabled,
        "monitoring_enabled": settings.monitoring_interval_seconds > 0,
        "cleanup_enabled": settings.cleanup_interval_seconds > 0,
        "backup_enabled": settings.backup_interval_seconds > 0,
    }


async def _get_database_status(settings: Settings) -> Dict[str, Any]:
    """Lấy trạng thái cơ sở dữ liệu."""

    db_status = {
        "connected": False,
        "connection_pool": None,
        "tables": {},
        "error": None,
    }

    try:
        from src.database.connection import get_database_manager

        db_manager = get_database_manager(settings)

        # Kiểm tra kết nối
        await db_manager.test_connection()
        db_status["connected"] = True

        # Lấy thống kê kết nối
        connection_stats = await db_manager.get_connection_stats()
        db_status["connection_pool"] = connection_stats

        # Lấy số lượng bảng
        async with db_manager.get_async_session() as session:
            import sqlalchemy as sa
            from sqlalchemy import text, func, select
            from src.database.models import Device, Session, CSIData, PoseDetection, SystemMetric, AuditLog

            tables = {
                "devices": Device,
                "sessions": Session,
                "csi_data": CSIData,
                "pose_detections": PoseDetection,
                "system_metrics": SystemMetric,
                "audit_logs": AuditLog,
            }

            # Danh sách trắng tên bảng được phép để ngăn SQL injection
            allowed_table_names = set(tables.keys())

            for table_name, model in tables.items():
                try:
                    # Xác thực table_name theo danh sách trắng để ngăn SQL injection
                    if table_name not in allowed_table_names:
                        db_status["tables"][table_name] = {"error": "Tên bảng không hợp lệ"}
                        continue

                    # Sử dụng mô hình ORM SQLAlchemy cho truy vấn an toàn thay vì SQL thô
                    result = await session.execute(
                        select(func.count()).select_from(model)
                    )
                    count = result.scalar()
                    db_status["tables"][table_name] = {"count": count}
                except Exception as e:
                    db_status["tables"][table_name] = {"error": str(e)}

    except Exception as e:
        db_status["error"] = str(e)

    return db_status


async def _get_background_tasks_status(settings: Settings) -> Dict[str, Any]:
    """Lấy trạng thái các tác vụ nền."""

    tasks_status = {}

    try:
        # Tác vụ dọn dẹp
        from src.tasks.cleanup import get_cleanup_manager
        cleanup_manager = get_cleanup_manager(settings)
        tasks_status["cleanup"] = cleanup_manager.get_stats()

    except Exception as e:
        tasks_status["cleanup"] = {"error": str(e)}

    try:
        # Tác vụ giám sát
        from src.tasks.monitoring import get_monitoring_manager
        monitoring_manager = get_monitoring_manager(settings)
        tasks_status["monitoring"] = monitoring_manager.get_stats()

    except Exception as e:
        tasks_status["monitoring"] = {"error": str(e)}

    try:
        # Tác vụ sao lưu
        from src.tasks.backup import get_backup_manager
        backup_manager = get_backup_manager(settings)
        tasks_status["backup"] = backup_manager.get_stats()

    except Exception as e:
        tasks_status["backup"] = {"error": str(e)}

    return tasks_status


def _get_resource_usage() -> Dict[str, Any]:
    """Lấy thông tin sử dụng tài nguyên hệ thống."""

    # Sử dụng CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()

    # Sử dụng bộ nhớ
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Sử dụng ổ đĩa
    disk = psutil.disk_usage('/')

    # I/O mạng
    network = psutil.net_io_counters()

    return {
        "cpu": {
            "usage_percent": cpu_percent,
            "count": cpu_count,
        },
        "memory": {
            "total_mb": memory.total / (1024 * 1024),
            "used_mb": memory.used / (1024 * 1024),
            "available_mb": memory.available / (1024 * 1024),
            "usage_percent": memory.percent,
        },
        "swap": {
            "total_mb": swap.total / (1024 * 1024),
            "used_mb": swap.used / (1024 * 1024),
            "usage_percent": swap.percent,
        },
        "disk": {
            "total_gb": disk.total / (1024 * 1024 * 1024),
            "used_gb": disk.used / (1024 * 1024 * 1024),
            "free_gb": disk.free / (1024 * 1024 * 1024),
            "usage_percent": (disk.used / disk.total) * 100,
        },
        "network": {
            "bytes_sent": network.bytes_sent,
            "bytes_recv": network.bytes_recv,
            "packets_sent": network.packets_sent,
            "packets_recv": network.packets_recv,
        } if network else None,
    }


async def _get_health_status(settings: Settings) -> Dict[str, Any]:
    """Lấy trạng thái sức khỏe tổng thể."""

    health = {
        "status": "healthy",
        "checks": {},
        "issues": [],
    }

    # Kiểm tra sức khỏe cơ sở dữ liệu
    try:
        from src.database.connection import get_database_manager

        db_manager = get_database_manager(settings)
        await db_manager.test_connection()
        health["checks"]["database"] = "healthy"

    except Exception as e:
        health["checks"]["database"] = "unhealthy"
        health["issues"].append(f"Kết nối cơ sở dữ liệu thất bại: {e}")
        health["status"] = "unhealthy"

    # Kiểm tra dung lượng ổ đĩa
    disk = psutil.disk_usage('/')
    disk_usage_percent = (disk.used / disk.total) * 100

    if disk_usage_percent > 90:
        health["checks"]["disk_space"] = "critical"
        health["issues"].append(f"Sử dụng ổ đĩa nghiêm trọng: {disk_usage_percent:.1f}%")
        health["status"] = "critical"
    elif disk_usage_percent > 80:
        health["checks"]["disk_space"] = "warning"
        health["issues"].append(f"Sử dụng ổ đĩa cao: {disk_usage_percent:.1f}%")
        if health["status"] == "healthy":
            health["status"] = "warning"
    else:
        health["checks"]["disk_space"] = "healthy"

    # Kiểm tra sử dụng bộ nhớ
    memory = psutil.virtual_memory()

    if memory.percent > 90:
        health["checks"]["memory"] = "critical"
        health["issues"].append(f"Sử dụng bộ nhớ nghiêm trọng: {memory.percent:.1f}%")
        health["status"] = "critical"
    elif memory.percent > 80:
        health["checks"]["memory"] = "warning"
        health["issues"].append(f"Sử dụng bộ nhớ cao: {memory.percent:.1f}%")
        if health["status"] == "healthy":
            health["status"] = "warning"
    else:
        health["checks"]["memory"] = "healthy"

    # Kiểm tra thư mục log
    log_dir = Path(settings.log_directory)
    if log_dir.exists() and log_dir.is_dir():
        health["checks"]["log_directory"] = "healthy"
    else:
        health["checks"]["log_directory"] = "unhealthy"
        health["issues"].append(f"Thư mục log không truy cập được: {log_dir}")
        health["status"] = "unhealthy"

    # Kiểm tra thư mục sao lưu
    backup_dir = Path(settings.backup_directory)
    if backup_dir.exists() and backup_dir.is_dir():
        health["checks"]["backup_directory"] = "healthy"
    else:
        health["checks"]["backup_directory"] = "unhealthy"
        health["issues"].append(f"Thư mục sao lưu không truy cập được: {backup_dir}")
        health["status"] = "unhealthy"

    return health


def _print_text_status(status_data: Dict[str, Any], detailed: bool) -> None:
    """In trạng thái ở định dạng văn bản dễ đọc."""

    print("=" * 60)
    print("Trạng thái Máy chủ WiFi-DensePose API")
    print("=" * 60)
    print(f"Thời gian: {status_data['timestamp']}")
    print()

    # Trạng thái máy chủ
    server = status_data["server"]
    print("🖥️  Trạng thái máy chủ:")
    if server["running"]:
        print(f"   ✅ Đang chạy (PID: {server['pid']})")
        if "start_time" in server:
            uptime = timedelta(seconds=int(server["uptime_seconds"]))
            print(f"   ⏱️  Thời gian hoạt động: {uptime}")
            print(f"   💾 Bộ nhớ: {server['memory_usage_mb']:.1f} MB")
            print(f"   🔧 CPU: {server['cpu_percent']:.1f}%")
            print(f"   🧵 Luồng: {server['num_threads']}")
    else:
        print("   ❌ Không chạy")
        if server["pid_file_exists"]:
            print("   ⚠️  File PID cũ tồn tại")
    print()

    # Trạng thái hệ thống
    system = status_data["system"]
    print("🖥️  Hệ thống:")
    print(f"   Tên máy: {system['hostname']}")
    print(f"   Nền tảng: {system['platform']} ({system['architecture']})")
    print(f"   Python: {system['python_version']}")
    uptime = timedelta(seconds=int(system["uptime_seconds"]))
    print(f"   Thời gian hoạt động: {uptime}")
    print()

    # Cấu hình
    config = status_data["configuration"]
    print("⚙️  Cấu hình:")
    print(f"   Môi trường: {config['environment']}")
    print(f"   Gỡ lỗi: {config['debug']}")
    print(f"   Phiên bản API: {config['version']}")
    print(f"   Lắng nghe: {config['host']}:{config['port']}")
    print(f"   Cơ sở dữ liệu: {'✅' if config['database_configured'] else '❌'}")
    print(f"   Redis: {'✅' if config['redis_enabled'] else '❌'}")
    print(f"   Giám sát: {'✅' if config['monitoring_enabled'] else '❌'}")
    print(f"   Dọn dẹp: {'✅' if config['cleanup_enabled'] else '❌'}")
    print(f"   Sao lưu: {'✅' if config['backup_enabled'] else '❌'}")
    print()

    if detailed:
        # Trạng thái cơ sở dữ liệu
        if "database" in status_data:
            db = status_data["database"]
            print("🗄️  Cơ sở dữ liệu:")
            if db["connected"]:
                print("   ✅ Đã kết nối")
                if "tables" in db:
                    print("   📊 Số lượng bảng:")
                    for table, info in db["tables"].items():
                        if "count" in info:
                            print(f"      {table}: {info['count']:,}")
                        else:
                            print(f"      {table}: Lỗi - {info.get('error', 'Không xác định')}")
            else:
                print(f"   ❌ Chưa kết nối: {db.get('error', 'Lỗi không xác định')}")
            print()

        # Tác vụ nền
        if "background_tasks" in status_data:
            tasks = status_data["background_tasks"]
            print("🔄 Tác vụ nền:")
            for task_name, task_info in tasks.items():
                if "error" in task_info:
                    print(f"   ❌ {task_name}: {task_info['error']}")
                else:
                    manager_info = task_info.get("manager", {})
                    print(f"   📋 {task_name}:")
                    print(f"      Đang chạy: {manager_info.get('running', 'Không xác định')}")
                    print(f"      Lần chạy cuối: {manager_info.get('last_run', 'Chưa bao giờ')}")
                    print(f"      Số lần chạy: {manager_info.get('run_count', 0)}")
            print()

        # Sử dụng tài nguyên
        if "resources" in status_data:
            resources = status_data["resources"]
            print("📊 Sử dụng tài nguyên:")

            cpu = resources["cpu"]
            print(f"   🔧 CPU: {cpu['usage_percent']:.1f}% ({cpu['count']} lõi)")

            memory = resources["memory"]
            print(f"   💾 Bộ nhớ: {memory['usage_percent']:.1f}% "
                  f"({memory['used_mb']:.0f}/{memory['total_mb']:.0f} MB)")

            disk = resources["disk"]
            print(f"   💿 Ổ đĩa: {disk['usage_percent']:.1f}% "
                  f"({disk['used_gb']:.1f}/{disk['total_gb']:.1f} GB)")
            print()

        # Trạng thái sức khỏe
        if "health" in status_data:
            health = status_data["health"]
            print("🏥 Trạng thái sức khỏe:")

            status_emoji = {
                "healthy": "✅",
                "warning": "⚠️",
                "critical": "❌",
                "unhealthy": "❌"
            }

            print(f"   Tổng thể: {status_emoji.get(health['status'], '❓')} {health['status'].upper()}")

            if health["issues"]:
                print("   Các vấn đề:")
                for issue in health["issues"]:
                    print(f"      • {issue}")

            print("   Kiểm tra:")
            for check, status in health["checks"].items():
                emoji = status_emoji.get(status, "❓")
                print(f"      {emoji} {check}: {status}")
            print()

    print("=" * 60)


def get_quick_status(settings: Settings) -> str:
    """Lấy trạng thái nhanh một dòng."""

    from src.commands.stop import get_server_status

    status = get_server_status(settings)

    if status["running"]:
        return f"✅ Đang chạy (PID: {status['pid']})"
    elif status["pid_file_exists"]:
        return "⚠️  Không chạy (file PID cũ tồn tại)"
    else:
        return "❌ Không chạy"


async def check_health(settings: Settings) -> bool:
    """Kiểm tra sức khỏe nhanh - trả về True nếu khỏe mạnh."""

    try:
        status_data = await _collect_status_data(settings, detailed=True)

        # Kiểm tra máy chủ có đang chạy không
        if not status_data["server"]["running"]:
            return False

        # Kiểm tra trạng thái sức khỏe
        if "health" in status_data:
            health_status = status_data["health"]["status"]
            return health_status in ["healthy", "warning"]

        return True

    except Exception:
        return False
