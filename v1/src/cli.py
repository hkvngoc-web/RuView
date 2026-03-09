"""
Giao diện dòng lệnh cho WiFi-DensePose API
"""

import asyncio
import click
import sys
from typing import Optional

from src.config.settings import get_settings, load_settings_from_file
from src.logger import setup_logging, get_logger
from src.commands.start import start_command
from src.commands.stop import stop_command
from src.commands.status import status_command

# Lấy cài đặt mặc định và thiết lập ghi log cho CLI
settings = get_settings()
setup_logging(settings)
logger = get_logger(__name__)


def get_settings_with_config(config_file: Optional[str] = None):
    """Lấy cài đặt với file cấu hình tùy chọn."""
    if config_file:
        return load_settings_from_file(config_file)
    else:
        return get_settings()


@click.group()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    help='Đường dẫn đến file cấu hình'
)
@click.option(
    '--verbose',
    '-v',
    is_flag=True,
    help='Bật ghi log chi tiết'
)
@click.option(
    '--debug',
    is_flag=True,
    help='Bật chế độ gỡ lỗi'
)
@click.pass_context
def cli(ctx, config: Optional[str], verbose: bool, debug: bool):
    """Giao diện dòng lệnh WiFi-DensePose API."""

    # Đảm bảo đối tượng ngữ cảnh tồn tại
    ctx.ensure_object(dict)

    # Lưu các tùy chọn CLI vào ngữ cảnh
    ctx.obj['config_file'] = config
    ctx.obj['verbose'] = verbose
    ctx.obj['debug'] = debug

    # Thiết lập mức ghi log
    if debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Đã bật chế độ gỡ lỗi")
    elif verbose:
        import logging
        logging.getLogger().setLevel(logging.INFO)
        logger.info("Đã bật chế độ chi tiết")


@cli.command()
@click.option(
    '--host',
    default='0.0.0.0',
    help='Máy chủ lắng nghe (mặc định: 0.0.0.0)'
)
@click.option(
    '--port',
    default=8000,
    type=int,
    help='Cổng lắng nghe (mặc định: 8000)'
)
@click.option(
    '--workers',
    default=1,
    type=int,
    help='Số tiến trình worker (mặc định: 1)'
)
@click.option(
    '--reload',
    is_flag=True,
    help='Bật tự động tải lại cho phát triển'
)
@click.option(
    '--daemon',
    '-d',
    is_flag=True,
    help='Chạy như daemon (tiến trình nền)'
)
@click.pass_context
def start(ctx, host: str, port: int, workers: int, reload: bool, daemon: bool):
    """Khởi động máy chủ WiFi-DensePose API."""

    try:
        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Ghi đè cài đặt bằng tùy chọn CLI
        if ctx.obj.get('debug'):
            settings.debug = True

        # Chạy lệnh khởi động
        asyncio.run(start_command(
            settings=settings,
            host=host,
            port=port,
            workers=workers,
            reload=reload,
            daemon=daemon
        ))

    except KeyboardInterrupt:
        logger.info("Đã nhận tín hiệu ngắt, đang tắt...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Không thể khởi động máy chủ: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    '--force',
    '-f',
    is_flag=True,
    help='Buộc dừng mà không tắt duyên dáng'
)
@click.option(
    '--timeout',
    default=30,
    type=int,
    help='Thời gian chờ tắt duyên dáng (mặc định: 30 giây)'
)
@click.pass_context
def stop(ctx, force: bool, timeout: int):
    """Dừng máy chủ WiFi-DensePose API."""

    try:
        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Chạy lệnh dừng
        asyncio.run(stop_command(
            settings=settings,
            force=force,
            timeout=timeout
        ))

    except Exception as e:
        logger.error(f"Không thể dừng máy chủ: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    '--format',
    type=click.Choice(['text', 'json']),
    default='text',
    help='Định dạng đầu ra (mặc định: text)'
)
@click.option(
    '--detailed',
    is_flag=True,
    help='Hiển thị thông tin trạng thái chi tiết'
)
@click.pass_context
def status(ctx, format: str, detailed: bool):
    """Hiển thị trạng thái máy chủ WiFi-DensePose API."""

    try:
        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Chạy lệnh trạng thái
        asyncio.run(status_command(
            settings=settings,
            output_format=format,
            detailed=detailed
        ))

    except Exception as e:
        logger.error(f"Không thể lấy trạng thái: {e}")
        sys.exit(1)


@cli.group()
def db():
    """Các lệnh quản lý cơ sở dữ liệu."""
    pass


@db.command()
@click.option(
    '--url',
    help='URL cơ sở dữ liệu (ghi đè cấu hình)'
)
@click.pass_context
def init(ctx, url: Optional[str]):
    """Khởi tạo schema cơ sở dữ liệu."""

    try:
        from src.database.connection import get_database_manager
        from alembic.config import Config
        from alembic import command
        import os

        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        if url:
            settings.database_url = url

        # Khởi tạo cơ sở dữ liệu
        db_manager = get_database_manager(settings)

        async def init_db():
            await db_manager.initialize()
            logger.info("Đã khởi tạo cơ sở dữ liệu thành công")

        asyncio.run(init_db())

        # Chạy migration nếu alembic.ini tồn tại
        alembic_ini_path = "alembic.ini"
        if os.path.exists(alembic_ini_path):
            try:
                alembic_cfg = Config(alembic_ini_path)
                # Đặt URL cơ sở dữ liệu trong cấu hình
                alembic_cfg.set_main_option("sqlalchemy.url", settings.get_database_url())
                command.upgrade(alembic_cfg, "head")
                logger.info("Đã áp dụng migration cơ sở dữ liệu thành công")
            except Exception as migration_error:
                logger.warning(f"Migration thất bại, nhưng cơ sở dữ liệu đã được khởi tạo: {migration_error}")
        else:
            logger.info("Không tìm thấy alembic.ini, bỏ qua migration")

    except Exception as e:
        logger.error(f"Không thể khởi tạo cơ sở dữ liệu: {e}")
        sys.exit(1)


@db.command()
@click.option(
    '--revision',
    default='head',
    help='Revision đích (mặc định: head)'
)
@click.pass_context
def migrate(ctx, revision: str):
    """Chạy migration cơ sở dữ liệu."""

    try:
        from alembic.config import Config
        from alembic import command

        # Chạy migration
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, revision)
        logger.info(f"Đã migrate cơ sở dữ liệu đến revision: {revision}")

    except Exception as e:
        logger.error(f"Không thể chạy migration: {e}")
        sys.exit(1)


@db.command()
@click.option(
    '--steps',
    default=1,
    type=int,
    help='Số bước rollback (mặc định: 1)'
)
@click.pass_context
def rollback(ctx, steps: int):
    """Rollback migration cơ sở dữ liệu."""

    try:
        from alembic.config import Config
        from alembic import command

        # Rollback migration
        alembic_cfg = Config("alembic.ini")
        command.downgrade(alembic_cfg, f"-{steps}")
        logger.info(f"Đã rollback cơ sở dữ liệu {steps} bước")

    except Exception as e:
        logger.error(f"Không thể rollback cơ sở dữ liệu: {e}")
        sys.exit(1)


@cli.group()
def tasks():
    """Các lệnh quản lý tác vụ nền."""
    pass


@tasks.command()
@click.option(
    '--task',
    type=click.Choice(['cleanup', 'monitoring', 'backup']),
    help='Tác vụ cụ thể cần chạy'
)
@click.pass_context
def run(ctx, task: Optional[str]):
    """Chạy các tác vụ nền."""

    try:
        from src.tasks.cleanup import get_cleanup_manager
        from src.tasks.monitoring import get_monitoring_manager
        from src.tasks.backup import get_backup_manager

        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        async def run_tasks():
            if task == 'cleanup' or task is None:
                cleanup_manager = get_cleanup_manager(settings)
                result = await cleanup_manager.run_all_tasks()
                logger.info(f"Kết quả dọn dẹp: {result}")

            if task == 'monitoring' or task is None:
                monitoring_manager = get_monitoring_manager(settings)
                result = await monitoring_manager.run_all_tasks()
                logger.info(f"Kết quả giám sát: {result}")

            if task == 'backup' or task is None:
                backup_manager = get_backup_manager(settings)
                result = await backup_manager.run_all_tasks()
                logger.info(f"Kết quả sao lưu: {result}")

        asyncio.run(run_tasks())

    except Exception as e:
        logger.error(f"Không thể chạy tác vụ: {e}")
        sys.exit(1)


@tasks.command()
@click.pass_context
def status(ctx):
    """Hiển thị trạng thái tác vụ nền."""

    try:
        from src.tasks.cleanup import get_cleanup_manager
        from src.tasks.monitoring import get_monitoring_manager
        from src.tasks.backup import get_backup_manager
        import json

        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Lấy trình quản lý tác vụ
        cleanup_manager = get_cleanup_manager(settings)
        monitoring_manager = get_monitoring_manager(settings)
        backup_manager = get_backup_manager(settings)

        # Thu thập trạng thái
        status_data = {
            "cleanup": cleanup_manager.get_stats(),
            "monitoring": monitoring_manager.get_stats(),
            "backup": backup_manager.get_stats(),
        }

        # In trạng thái
        click.echo(json.dumps(status_data, indent=2))

    except Exception as e:
        logger.error(f"Không thể lấy trạng thái tác vụ: {e}")
        sys.exit(1)


@cli.group()
def config():
    """Các lệnh quản lý cấu hình."""
    pass


@config.command()
@click.pass_context
def show(ctx):
    """Hiển thị cấu hình hiện tại."""

    try:
        import json

        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Chuyển đổi cài đặt sang dict (loại bỏ dữ liệu nhạy cảm)
        config_dict = {
            "app_name": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "debug": settings.debug,
            "host": settings.host,
            "port": settings.port,
            "api_prefix": settings.api_prefix,
            "docs_url": settings.docs_url,
            "redoc_url": settings.redoc_url,
            "log_level": settings.log_level,
            "log_file": settings.log_file,
            "data_storage_path": settings.data_storage_path,
            "model_storage_path": settings.model_storage_path,
            "temp_storage_path": settings.temp_storage_path,
            "wifi_interface": settings.wifi_interface,
            "csi_buffer_size": settings.csi_buffer_size,
            "pose_confidence_threshold": settings.pose_confidence_threshold,
            "stream_fps": settings.stream_fps,
            "websocket_ping_interval": settings.websocket_ping_interval,
            "features": {
                "authentication": settings.enable_authentication,
                "rate_limiting": settings.enable_rate_limiting,
                "websockets": settings.enable_websockets,
                "historical_data": settings.enable_historical_data,
                "real_time_processing": settings.enable_real_time_processing,
                "cors": settings.cors_enabled,
            }
        }

        click.echo(json.dumps(config_dict, indent=2))

    except Exception as e:
        logger.error(f"Không thể hiển thị cấu hình: {e}")
        sys.exit(1)


@config.command()
@click.pass_context
def validate(ctx):
    """Xác thực cấu hình."""

    try:
        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        # Xác thực kết nối cơ sở dữ liệu
        from src.database.connection import get_database_manager

        async def validate_config():
            db_manager = get_database_manager(settings)

            try:
                await db_manager.test_connection()
                click.echo("✓ Kết nối cơ sở dữ liệu: OK")
            except Exception as e:
                click.echo(f"✗ Kết nối cơ sở dữ liệu: THẤT BẠI - {e}")
                return False

            # Xác thực kết nối Redis (nếu đã cấu hình)
            redis_url = settings.get_redis_url()
            if redis_url:
                try:
                    import redis.asyncio as redis
                    redis_client = redis.from_url(redis_url)
                    await redis_client.ping()
                    click.echo("✓ Kết nối Redis: OK")
                    await redis_client.close()
                except Exception as e:
                    click.echo(f"✗ Kết nối Redis: THẤT BẠI - {e}")
                    return False
            else:
                click.echo("- Kết nối Redis: CHƯA CẤU HÌNH")

            # Xác thực thư mục
            from pathlib import Path

            directories = [
                ("Lưu trữ dữ liệu", settings.data_storage_path),
                ("Lưu trữ mô hình", settings.model_storage_path),
                ("Lưu trữ tạm thời", settings.temp_storage_path),
            ]

            for name, directory in directories:
                path = Path(directory)
                if path.exists() and path.is_dir():
                    click.echo(f"✓ {name}: OK")
                else:
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        click.echo(f"✓ {name}: ĐÃ TẠO - {directory}")
                    except Exception as e:
                        click.echo(f"✗ {name}: KHÔNG THỂ TẠO - {directory} ({e})")
                        return False

            click.echo("\n✓ Xác thực cấu hình đã thông qua")
            return True

        result = asyncio.run(validate_config())
        if not result:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Không thể xác thực cấu hình: {e}")
        sys.exit(1)


@config.command()
@click.option(
    '--format',
    type=click.Choice(['text', 'json']),
    default='text',
    help='Định dạng đầu ra (mặc định: text)'
)
@click.pass_context
def failsafe(ctx, format: str):
    """Hiển thị trạng thái và cấu hình dự phòng."""

    try:
        import json
        from src.database.connection import get_database_manager

        # Lấy cài đặt
        settings = get_settings_with_config(ctx.obj.get('config_file'))

        async def check_failsafe_status():
            db_manager = get_database_manager(settings)

            # Khởi tạo cơ sở dữ liệu để kiểm tra trạng thái hiện tại
            try:
                await db_manager.initialize()
            except Exception as e:
                logger.warning(f"Khởi tạo cơ sở dữ liệu thất bại: {e}")

            # Thu thập trạng thái dự phòng
            failsafe_status = {
                "database": {
                    "failsafe_enabled": settings.enable_database_failsafe,
                    "using_sqlite_fallback": db_manager.is_using_sqlite_fallback(),
                    "sqlite_fallback_path": settings.sqlite_fallback_path,
                    "primary_database_url": settings.get_database_url() if not db_manager.is_using_sqlite_fallback() else None,
                },
                "redis": {
                    "failsafe_enabled": settings.enable_redis_failsafe,
                    "redis_enabled": settings.redis_enabled,
                    "redis_required": settings.redis_required,
                    "redis_available": db_manager.is_redis_available(),
                    "redis_url": settings.get_redis_url() if settings.redis_enabled else None,
                },
                "overall_status": "healthy"
            }

            # Xác định trạng thái tổng thể
            if failsafe_status["database"]["using_sqlite_fallback"] or not failsafe_status["redis"]["redis_available"]:
                failsafe_status["overall_status"] = "degraded"

            # Xuất kết quả
            if format == 'json':
                click.echo(json.dumps(failsafe_status, indent=2))
            else:
                click.echo("=== Trạng thái dự phòng ===\n")

                # Trạng thái cơ sở dữ liệu
                click.echo("Cơ sở dữ liệu:")
                if failsafe_status["database"]["using_sqlite_fallback"]:
                    click.echo("  ⚠️  Đang sử dụng cơ sở dữ liệu dự phòng SQLite")
                    click.echo(f"     Đường dẫn: {failsafe_status['database']['sqlite_fallback_path']}")
                else:
                    click.echo("  ✓  Đang sử dụng cơ sở dữ liệu chính (PostgreSQL)")

                click.echo(f"  Dự phòng được bật: {'Có' if failsafe_status['database']['failsafe_enabled'] else 'Không'}")

                # Trạng thái Redis
                click.echo("\nRedis:")
                if not failsafe_status["redis"]["redis_enabled"]:
                    click.echo("  -  Redis đã tắt")
                elif not failsafe_status["redis"]["redis_available"]:
                    click.echo("  ⚠️  Redis không khả dụng (dự phòng đang hoạt động)")
                else:
                    click.echo("  ✓  Redis khả dụng")

                click.echo(f"  Dự phòng được bật: {'Có' if failsafe_status['redis']['failsafe_enabled'] else 'Không'}")
                click.echo(f"  Bắt buộc: {'Có' if failsafe_status['redis']['redis_required'] else 'Không'}")

                # Trạng thái tổng thể
                status_icon = "✓" if failsafe_status["overall_status"] == "healthy" else "⚠️"
                click.echo(f"\nTrạng thái tổng thể: {status_icon} {failsafe_status['overall_status'].upper()}")

                if failsafe_status["overall_status"] == "degraded":
                    click.echo("\nLưu ý: Hệ thống đang chạy ở chế độ suy giảm sử dụng cấu hình dự phòng.")

        asyncio.run(check_failsafe_status())

    except Exception as e:
        logger.error(f"Không thể kiểm tra trạng thái dự phòng: {e}")
        sys.exit(1)


@cli.command()
def version():
    """Hiển thị thông tin phiên bản."""

    try:
        from src.config.settings import get_settings

        settings = get_settings()

        click.echo(f"WiFi-DensePose API v{settings.version}")
        click.echo(f"Môi trường: {settings.environment}")
        click.echo(f"Python: {sys.version}")

    except Exception as e:
        logger.error(f"Không thể lấy phiên bản: {e}")
        sys.exit(1)


def create_cli(orchestrator=None):
    """Tạo giao diện CLI cho ứng dụng."""
    return cli


if __name__ == '__main__':
    cli()
