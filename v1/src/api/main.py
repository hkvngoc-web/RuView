"""
Ứng dụng FastAPI cho WiFi-DensePose API
"""

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config.settings import get_settings
from src.config.domains import get_domain_config
from src.api.routers import pose, stream, health
from src.api.middleware.auth import AuthMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.dependencies import get_pose_service, get_stream_service, get_hardware_service
from src.api.websocket.connection_manager import connection_manager
from src.api.websocket.pose_stream import PoseStreamHandler

# Cấu hình ghi log
settings = get_settings()
logging.config.dictConfig(settings.get_logging_config())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Trình quản lý vòng đời ứng dụng."""
    logger.info("Đang khởi động WiFi-DensePose API...")

    try:
        # Khởi tạo các dịch vụ
        await initialize_services(app)

        # Bắt đầu các tác vụ nền
        await start_background_tasks(app)

        logger.info("WiFi-DensePose API đã khởi động thành công")

        yield

    except Exception as e:
        logger.error(f"Không thể khởi động ứng dụng: {e}")
        raise
    finally:
        # Dọn dẹp khi tắt máy
        logger.info("Đang tắt WiFi-DensePose API...")
        await cleanup_services(app)
        logger.info("WiFi-DensePose API đã tắt hoàn tất")


async def initialize_services(app: FastAPI):
    """Khởi tạo các dịch vụ ứng dụng."""
    try:
        # Khởi tạo dịch vụ phần cứng
        hardware_service = get_hardware_service()
        await hardware_service.initialize()

        # Khởi tạo dịch vụ tư thế
        pose_service = get_pose_service()
        await pose_service.initialize()

        # Khởi tạo dịch vụ truyền phát
        stream_service = get_stream_service()
        await stream_service.initialize()

        # Khởi tạo trình xử lý luồng tư thế
        pose_stream_handler = PoseStreamHandler(
            connection_manager=connection_manager,
            pose_service=pose_service,
            stream_service=stream_service
        )

        # Lưu vào trạng thái ứng dụng để truy cập trong các route
        app.state.hardware_service = hardware_service
        app.state.pose_service = pose_service
        app.state.stream_service = stream_service
        app.state.pose_stream_handler = pose_stream_handler

        logger.info("Đã khởi tạo các dịch vụ thành công")

    except Exception as e:
        logger.error(f"Không thể khởi tạo các dịch vụ: {e}")
        raise


async def start_background_tasks(app: FastAPI):
    """Bắt đầu các tác vụ nền."""
    try:
        # Bắt đầu dịch vụ tư thế
        pose_service = app.state.pose_service
        await pose_service.start()
        logger.info("Dịch vụ tư thế đã bắt đầu")

        # Bắt đầu truyền phát tư thế nếu được bật
        if settings.enable_real_time_processing:
            pose_stream_handler = app.state.pose_stream_handler
            await pose_stream_handler.start_streaming()

        logger.info("Các tác vụ nền đã bắt đầu")

    except Exception as e:
        logger.error(f"Không thể bắt đầu các tác vụ nền: {e}")
        raise


async def cleanup_services(app: FastAPI):
    """Dọn dẹp các dịch vụ khi tắt."""
    try:
        # Dừng truyền phát tư thế
        if hasattr(app.state, 'pose_stream_handler'):
            await app.state.pose_stream_handler.shutdown()

        # Tắt trình quản lý kết nối
        await connection_manager.shutdown()

        # Dọn dẹp các dịch vụ
        if hasattr(app.state, 'stream_service'):
            await app.state.stream_service.shutdown()

        if hasattr(app.state, 'pose_service'):
            await app.state.pose_service.stop()

        if hasattr(app.state, 'hardware_service'):
            await app.state.hardware_service.shutdown()

        logger.info("Đã dọn dẹp các dịch vụ thành công")

    except Exception as e:
        logger.error(f"Lỗi trong quá trình dọn dẹp: {e}")


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

# Thêm middleware
if settings.enable_rate_limiting:
    app.add_middleware(RateLimitMiddleware)

if settings.enable_authentication:
    app.add_middleware(AuthMiddleware)

# Thêm middleware CORS
cors_config = settings.get_cors_config()
app.add_middleware(
    CORSMiddleware,
    **cors_config
)

# Thêm middleware máy chủ tin cậy cho môi trường sản xuất
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts
    )


# Trình xử lý ngoại lệ
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Xử lý ngoại lệ HTTP."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "type": "http_error"
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
                "details": exc.errors()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Xử lý ngoại lệ chung."""
    logger.error(f"Ngoại lệ chưa xử lý: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": 500,
                "message": "Lỗi máy chủ nội bộ",
                "type": "internal_error"
            }
        }
    )


# Middleware ghi log yêu cầu
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Ghi log tất cả yêu cầu."""
    start_time = asyncio.get_event_loop().time()

    # Xử lý yêu cầu
    response = await call_next(request)

    # Tính thời gian xử lý
    process_time = asyncio.get_event_loop().time() - start_time

    # Ghi log yêu cầu
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Trạng thái: {response.status_code} - "
        f"Thời gian: {process_time:.3f}s"
    )

    # Thêm header thời gian xử lý
    response.headers["X-Process-Time"] = str(process_time)

    return response


# Bao gồm các router
app.include_router(
    health.router,
    prefix="/health",
    tags=["Kiểm tra sức khỏe"]
)

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


# Endpoint gốc
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


# Endpoint thông tin API
@app.get(f"{settings.api_prefix}/info")
async def api_info():
    """Lấy thông tin chi tiết API."""
    domain_config = get_domain_config()

    return {
        "api": {
            "name": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "prefix": settings.api_prefix
        },
        "configuration": {
            "zones": len(domain_config.zones),
            "routers": len(domain_config.routers),
            "pose_models": len(domain_config.pose_models)
        },
        "features": {
            "authentication": settings.enable_authentication,
            "rate_limiting": settings.enable_rate_limiting,
            "websockets": settings.enable_websockets,
            "real_time_processing": settings.enable_real_time_processing,
            "historical_data": settings.enable_historical_data
        },
        "limits": {
            "rate_limit_requests": settings.rate_limit_requests,
            "rate_limit_window": settings.rate_limit_window,
            "max_websocket_connections": domain_config.streaming.max_connections
        }
    }


# Endpoint trạng thái
@app.get(f"{settings.api_prefix}/status")
async def api_status(request: Request):
    """Lấy trạng thái hiện tại của API."""
    try:
        # Lấy các dịch vụ từ trạng thái ứng dụng
        hardware_service = getattr(request.app.state, 'hardware_service', None)
        pose_service = getattr(request.app.state, 'pose_service', None)
        stream_service = getattr(request.app.state, 'stream_service', None)
        pose_stream_handler = getattr(request.app.state, 'pose_stream_handler', None)

        # Lấy trạng thái các dịch vụ
        status = {
            "api": {
                "status": "healthy",
                "uptime": "unknown",
                "version": settings.version
            },
            "services": {
                "hardware": await hardware_service.get_status() if hardware_service else {"status": "không khả dụng"},
                "pose": await pose_service.get_status() if pose_service else {"status": "không khả dụng"},
                "stream": await stream_service.get_status() if stream_service else {"status": "không khả dụng"}
            },
            "streaming": pose_stream_handler.get_stream_status() if pose_stream_handler else {"is_streaming": False},
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
            # Lấy các dịch vụ từ trạng thái ứng dụng
            pose_stream_handler = getattr(request.app.state, 'pose_stream_handler', None)

            metrics = {
                "connections": await connection_manager.get_metrics(),
                "streaming": await pose_stream_handler.get_performance_metrics() if pose_stream_handler else {}
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

        Trả về bản xem đã được làm sạch -- khóa bí mật và mật khẩu được ẩn.
        """
        _sensitive = {"secret", "password", "token", "key", "credential", "auth"}
        raw = settings.dict()
        sanitized = {
            k: "***ĐÃ ẨN***" if any(s in k.lower() for s in _sensitive) else v
            for k, v in raw.items()
        }
        domain_config = get_domain_config()
        return {
            "settings": sanitized,
            "domain_config": domain_config.to_dict()
        }

    @app.post(f"{settings.api_prefix}/dev/reset")
    async def dev_reset(request: Request):
        """Đặt lại các dịch vụ (chỉ môi trường phát triển)."""
        try:
            # Đặt lại các dịch vụ
            hardware_service = getattr(request.app.state, 'hardware_service', None)
            pose_service = getattr(request.app.state, 'pose_service', None)

            if hardware_service:
                await hardware_service.reset()

            if pose_service:
                await pose_service.reset()

            return {"message": "Đã đặt lại các dịch vụ thành công"}

        except Exception as e:
            logger.error(f"Lỗi khi đặt lại các dịch vụ: {e}")
            return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=settings.workers if not settings.reload else 1,
        log_level=settings.log_level.lower()
    )
