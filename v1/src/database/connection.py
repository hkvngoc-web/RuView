"""
Quản lý kết nối cơ sở dữ liệu cho WiFi-DensePose API
"""

import asyncio
import logging
from typing import Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError
import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError

from src.config.settings import Settings
from src.logger import get_logger

logger = get_logger(__name__)


class DatabaseConnectionError(Exception):
    """Lỗi kết nối cơ sở dữ liệu."""
    pass


class DatabaseManager:
    """Trình quản lý kết nối cơ sở dữ liệu."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._async_engine = None
        self._sync_engine = None
        self._async_session_factory = None
        self._sync_session_factory = None
        self._redis_client = None
        self._initialized = False
        self._connection_pool_size = settings.db_pool_size
        self._max_overflow = settings.db_max_overflow
        self._pool_timeout = settings.db_pool_timeout
        self._pool_recycle = settings.db_pool_recycle

    async def initialize(self):
        """Khởi tạo các kết nối cơ sở dữ liệu."""
        if self._initialized:
            return

        logger.info("Đang khởi tạo kết nối cơ sở dữ liệu")

        try:
            # Khởi tạo kết nối PostgreSQL
            await self._initialize_postgresql()

            # Khởi tạo kết nối Redis
            await self._initialize_redis()

            self._initialized = True
            logger.info("Kết nối cơ sở dữ liệu đã khởi tạo thành công")

        except Exception as e:
            logger.error(f"Không thể khởi tạo kết nối cơ sở dữ liệu: {e}")
            raise DatabaseConnectionError(f"Khởi tạo cơ sở dữ liệu thất bại: {e}")

    async def _initialize_postgresql(self):
        """Khởi tạo kết nối PostgreSQL với cơ chế dự phòng SQLite."""
        postgresql_failed = False

        try:
            # Thử PostgreSQL trước
            await self._initialize_postgresql_primary()
            logger.info("Kết nối PostgreSQL đã khởi tạo")
            return
        except Exception as e:
            postgresql_failed = True
            logger.error(f"Khởi tạo PostgreSQL thất bại: {e}")

            if not self.settings.enable_database_failsafe:
                raise DatabaseConnectionError(f"Kết nối PostgreSQL thất bại và cơ chế dự phòng bị tắt: {e}")

            logger.warning("Đang chuyển sang cơ sở dữ liệu SQLite dự phòng")

        # Chuyển sang SQLite nếu PostgreSQL thất bại và cơ chế dự phòng được bật
        if postgresql_failed and self.settings.enable_database_failsafe:
            await self._initialize_sqlite_fallback()
            logger.info("Cơ sở dữ liệu SQLite dự phòng đã khởi tạo")

    async def _initialize_postgresql_primary(self):
        """Khởi tạo kết nối PostgreSQL chính."""
        # Xây dựng URL cơ sở dữ liệu
        if self.settings.database_url and "postgresql" in self.settings.database_url:
            db_url = self.settings.database_url
            async_db_url = self.settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
        elif self.settings.db_host and self.settings.db_name and self.settings.db_user:
            db_url = (
                f"postgresql://{self.settings.db_user}:{self.settings.db_password}"
                f"@{self.settings.db_host}:{self.settings.db_port}/{self.settings.db_name}"
            )
            async_db_url = (
                f"postgresql+asyncpg://{self.settings.db_user}:{self.settings.db_password}"
                f"@{self.settings.db_host}:{self.settings.db_port}/{self.settings.db_name}"
            )
        else:
            raise ValueError("Tham số kết nối PostgreSQL chưa được cấu hình")

        # Tạo engine bất đồng bộ (không chỉ định poolclass cho engine bất đồng bộ)
        self._async_engine = create_async_engine(
            async_db_url,
            pool_size=self._connection_pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout,
            pool_recycle=self._pool_recycle,
            pool_pre_ping=True,
            echo=self.settings.db_echo,
            future=True,
        )

        # Tạo engine đồng bộ cho di cư và tác vụ quản trị
        self._sync_engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=max(2, self._connection_pool_size // 2),
            max_overflow=self._max_overflow // 2,
            pool_timeout=self._pool_timeout,
            pool_recycle=self._pool_recycle,
            pool_pre_ping=True,
            echo=self.settings.db_echo,
            future=True,
        )

        # Tạo các factory phiên làm việc
        self._async_session_factory = async_sessionmaker(
            self._async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._sync_session_factory = sessionmaker(
            self._sync_engine,
            expire_on_commit=False,
        )

        # Thêm trình lắng nghe sự kiện kết nối
        self._setup_connection_events()

        # Kiểm tra kết nối
        await self._test_postgresql_connection()

    async def _initialize_sqlite_fallback(self):
        """Khởi tạo cơ sở dữ liệu SQLite dự phòng."""
        import os

        # Đảm bảo thư mục tồn tại
        sqlite_path = self.settings.sqlite_fallback_path
        os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)

        # Xây dựng URL SQLite
        db_url = f"sqlite:///{sqlite_path}"
        async_db_url = f"sqlite+aiosqlite:///{sqlite_path}"

        # Tạo engine bất đồng bộ cho SQLite
        self._async_engine = create_async_engine(
            async_db_url,
            echo=self.settings.db_echo,
            future=True,
        )

        # Tạo engine đồng bộ cho SQLite
        self._sync_engine = create_engine(
            db_url,
            poolclass=NullPool,  # SQLite không cần gộp kết nối
            echo=self.settings.db_echo,
            future=True,
        )

        # Tạo các factory phiên làm việc
        self._async_session_factory = async_sessionmaker(
            self._async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._sync_session_factory = sessionmaker(
            self._sync_engine,
            expire_on_commit=False,
        )

        # Thêm trình lắng nghe sự kiện kết nối
        self._setup_connection_events()

        # Kiểm tra kết nối SQLite
        await self._test_sqlite_connection()

    async def _test_sqlite_connection(self):
        """Kiểm tra kết nối SQLite."""
        try:
            async with self._async_engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()  # Không dùng await - fetchone() không phải bất đồng bộ
            logger.debug("Kiểm tra kết nối SQLite thành công")
        except Exception as e:
            logger.error(f"Kiểm tra kết nối SQLite thất bại: {e}")
            raise DatabaseConnectionError(f"Kiểm tra kết nối SQLite thất bại: {e}")

    async def _initialize_redis(self):
        """Khởi tạo kết nối Redis với cơ chế dự phòng."""
        if not self.settings.redis_enabled:
            logger.info("Redis đã bị tắt, bỏ qua khởi tạo")
            return

        try:
            # Xây dựng URL Redis
            if self.settings.redis_url:
                redis_url = self.settings.redis_url
            else:
                redis_url = (
                    f"redis://{self.settings.redis_host}:{self.settings.redis_port}"
                    f"/{self.settings.redis_db}"
                )

            # Tạo máy khách Redis
            self._redis_client = redis.from_url(
                redis_url,
                password=self.settings.redis_password,
                encoding="utf-8",
                decode_responses=True,
                max_connections=self.settings.redis_max_connections,
                retry_on_timeout=True,
                socket_timeout=self.settings.redis_socket_timeout,
                socket_connect_timeout=self.settings.redis_connect_timeout,
            )

            # Kiểm tra kết nối Redis
            await self._test_redis_connection()

            logger.info("Kết nối Redis đã khởi tạo")

        except Exception as e:
            logger.error(f"Không thể khởi tạo Redis: {e}")

            if self.settings.redis_required:
                raise DatabaseConnectionError(f"Kết nối Redis thất bại và là bắt buộc: {e}")
            elif self.settings.enable_redis_failsafe:
                logger.warning("Khởi tạo Redis thất bại, tiếp tục không có Redis (cơ chế dự phòng đã bật)")
                self._redis_client = None
            else:
                logger.warning("Khởi tạo Redis thất bại nhưng không bắt buộc, tiếp tục không có Redis")
                self._redis_client = None

    def _setup_connection_events(self):
        """Thiết lập trình lắng nghe sự kiện kết nối cơ sở dữ liệu."""

        @event.listens_for(self._sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Thiết lập cài đặt đặc thù cơ sở dữ liệu khi kết nối."""
            if "sqlite" in str(self._sync_engine.url):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        @event.listens_for(self._sync_engine, "checkout")
        def receive_checkout(dbapi_connection, connection_record, connection_proxy):
            """Ghi log khi lấy kết nối ra."""
            logger.debug("Đã lấy kết nối cơ sở dữ liệu ra")

        @event.listens_for(self._sync_engine, "checkin")
        def receive_checkin(dbapi_connection, connection_record):
            """Ghi log khi trả kết nối vào."""
            logger.debug("Đã trả kết nối cơ sở dữ liệu vào")

        @event.listens_for(self._sync_engine, "invalidate")
        def receive_invalidate(dbapi_connection, connection_record, exception):
            """Xử lý khi kết nối bị vô hiệu hóa."""
            logger.warning(f"Kết nối cơ sở dữ liệu bị vô hiệu hóa: {exception}")

    async def _test_postgresql_connection(self):
        """Kiểm tra kết nối PostgreSQL."""
        try:
            async with self._async_engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()  # Không dùng await - fetchone() không phải bất đồng bộ
            logger.debug("Kiểm tra kết nối PostgreSQL thành công")
        except Exception as e:
            logger.error(f"Kiểm tra kết nối PostgreSQL thất bại: {e}")
            raise DatabaseConnectionError(f"Kiểm tra kết nối PostgreSQL thất bại: {e}")

    async def _test_redis_connection(self):
        """Kiểm tra kết nối Redis."""
        if not self._redis_client:
            return

        try:
            await self._redis_client.ping()
            logger.debug("Kiểm tra kết nối Redis thành công")
        except Exception as e:
            logger.error(f"Kiểm tra kết nối Redis thất bại: {e}")
            if self.settings.redis_required:
                raise DatabaseConnectionError(f"Kiểm tra kết nối Redis thất bại: {e}")

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Lấy phiên cơ sở dữ liệu bất đồng bộ."""
        if not self._initialized:
            await self.initialize()

        if not self._async_session_factory:
            raise DatabaseConnectionError("Factory phiên bất đồng bộ chưa được khởi tạo")

        session = self._async_session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Lỗi phiên cơ sở dữ liệu: {e}")
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def get_sync_session(self) -> Session:
        """Lấy phiên cơ sở dữ liệu đồng bộ."""
        if not self._initialized:
            await self.initialize()

        if not self._sync_session_factory:
            raise DatabaseConnectionError("Factory phiên đồng bộ chưa được khởi tạo")

        session = self._sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Lỗi phiên cơ sở dữ liệu: {e}")
            raise
        finally:
            session.close()

    async def get_redis_client(self) -> Optional[redis.Redis]:
        """Lấy máy khách Redis."""
        if not self._initialized:
            await self.initialize()

        return self._redis_client

    async def health_check(self) -> Dict[str, Any]:
        """Thực hiện kiểm tra sức khỏe cơ sở dữ liệu."""
        health_status = {
            "database": {"status": "không xác định", "details": {}},
            "redis": {"status": "không xác định", "details": {}},
            "overall": "không xác định"
        }

        # Kiểm tra cơ sở dữ liệu (PostgreSQL hoặc SQLite)
        try:
            start_time = datetime.utcnow()
            async with self.get_async_session() as session:
                result = await session.execute(text("SELECT 1"))
                result.fetchone()  # Không dùng await - fetchone() không phải bất đồng bộ

            response_time = (datetime.utcnow() - start_time).total_seconds()

            # Xác định loại cơ sở dữ liệu và trạng thái
            is_sqlite = self.is_using_sqlite_fallback()
            db_type = "sqlite_dự_phòng" if is_sqlite else "postgresql"

            details = {
                "type": db_type,
                "response_time_ms": round(response_time * 1000, 2),
            }

            # Thêm thông tin pool cho PostgreSQL
            if not is_sqlite and hasattr(self._async_engine, 'pool'):
                details.update({
                    "pool_size": self._async_engine.pool.size(),
                    "checked_out": self._async_engine.pool.checkedout(),
                    "overflow": self._async_engine.pool.overflow(),
                })

            # Thêm thông tin cơ chế dự phòng
            if is_sqlite:
                details["failsafe_active"] = True
                details["fallback_path"] = self.settings.sqlite_fallback_path

            health_status["database"] = {
                "status": "khỏe mạnh",
                "details": details
            }
        except Exception as e:
            health_status["database"] = {
                "status": "không khỏe",
                "details": {"error": str(e)}
            }

        # Kiểm tra Redis
        if self._redis_client:
            try:
                start_time = datetime.utcnow()
                await self._redis_client.ping()
                response_time = (datetime.utcnow() - start_time).total_seconds()

                info = await self._redis_client.info()

                health_status["redis"] = {
                    "status": "khỏe mạnh",
                    "details": {
                        "response_time_ms": round(response_time * 1000, 2),
                        "connected_clients": info.get("connected_clients", 0),
                        "used_memory": info.get("used_memory_human", "không xác định"),
                        "uptime": info.get("uptime_in_seconds", 0),
                    }
                }
            except Exception as e:
                health_status["redis"] = {
                    "status": "không khỏe",
                    "details": {"error": str(e)}
                }
        else:
            health_status["redis"] = {
                "status": "đã tắt",
                "details": {"message": "Redis chưa được bật"}
            }

        # Xác định trạng thái tổng thể
        database_healthy = health_status["database"]["status"] == "khỏe mạnh"
        redis_healthy = (
            health_status["redis"]["status"] in ["khỏe mạnh", "đã tắt"] or
            not self.settings.redis_required
        )

        # Kiểm tra xem có đang sử dụng chế độ dự phòng không
        using_sqlite_fallback = self.is_using_sqlite_fallback()
        redis_unavailable = not self.is_redis_available() and self.settings.redis_enabled

        if database_healthy and redis_healthy:
            if using_sqlite_fallback or redis_unavailable:
                health_status["overall"] = "suy giảm"  # Hoạt động nhưng đang dùng cơ chế dự phòng
            else:
                health_status["overall"] = "khỏe mạnh"
        elif database_healthy:
            health_status["overall"] = "suy giảm"
        else:
            health_status["overall"] = "không khỏe"

        return health_status

    async def get_connection_stats(self) -> Dict[str, Any]:
        """Lấy thống kê kết nối cơ sở dữ liệu."""
        stats = {
            "postgresql": {},
            "redis": {}
        }

        # Thống kê PostgreSQL
        if self._async_engine:
            pool = self._async_engine.pool
            stats["postgresql"] = {
                "pool_size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "checked_in": pool.checkedin(),
                "total_connections": pool.size() + pool.overflow(),
                "available_connections": pool.size() - pool.checkedout(),
            }

        # Thống kê Redis
        if self._redis_client:
            try:
                info = await self._redis_client.info()
                stats["redis"] = {
                    "connected_clients": info.get("connected_clients", 0),
                    "blocked_clients": info.get("blocked_clients", 0),
                    "total_connections_received": info.get("total_connections_received", 0),
                    "rejected_connections": info.get("rejected_connections", 0),
                }
            except Exception as e:
                stats["redis"] = {"error": str(e)}

        return stats

    async def close_connections(self):
        """Đóng tất cả kết nối cơ sở dữ liệu."""
        logger.info("Đang đóng kết nối cơ sở dữ liệu")

        # Đóng kết nối PostgreSQL
        if self._async_engine:
            await self._async_engine.dispose()
            logger.debug("Đã giải phóng engine PostgreSQL bất đồng bộ")

        if self._sync_engine:
            self._sync_engine.dispose()
            logger.debug("Đã giải phóng engine PostgreSQL đồng bộ")

        # Đóng kết nối Redis
        if self._redis_client:
            await self._redis_client.close()
            logger.debug("Đã đóng kết nối Redis")

        self._initialized = False
        logger.info("Đã đóng kết nối cơ sở dữ liệu")

    def is_using_sqlite_fallback(self) -> bool:
        """Kiểm tra xem có đang sử dụng cơ sở dữ liệu SQLite dự phòng không."""
        if not self._async_engine:
            return False
        return "sqlite" in str(self._async_engine.url)

    def is_redis_available(self) -> bool:
        """Kiểm tra xem Redis có sẵn sàng không."""
        return self._redis_client is not None

    async def test_connection(self) -> bool:
        """Kiểm tra kết nối cơ sở dữ liệu cho xác thực CLI."""
        try:
            if not self._initialized:
                await self.initialize()

            # Kiểm tra kết nối cơ sở dữ liệu (PostgreSQL hoặc SQLite)
            async with self.get_async_session() as session:
                result = await session.execute(text("SELECT 1"))
                result.fetchone()  # Không dùng await - fetchone() không phải bất đồng bộ

            # Kiểm tra kết nối Redis nếu được bật
            if self._redis_client:
                await self._redis_client.ping()

            return True
        except Exception as e:
            logger.error(f"Kiểm tra kết nối cơ sở dữ liệu thất bại: {e}")
            return False

    async def reset_connections(self):
        """Đặt lại tất cả kết nối cơ sở dữ liệu."""
        logger.info("Đang đặt lại kết nối cơ sở dữ liệu")
        await self.close_connections()
        await self.initialize()
        logger.info("Đã đặt lại kết nối cơ sở dữ liệu")


# Thể hiện toàn cục của trình quản lý cơ sở dữ liệu
_db_manager: Optional[DatabaseManager] = None


def get_database_manager(settings: Settings) -> DatabaseManager:
    """Lấy thể hiện trình quản lý cơ sở dữ liệu."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(settings)
    return _db_manager


async def get_async_session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """Phụ thuộc để lấy phiên cơ sở dữ liệu bất đồng bộ."""
    db_manager = get_database_manager(settings)
    async with db_manager.get_async_session() as session:
        yield session


async def get_redis_client(settings: Settings) -> Optional[redis.Redis]:
    """Phụ thuộc để lấy máy khách Redis."""
    db_manager = get_database_manager(settings)
    return await db_manager.get_redis_client()


class DatabaseHealthCheck:
    """Tiện ích kiểm tra sức khỏe cơ sở dữ liệu."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def check_postgresql(self) -> Dict[str, Any]:
        """Kiểm tra sức khỏe PostgreSQL."""
        try:
            start_time = datetime.utcnow()
            async with self.db_manager.get_async_session() as session:
                result = await session.execute(text("SELECT version()"))
                version = result.fetchone()[0]  # Không dùng await - fetchone() không phải bất đồng bộ

            response_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                "status": "khỏe mạnh",
                "version": version,
                "response_time_ms": round(response_time * 1000, 2),
            }
        except Exception as e:
            return {
                "status": "không khỏe",
                "error": str(e),
            }

    async def check_redis(self) -> Dict[str, Any]:
        """Kiểm tra sức khỏe Redis."""
        redis_client = await self.db_manager.get_redis_client()

        if not redis_client:
            return {
                "status": "đã tắt",
                "message": "Redis chưa được cấu hình"
            }

        try:
            start_time = datetime.utcnow()
            pong = await redis_client.ping()
            response_time = (datetime.utcnow() - start_time).total_seconds()

            info = await redis_client.info("server")

            return {
                "status": "khỏe mạnh",
                "ping": pong,
                "version": info.get("redis_version", "không xác định"),
                "response_time_ms": round(response_time * 1000, 2),
            }
        except Exception as e:
            return {
                "status": "không khỏe",
                "error": str(e),
            }

    async def full_health_check(self) -> Dict[str, Any]:
        """Thực hiện kiểm tra sức khỏe cơ sở dữ liệu đầy đủ."""
        postgresql_health = await self.check_postgresql()
        redis_health = await self.check_redis()

        overall_status = "khỏe mạnh"
        if postgresql_health["status"] != "khỏe mạnh":
            overall_status = "không khỏe"
        elif redis_health["status"] == "không khỏe":
            overall_status = "suy giảm"

        return {
            "overall_status": overall_status,
            "postgresql": postgresql_health,
            "redis": redis_health,
            "timestamp": datetime.utcnow().isoformat(),
        }
