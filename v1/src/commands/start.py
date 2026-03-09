"""
Triển khai lệnh khởi động cho WiFi-DensePose API
"""

import asyncio
import os
import signal
import sys
import uvicorn
from pathlib import Path
from typing import Optional

from src.config.settings import Settings
from src.logger import get_logger

logger = get_logger(__name__)


async def start_command(
    settings: Settings,
    host: str = "0.0.0.0",
    port: int = 8000,
    workers: int = 1,
    reload: bool = False,
    daemon: bool = False
) -> None:
    """Khởi động máy chủ WiFi-DensePose API."""

    logger.info(f"Đang khởi động máy chủ WiFi-DensePose API...")
    logger.info(f"Môi trường: {settings.environment}")
    logger.info(f"Chế độ gỡ lỗi: {settings.debug}")
    logger.info(f"Máy chủ: {host}")
    logger.info(f"Cổng: {port}")
    logger.info(f"Số worker: {workers}")

    # Xác thực cài đặt
    await _validate_startup_requirements(settings)

    # Thiết lập trình xử lý tín hiệu
    _setup_signal_handlers()

    # Tạo file PID nếu chạy ở chế độ daemon
    pid_file = None
    if daemon:
        pid_file = _create_pid_file(settings)

    try:
        # Khởi tạo cơ sở dữ liệu
        await _initialize_database(settings)

        # Bắt đầu các tác vụ nền
        background_tasks = await _start_background_tasks(settings)

        # Cấu hình uvicorn
        uvicorn_config = {
            "app": "src.app:app",
            "host": host,
            "port": port,
            "reload": reload,
            "workers": workers if not reload else 1,  # Reload không hoạt động với nhiều worker
            "log_level": "debug" if settings.debug else "info",
            "access_log": True,
            "use_colors": not daemon,
        }

        if daemon:
            # Chạy ở chế độ daemon
            await _run_as_daemon(uvicorn_config, pid_file)
        else:
            # Chạy ở chế độ foreground
            await _run_server(uvicorn_config)

    except KeyboardInterrupt:
        logger.info("Nhận tín hiệu ngắt, đang tắt máy chủ...")
    except Exception as e:
        logger.error(f"Khởi động máy chủ thất bại: {e}")
        raise
    finally:
        # Dọn dẹp
        if pid_file and pid_file.exists():
            pid_file.unlink()

        # Dừng các tác vụ nền
        if 'background_tasks' in locals():
            await _stop_background_tasks(background_tasks)


async def _validate_startup_requirements(settings: Settings) -> None:
    """Xác thực tất cả yêu cầu khởi động đã được đáp ứng."""

    logger.info("Đang xác thực yêu cầu khởi động...")

    # Kiểm tra kết nối cơ sở dữ liệu
    try:
        from src.database.connection import get_database_manager

        db_manager = get_database_manager(settings)
        await db_manager.test_connection()
        logger.info("✓ Kết nối cơ sở dữ liệu đã xác thực")

    except Exception as e:
        logger.error(f"✗ Kết nối cơ sở dữ liệu thất bại: {e}")
        raise

    # Kiểm tra kết nối Redis (nếu được bật)
    if settings.redis_enabled:
        try:
            redis_stats = await db_manager.get_connection_stats()
            if "redis" in redis_stats and not redis_stats["redis"].get("error"):
                logger.info("✓ Kết nối Redis đã xác thực")
            else:
                logger.warning("⚠ Kết nối Redis thất bại, tiếp tục không có Redis")

        except Exception as e:
            logger.warning(f"⚠ Kết nối Redis thất bại: {e}, tiếp tục không có Redis")

    # Kiểm tra các thư mục cần thiết
    directories = [
        ("Thư mục log", settings.log_directory),
        ("Thư mục sao lưu", settings.backup_directory),
    ]

    for name, directory in directories:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        logger.info(f"✓ {name} đã sẵn sàng: {directory}")

    logger.info("Tất cả yêu cầu khởi động đã được xác thực")


async def _initialize_database(settings: Settings) -> None:
    """Khởi tạo kết nối cơ sở dữ liệu và chạy di chuyển nếu cần."""

    logger.info("Đang khởi tạo cơ sở dữ liệu...")

    try:
        from src.database.connection import get_database_manager

        db_manager = get_database_manager(settings)
        await db_manager.initialize()

        logger.info("Khởi tạo cơ sở dữ liệu thành công")

    except Exception as e:
        logger.error(f"Khởi tạo cơ sở dữ liệu thất bại: {e}")
        raise


async def _start_background_tasks(settings: Settings) -> dict:
    """Bắt đầu các tác vụ nền."""

    logger.info("Đang bắt đầu các tác vụ nền...")

    tasks = {}

    try:
        # Bắt đầu tác vụ dọn dẹp
        if settings.cleanup_interval_seconds > 0:
            from src.tasks.cleanup import run_periodic_cleanup

            cleanup_task = asyncio.create_task(run_periodic_cleanup(settings))
            tasks['cleanup'] = cleanup_task
            logger.info("✓ Tác vụ dọn dẹp đã bắt đầu")

        # Bắt đầu tác vụ giám sát
        if settings.monitoring_interval_seconds > 0:
            from src.tasks.monitoring import run_periodic_monitoring

            monitoring_task = asyncio.create_task(run_periodic_monitoring(settings))
            tasks['monitoring'] = monitoring_task
            logger.info("✓ Tác vụ giám sát đã bắt đầu")

        # Bắt đầu tác vụ sao lưu
        if settings.backup_interval_seconds > 0:
            from src.tasks.backup import run_periodic_backup

            backup_task = asyncio.create_task(run_periodic_backup(settings))
            tasks['backup'] = backup_task
            logger.info("✓ Tác vụ sao lưu đã bắt đầu")

        logger.info(f"Đã bắt đầu {len(tasks)} tác vụ nền")
        return tasks

    except Exception as e:
        logger.error(f"Không thể bắt đầu tác vụ nền: {e}")
        # Hủy các tác vụ đã bắt đầu
        for task in tasks.values():
            task.cancel()
        raise


async def _stop_background_tasks(tasks: dict) -> None:
    """Dừng các tác vụ nền một cách nhẹ nhàng."""

    logger.info("Đang dừng các tác vụ nền...")

    # Hủy tất cả tác vụ
    for name, task in tasks.items():
        if not task.done():
            logger.info(f"Đang dừng tác vụ {name}...")
            task.cancel()

    # Chờ tác vụ hoàn thành
    if tasks:
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    logger.info("Đã dừng các tác vụ nền")


def _setup_signal_handlers() -> None:
    """Thiết lập trình xử lý tín hiệu cho tắt máy nhẹ nhàng."""

    def signal_handler(signum, frame):
        logger.info(f"Nhận tín hiệu {signum}, đang bắt đầu tắt máy nhẹ nhàng...")
        # Việc tắt máy thực tế sẽ được xử lý bởi vòng lặp chính
        sys.exit(0)

    # Thiết lập trình xử lý tín hiệu
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)


def _create_pid_file(settings: Settings) -> Path:
    """Tạo file PID cho chế độ daemon."""

    pid_file = Path(settings.log_directory) / "wifi-densepose-api.pid"

    # Kiểm tra xem file PID đã tồn tại chưa
    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())

            # Kiểm tra xem tiến trình có đang chạy không
            try:
                os.kill(old_pid, 0)  # Tín hiệu 0 chỉ kiểm tra tiến trình có tồn tại không
                logger.error(f"Máy chủ đã đang chạy với PID {old_pid}")
                sys.exit(1)
            except OSError:
                # Tiến trình không tồn tại, xóa file PID cũ
                pid_file.unlink()
                logger.info("Đã xóa file PID cũ không còn hiệu lực")

        except (ValueError, IOError):
            # File PID không hợp lệ, xóa nó
            pid_file.unlink()
            logger.info("Đã xóa file PID không hợp lệ")

    # Ghi PID hiện tại
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    logger.info(f"Đã tạo file PID: {pid_file}")
    return pid_file


async def _run_server(config: dict) -> None:
    """Chạy máy chủ ở chế độ foreground."""

    logger.info("Đang khởi động máy chủ ở chế độ foreground...")

    # Tạo máy chủ uvicorn
    server = uvicorn.Server(uvicorn.Config(**config))

    # Chạy máy chủ
    await server.serve()


async def _run_as_daemon(config: dict, pid_file: Path) -> None:
    """Chạy máy chủ ở chế độ daemon."""

    logger.info("Đang khởi động máy chủ ở chế độ daemon...")

    # Fork tiến trình
    try:
        pid = os.fork()
        if pid > 0:
            # Tiến trình cha
            logger.info(f"Máy chủ đã khởi động dưới dạng daemon với PID {pid}")
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork thất bại: {e}")
        sys.exit(1)

    # Tiến trình con tiếp tục

    # Tách khỏi môi trường tiến trình cha
    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Fork lần thứ hai
    try:
        pid = os.fork()
        if pid > 0:
            # Thoát tiến trình cha thứ hai
            sys.exit(0)
    except OSError as e:
        logger.error(f"Fork lần thứ hai thất bại: {e}")
        sys.exit(1)

    # Cập nhật file PID với PID daemon
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    # Chuyển hướng bộ mô tả file chuẩn
    sys.stdout.flush()
    sys.stderr.flush()

    # Chuyển hướng stdin, stdout, stderr sang /dev/null
    with open('/dev/null', 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())

    with open('/dev/null', 'w') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

    # Tạo máy chủ uvicorn
    server = uvicorn.Server(uvicorn.Config(**config))

    # Chạy máy chủ
    await server.serve()


def get_server_status(settings: Settings) -> dict:
    """Lấy trạng thái máy chủ hiện tại."""

    pid_file = Path(settings.log_directory) / "wifi-densepose-api.pid"

    status = {
        "running": False,
        "pid": None,
        "pid_file": str(pid_file),
        "pid_file_exists": pid_file.exists(),
    }

    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())

            status["pid"] = pid

            # Kiểm tra xem tiến trình có đang chạy không
            try:
                os.kill(pid, 0)  # Tín hiệu 0 chỉ kiểm tra tiến trình có tồn tại không
                status["running"] = True
            except OSError:
                # Tiến trình không tồn tại
                status["running"] = False

        except (ValueError, IOError):
            # File PID không hợp lệ
            status["running"] = False

    return status
