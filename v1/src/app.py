"""
Nhà máy tạo và cấu hình ứng dụng FastAPI
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config.settings import Settings
from src.services.orchestrator import ServiceOrchestrator
from src.middleware.auth import AuthenticationMiddleware
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.error_handler import ErrorHandlingMiddleware
from src.api.routers import pose, stream, health
from src.api.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Trình quản lý vòng đời ứng dụng."""
    logger.info("Đang khởi động WiFi-DensePose API...")

    try:
        # Lấy trình điều phối từ trạng thái ứng dụng
        orchestrator: ServiceOrchestrator = app.state.orchestrator

        # Bắt đầu trình quản lý kết nối
        await connection_manager.start()

        # Bắt đầu tất cả dịch vụ
        await orchestrator.start()

        logger.info("WiFi-DensePose API đã khởi động thành công")

        yield

    except Exception as e:
        logger.error(f"Không thể khởi động ứng dụng: {e}")
        raise
    finally:
        # Dọn dẹp khi tắt
        logger.info("Đang tắt WiFi-DensePose API...")

        # Tắt trình quản lý kết nối
        await connection_manager.shutdown()

        if hasattr(app.state, 'orchestrator'):
            await app.state.orchestrator.shutdown()
        logger.info("WiFi-DensePose API đã tắt hoàn tất")


def create_app(settings: Settings, orchestrator: ServiceOrchestrator) -> FastAPI:
    """Tạo và cấu hình ứng dụng FastAPI."""

    # Tạo ứng dụng FastAPI
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="API ước lượng tư thế con người và nhận dạng hoạt động dựa trên WiFi",
        docs_url=settings.docs_url if not settings.is_production else None,
        redoc_url=settings.redoc_url if not settings.is_production else None,
        openapi_url=settings.openapi_url if not settings.is_production else None,
        lifespan=lifespan
    )

    # Lưu trình điều phối vào trạng thái ứng dụng
    app.state.orchestrator = orchestrator
    app.state.settings = settings

    # Thêm middleware theo thứ tự ngược (thêm cuối = thực thi trước)
    setup_middleware(app, settings)

    # Thêm trình xử lý ngoại lệ
    setup_exception_handlers(app)

    # Bao gồm các router
    setup_routers(app, settings)

    # Thêm endpoint gốc
    setup_root_endpoints(app, settings)

    return app


def setup_middleware(app: FastAPI, settings: Settings):
    """Thiết lập middleware ứng dụng."""

    # Middleware giới hạn tốc độ
    if settings.enable_rate_limiting:
        app.add_middleware(RateLimitMiddleware, settings=settings)

    # Middleware xác thực
    if settings.enable_authentication:
        app.add_middleware(AuthenticationMiddleware, settings=settings)

    # Middleware CORS
    if settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            allow_headers=["*"],
        )

    # Middleware máy chủ tin cậy cho môi trường sản xuất
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.allowed_hosts
        )


def setup_exception_handlers(app: FastAPI):
    """Thiết lập trình xử lý ngoại lệ toàn cục."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Xử lý ngoại lệ HTTP."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "type": "http_error",
                    "path": str(request.url.path)
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Xử lý lỗi xác thực yêu cầu."""
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": 422,
                    "message": "Lỗi xác thực",
                    "type": "validation_error",
                    "path": str(request.url.path),
                    "details": exc.errors()
                }
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Xử lý ngoại lệ chung."""
        logger.error(f"Ngoại lệ chưa xử lý tại {request.url.path}: {exc}", exc_info=True)

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": "Lỗi máy chủ nội bộ",
                    "type": "internal_error",
                    "path": str(request.url.path)
                }
            }
        )


def setup_routers(app: FastAPI, settings: Settings):
    """Thiết lập các router API."""

    # Router kiểm tra sức khỏe (không có prefix)
    app.include_router(
        health.router,
        prefix="/health",
        tags=["Kiểm tra sức khỏe"]
    )

    # Các router API với prefix
    app.include_router(
        pose.router,
        prefix=f"{settings.api_prefix}/pose",
        tags=["Ước lượng tư thế"]
    )

    app.include_router(
        stream.router,
        prefix=f"{settings.api_prefix}/stream",
        tags=["Truyền phát"]
    )


def setup_root_endpoints(app: FastAPI, settings: Settings):
    """Thiết lập các endpoint gốc của ứng dụng."""

    @app.get("/")
    async def root():
        """Endpoint gốc với thông tin API."""
        return {
            "name": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "docs_url": settings.docs_url,
            "api_prefix": settings.api_prefix,
            "features": {
                "authentication": settings.enable_authentication,
                "rate_limiting": settings.enable_rate_limiting,
                "websockets": settings.enable_websockets,
                "real_time_processing": settings.enable_real_time_processing
            }
        }

    @app.get(f"{settings.api_prefix}/info")
    async def api_info(request: Request):
        """Lấy thông tin chi tiết API."""
        orchestrator: ServiceOrchestrator = request.app.state.orchestrator

        return {
            "api": {
                "name": settings.app_name,
                "version": settings.version,
                "environment": settings.environment,
                "prefix": settings.api_prefix
            },
            "services": await orchestrator.get_service_info(),
            "features": {
                "authentication": settings.enable_authentication,
                "rate_limiting": settings.enable_rate_limiting,
                "websockets": settings.enable_websockets,
                "real_time_processing": settings.enable_real_time_processing,
                "historical_data": settings.enable_historical_data
            },
            "limits": {
                "rate_limit_requests": settings.rate_limit_requests,
                "rate_limit_window": settings.rate_limit_window
            }
        }

    @app.get(f"{settings.api_prefix}/status")
    async def api_status(request: Request):
        """Lấy trạng thái hiện tại của API."""
        try:
            orchestrator: ServiceOrchestrator = request.app.state.orchestrator

            status = {
                "api": {
                    "status": "healthy",
                    "version": settings.version,
                    "environment": settings.environment
                },
                "services": await orchestrator.get_service_status(),
                "connections": await connection_manager.get_connection_stats()
            }

            return status

        except Exception as e:
            logger.error(f"Lỗi khi lấy trạng thái API: {e}")
            return {
                "api": {
                    "status": "lỗi",
                    "error": str(e)
                }
            }

    # Endpoint số liệu (nếu được bật)
    if settings.metrics_enabled:
        @app.get(f"{settings.api_prefix}/metrics")
        async def api_metrics(request: Request):
            """Lấy số liệu API."""
            try:
                orchestrator: ServiceOrchestrator = request.app.state.orchestrator

                metrics = {
                    "connections": await connection_manager.get_metrics(),
                    "services": await orchestrator.get_service_metrics()
                }

                return metrics

            except Exception as e:
                logger.error(f"Lỗi khi lấy số liệu: {e}")
                return {"error": str(e)}

    # Endpoint phát triển (chỉ trong môi trường phát triển)
    if settings.is_development and settings.enable_test_endpoints:
        @app.get(f"{settings.api_prefix}/dev/config")
        async def dev_config():
            """Lấy cấu hình hiện tại (chỉ môi trường phát triển).

            Trả về bản xem đã được làm sạch của cài đặt. Khóa bí mật,
            mật khẩu và biến môi trường thô không bao giờ được hiển thị.
            """
            # Xây dựng bản sao đã làm sạch -- ẩn bất kỳ khóa nào có vẻ nhạy cảm
            _sensitive = {"secret", "password", "token", "key", "credential", "auth"}
            raw = settings.dict()
            sanitized = {
                k: "***ĐÃ ẨN***" if any(s in k.lower() for s in _sensitive) else v
                for k, v in raw.items()
            }
            return {
                "settings": sanitized,
                "environment": settings.environment,
            }

        @app.post(f"{settings.api_prefix}/dev/reset")
        async def dev_reset(request: Request):
            """Đặt lại các dịch vụ (chỉ môi trường phát triển)."""
            try:
                orchestrator: ServiceOrchestrator = request.app.state.orchestrator
                await orchestrator.reset_services()
                return {"message": "Đã đặt lại các dịch vụ thành công"}

            except Exception as e:
                logger.error(f"Lỗi khi đặt lại các dịch vụ: {e}")
                return {"error": str(e)}


# Tạo thể hiện ứng dụng mặc định cho uvicorn
def get_app() -> FastAPI:
    """Lấy thể hiện ứng dụng mặc định."""
    from src.config.settings import get_settings
    from src.services.orchestrator import ServiceOrchestrator

    settings = get_settings()
    orchestrator = ServiceOrchestrator(settings)
    return create_app(settings, orchestrator)


# Thể hiện ứng dụng mặc định cho uvicorn
app = get_app()
