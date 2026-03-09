"""Cấu hình môi trường Alembic cho WiFi-DensePose API."""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Thêm thư mục gốc dự án vào đường dẫn Python
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import mô hình và cài đặt
from src.database.models import Base
from src.config.settings import get_settings

# Đây là đối tượng Alembic Config, cung cấp
# quyền truy cập vào các giá trị trong tệp .ini đang sử dụng.
config = context.config

# Diễn giải tệp cấu hình cho logging Python.
# Dòng này thiết lập logger cơ bản.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Thêm đối tượng MetaData của mô hình ở đây
# để hỗ trợ 'autogenerate'
target_metadata = Base.metadata

# Các giá trị khác từ cấu hình, được xác định bởi nhu cầu của env.py,
# có thể được lấy:
# my_important_option = config.get_main_option("my_important_option")
# ... v.v.


def get_database_url():
    """Lấy URL cơ sở dữ liệu từ cài đặt."""
    try:
        settings = get_settings()
        return settings.get_database_url()
    except Exception:
        # Dự phòng sang SQLite nếu không thể tải cài đặt
        return "sqlite:///./data/wifi_densepose_fallback.db"


def run_migrations_offline() -> None:
    """Chạy di cư ở chế độ 'offline'.

    Cấu hình context chỉ với URL
    và không có Engine, mặc dù Engine cũng được chấp nhận
    ở đây. Bằng cách bỏ qua việc tạo Engine,
    ta không cần DBAPI phải khả dụng.

    Các lệnh gọi context.execute() ở đây phát ra chuỗi đã cho
    đến đầu ra script.

    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Chạy di cư với kết nối cơ sở dữ liệu."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Chạy di cư ở chế độ bất đồng bộ."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Chạy di cư ở chế độ 'online'."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
