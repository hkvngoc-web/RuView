"""
Triển khai lệnh dừng cho WiFi-DensePose API
"""

import asyncio
import os
import signal
import time
from pathlib import Path
from typing import Optional

from src.config.settings import Settings
from src.logger import get_logger

logger = get_logger(__name__)


async def stop_command(
    settings: Settings,
    force: bool = False,
    timeout: int = 30
) -> None:
    """Dừng máy chủ WiFi-DensePose API."""

    logger.info("Đang dừng máy chủ WiFi-DensePose API...")

    # Lấy trạng thái máy chủ
    status = get_server_status(settings)

    if not status["running"]:
        if status["pid_file_exists"]:
            logger.info("Máy chủ không đang chạy, nhưng file PID tồn tại. Đang dọn dẹp...")
            _cleanup_pid_file(settings)
        else:
            logger.info("Máy chủ không đang chạy")
        return

    pid = status["pid"]
    logger.info(f"Tìm thấy máy chủ đang chạy với PID {pid}")

    try:
        if force:
            await _force_stop_server(pid, settings)
        else:
            await _graceful_stop_server(pid, timeout, settings)

    except Exception as e:
        logger.error(f"Không thể dừng máy chủ: {e}")
        raise


async def _graceful_stop_server(pid: int, timeout: int, settings: Settings) -> None:
    """Dừng máy chủ một cách duyên dáng với thời gian chờ."""

    logger.info(f"Đang thử tắt máy chủ duyên dáng (thời gian chờ: {timeout}s)...")

    try:
        # Gửi SIGTERM để tắt duyên dáng
        os.kill(pid, signal.SIGTERM)
        logger.info("Đã gửi tín hiệu SIGTERM")

        # Chờ tiến trình kết thúc
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Kiểm tra tiến trình còn đang chạy không
                os.kill(pid, 0)
                await asyncio.sleep(1)
            except OSError:
                # Tiến trình đã kết thúc
                logger.info("Máy chủ đã dừng duyên dáng")
                _cleanup_pid_file(settings)
                return

        # Hết thời gian chờ, buộc dừng
        logger.warning(f"Hết thời gian tắt duyên dáng ({timeout}s), đang buộc dừng...")
        await _force_stop_server(pid, settings)

    except OSError as e:
        if e.errno == 3:  # Không tìm thấy tiến trình
            logger.info("Tiến trình đã kết thúc trước đó")
            _cleanup_pid_file(settings)
        else:
            logger.error(f"Không thể gửi tín hiệu đến tiến trình {pid}: {e}")
            raise


async def _force_stop_server(pid: int, settings: Settings) -> None:
    """Buộc dừng máy chủ ngay lập tức."""

    logger.info("Đang buộc dừng máy chủ...")

    try:
        # Gửi SIGKILL để kết thúc ngay lập tức
        os.kill(pid, signal.SIGKILL)
        logger.info("Đã gửi tín hiệu SIGKILL")

        # Chờ một chút để tiến trình kết thúc
        await asyncio.sleep(2)

        # Xác nhận tiến trình đã kết thúc
        try:
            os.kill(pid, 0)
            logger.error(f"Tiến trình {pid} vẫn đang chạy sau SIGKILL")
        except OSError:
            logger.info("Máy chủ đã buộc dừng")

    except OSError as e:
        if e.errno == 3:  # Không tìm thấy tiến trình
            logger.info("Tiến trình đã kết thúc trước đó")
        else:
            logger.error(f"Không thể buộc dừng tiến trình {pid}: {e}")
            raise

    finally:
        _cleanup_pid_file(settings)


def _cleanup_pid_file(settings: Settings) -> None:
    """Dọn dẹp file PID."""

    pid_file = Path(settings.log_directory) / "wifi-densepose-api.pid"

    if pid_file.exists():
        try:
            pid_file.unlink()
            logger.info("Đã dọn dẹp file PID")
        except Exception as e:
            logger.warning(f"Không thể xóa file PID: {e}")


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

            # Kiểm tra tiến trình có đang chạy không
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


async def stop_all_background_tasks(settings: Settings) -> None:
    """Dừng tất cả tác vụ nền nếu đang chạy."""

    logger.info("Đang dừng các tác vụ nền...")

    try:
        # Thông thường sẽ kết nối đến hàng đợi tác vụ hoặc
        # gửi tín hiệu đến các tiến trình nền
        # Hiện tại chỉ ghi log hành động

        logger.info("Đã gửi tín hiệu dừng tác vụ nền")

    except Exception as e:
        logger.error(f"Không thể dừng tác vụ nền: {e}")


async def cleanup_resources(settings: Settings) -> None:
    """Dọn dẹp tài nguyên hệ thống."""

    logger.info("Đang dọn dẹp tài nguyên...")

    try:
        # Đóng kết nối cơ sở dữ liệu
        from src.database.connection import get_database_manager

        db_manager = get_database_manager(settings)
        await db_manager.close_all_connections()
        logger.info("Đã đóng kết nối cơ sở dữ liệu")

    except Exception as e:
        logger.warning(f"Không thể đóng kết nối cơ sở dữ liệu: {e}")

    try:
        # Dọn dẹp file tạm
        temp_files = [
            Path(settings.log_directory) / "temp",
            Path(settings.backup_directory) / "temp",
        ]

        for temp_path in temp_files:
            if temp_path.exists() and temp_path.is_dir():
                import shutil
                shutil.rmtree(temp_path)
                logger.info(f"Đã dọn dẹp thư mục tạm: {temp_path}")

    except Exception as e:
        logger.warning(f"Không thể dọn dẹp file tạm: {e}")

    logger.info("Dọn dẹp tài nguyên hoàn tất")


def is_server_running(settings: Settings) -> bool:
    """Kiểm tra máy chủ có đang chạy không."""

    status = get_server_status(settings)
    return status["running"]


def get_server_pid(settings: Settings) -> Optional[int]:
    """Lấy PID máy chủ nếu đang chạy."""

    status = get_server_status(settings)
    return status["pid"] if status["running"] else None


async def wait_for_server_stop(settings: Settings, timeout: int = 30) -> bool:
    """Chờ máy chủ dừng với thời gian chờ."""

    start_time = time.time()

    while time.time() - start_time < timeout:
        if not is_server_running(settings):
            return True
        await asyncio.sleep(1)

    return False


def send_reload_signal(settings: Settings) -> bool:
    """Gửi tín hiệu tải lại đến máy chủ đang chạy."""

    status = get_server_status(settings)

    if not status["running"]:
        logger.error("Máy chủ không đang chạy")
        return False

    try:
        # Gửi SIGHUP để tải lại
        os.kill(status["pid"], signal.SIGHUP)
        logger.info("Đã gửi tín hiệu tải lại đến máy chủ")
        return True

    except OSError as e:
        logger.error(f"Không thể gửi tín hiệu tải lại: {e}")
        return False


async def restart_server(settings: Settings, timeout: int = 30) -> None:
    """Khởi động lại máy chủ (dừng rồi khởi động)."""

    logger.info("Đang khởi động lại máy chủ...")

    # Dừng máy chủ nếu đang chạy
    if is_server_running(settings):
        await stop_command(settings, timeout=timeout)

        # Chờ máy chủ dừng
        if not await wait_for_server_stop(settings, timeout):
            logger.error("Máy chủ không dừng trong thời gian chờ, buộc khởi động lại")
            await stop_command(settings, force=True)

    # Khởi động máy chủ
    from src.commands.start import start_command
    await start_command(settings)


def get_stop_status_summary(settings: Settings) -> dict:
    """Lấy tóm tắt trạng thái thao tác dừng."""

    status = get_server_status(settings)

    return {
        "server_running": status["running"],
        "pid": status["pid"],
        "pid_file_exists": status["pid_file_exists"],
        "can_stop": status["running"],
        "cleanup_needed": status["pid_file_exists"] and not status["running"],
    }
