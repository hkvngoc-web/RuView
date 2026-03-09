"""
Middleware xử lý lỗi toàn cục cho WiFi-DensePose API
"""

import logging
import traceback
import time
from typing import Dict, Any, Optional, Callable, Union
from datetime import datetime

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from src.config.settings import Settings
from src.logger import get_request_context

logger = logging.getLogger(__name__)


class ErrorResponse:
    """Định dạng phản hồi lỗi chuẩn hóa."""

    def __init__(
        self,
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
        request_id: Optional[str] = None,
    ):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        self.request_id = request_id
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang dictionary cho phản hồi JSON."""
        response = {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "timestamp": self.timestamp,
            }
        }

        if self.details:
            response["error"]["details"] = self.details

        if self.request_id:
            response["error"]["request_id"] = self.request_id

        return response

    def to_response(self) -> JSONResponse:
        """Chuyển đổi sang JSONResponse của FastAPI."""
        headers = {}
        if self.request_id:
            headers["X-Request-ID"] = self.request_id

        return JSONResponse(
            status_code=self.status_code,
            content=self.to_dict(),
            headers=headers
        )


class ErrorHandler:
    """Trình xử lý lỗi trung tâm cho ứng dụng."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.include_traceback = settings.debug and settings.is_development
        self.log_errors = True

    def handle_http_exception(self, request: Request, exc: HTTPException) -> ErrorResponse:
        """Xử lý ngoại lệ HTTP."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.warning(
                f"HTTP {exc.status_code}: {exc.detail} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}"
            )

        # Xác định mã lỗi
        error_code = self._get_error_code_for_status(exc.status_code)

        # Xây dựng chi tiết lỗi
        details = {}
        if hasattr(exc, "headers") and exc.headers:
            details["headers"] = exc.headers

        if self.include_traceback and hasattr(exc, "__traceback__"):
            details["traceback"] = traceback.format_exception(
                type(exc), exc, exc.__traceback__
            )

        return ErrorResponse(
            error_code=error_code,
            message=str(exc.detail),
            details=details,
            status_code=exc.status_code,
            request_id=request_id
        )

    def handle_validation_error(self, request: Request, exc: RequestValidationError) -> ErrorResponse:
        """Xử lý lỗi xác thực yêu cầu."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.warning(
                f"Lỗi xác thực: {exc.errors()} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}"
            )

        # Định dạng lỗi xác thực
        validation_details = []
        for error in exc.errors():
            validation_details.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
                "input": error.get("input"),
            })

        details = {
            "validation_errors": validation_details,
            "error_count": len(validation_details)
        }

        if self.include_traceback:
            details["traceback"] = traceback.format_exception(
                type(exc), exc, exc.__traceback__
            )

        return ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Xác thực yêu cầu thất bại",
            details=details,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request_id=request_id
        )

    def handle_pydantic_error(self, request: Request, exc: ValidationError) -> ErrorResponse:
        """Xử lý lỗi xác thực Pydantic."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.warning(
                f"Lỗi xác thực Pydantic: {exc.errors()} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}"
            )

        # Định dạng lỗi xác thực
        validation_details = []
        for error in exc.errors():
            validation_details.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })

        details = {
            "validation_errors": validation_details,
            "error_count": len(validation_details)
        }

        return ErrorResponse(
            error_code="DATA_VALIDATION_ERROR",
            message="Xác thực dữ liệu thất bại",
            details=details,
            status_code=status.HTTP_400_BAD_REQUEST,
            request_id=request_id
        )

    def handle_generic_exception(self, request: Request, exc: Exception) -> ErrorResponse:
        """Xử lý ngoại lệ chung."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.error(
                f"Ngoại lệ chưa xử lý: {type(exc).__name__}: {exc} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}",
                exc_info=True
            )

        # Xác định chi tiết lỗi
        details = {
            "exception_type": type(exc).__name__,
        }

        if self.include_traceback:
            details["traceback"] = traceback.format_exception(
                type(exc), exc, exc.__traceback__
            )

        # Không tiết lộ chi tiết lỗi nội bộ trong môi trường sản xuất
        if self.settings.is_production:
            message = "Đã xảy ra lỗi máy chủ nội bộ"
        else:
            message = str(exc) or "Đã xảy ra lỗi không mong đợi"

        return ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message=message,
            details=details,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            request_id=request_id
        )

    def handle_database_error(self, request: Request, exc: Exception) -> ErrorResponse:
        """Xử lý lỗi liên quan đến cơ sở dữ liệu."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.error(
                f"Lỗi cơ sở dữ liệu: {type(exc).__name__}: {exc} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}",
                exc_info=True
            )

        details = {
            "exception_type": type(exc).__name__,
            "category": "database"
        }

        if self.include_traceback:
            details["traceback"] = traceback.format_exception(
                type(exc), exc, exc.__traceback__
            )

        return ErrorResponse(
            error_code="DATABASE_ERROR",
            message="Thao tác cơ sở dữ liệu thất bại" if self.settings.is_production else str(exc),
            details=details,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            request_id=request_id
        )

    def handle_external_service_error(self, request: Request, exc: Exception) -> ErrorResponse:
        """Xử lý lỗi dịch vụ bên ngoài."""
        request_context = get_request_context()
        request_id = request_context.get("request_id")

        # Ghi log lỗi
        if self.log_errors:
            logger.error(
                f"Lỗi dịch vụ bên ngoài: {type(exc).__name__}: {exc} - "
                f"{request.method} {request.url.path} - "
                f"ID yêu cầu: {request_id}",
                exc_info=True
            )

        details = {
            "exception_type": type(exc).__name__,
            "category": "external_service"
        }

        return ErrorResponse(
            error_code="EXTERNAL_SERVICE_ERROR",
            message="Dịch vụ bên ngoài không khả dụng" if self.settings.is_production else str(exc),
            details=details,
            status_code=status.HTTP_502_BAD_GATEWAY,
            request_id=request_id
        )

    def _get_error_code_for_status(self, status_code: int) -> str:
        """Lấy mã lỗi cho mã trạng thái HTTP."""
        error_codes = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "UNPROCESSABLE_ENTITY",
            429: "TOO_MANY_REQUESTS",
            500: "INTERNAL_SERVER_ERROR",
            502: "BAD_GATEWAY",
            503: "SERVICE_UNAVAILABLE",
            504: "GATEWAY_TIMEOUT",
        }

        return error_codes.get(status_code, "HTTP_ERROR")


class ErrorHandlingMiddleware:
    """Middleware xử lý lỗi cho FastAPI."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.error_handler = ErrorHandler(settings)

    async def __call__(self, scope, receive, send):
        """Xử lý yêu cầu qua middleware xử lý lỗi."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # Tạo đối tượng request giả cho xử lý lỗi
            from starlette.requests import Request
            request = Request(scope, receive)

            # Xử lý các loại ngoại lệ khác nhau
            if isinstance(exc, HTTPException):
                error_response = self.error_handler.handle_http_exception(request, exc)
            elif isinstance(exc, RequestValidationError):
                error_response = self.error_handler.handle_validation_error(request, exc)
            elif isinstance(exc, ValidationError):
                error_response = self.error_handler.handle_pydantic_error(request, exc)
            else:
                # Kiểm tra các loại lỗi cụ thể
                if self._is_database_error(exc):
                    error_response = self.error_handler.handle_database_error(request, exc)
                elif self._is_external_service_error(exc):
                    error_response = self.error_handler.handle_external_service_error(request, exc)
                else:
                    error_response = self.error_handler.handle_generic_exception(request, exc)

            # Gửi phản hồi lỗi
            response = error_response.to_response()
            await response(scope, receive, send)

        finally:
            # Ghi log thời gian xử lý yêu cầu
            processing_time = time.time() - start_time
            logger.debug(f"Thời gian xử lý middleware xử lý lỗi: {processing_time:.3f}s")

    def _is_database_error(self, exc: Exception) -> bool:
        """Kiểm tra xem ngoại lệ có liên quan đến cơ sở dữ liệu không."""
        database_exceptions = [
            "sqlalchemy",
            "psycopg2",
            "pymongo",
            "redis",
            "ConnectionError",
            "OperationalError",
            "IntegrityError",
        ]

        exc_module = getattr(type(exc), "__module__", "")
        exc_name = type(exc).__name__

        return any(
            db_exc in exc_module or db_exc in exc_name
            for db_exc in database_exceptions
        )

    def _is_external_service_error(self, exc: Exception) -> bool:
        """Kiểm tra xem ngoại lệ có liên quan đến dịch vụ bên ngoài không."""
        external_exceptions = [
            "requests",
            "httpx",
            "aiohttp",
            "urllib",
            "ConnectionError",
            "TimeoutError",
            "ConnectTimeout",
            "ReadTimeout",
        ]

        exc_module = getattr(type(exc), "__module__", "")
        exc_name = type(exc).__name__

        return any(
            ext_exc in exc_module or ext_exc in exc_name
            for ext_exc in external_exceptions
        )


def setup_error_handling(app, settings: Settings):
    """Thiết lập xử lý lỗi cho ứng dụng."""
    logger.info("Đang thiết lập middleware xử lý lỗi")

    error_handler = ErrorHandler(settings)

    # Thêm các trình xử lý ngoại lệ
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        error_response = error_handler.handle_http_exception(request, exc)
        return error_response.to_response()

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Chuyển đổi ngoại lệ Starlette HTTPException sang FastAPI HTTPException
        fastapi_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
        error_response = error_handler.handle_http_exception(request, fastapi_exc)
        return error_response.to_response()

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        error_response = error_handler.handle_validation_error(request, exc)
        return error_response.to_response()

    @app.exception_handler(ValidationError)
    async def pydantic_exception_handler(request: Request, exc: ValidationError):
        error_response = error_handler.handle_pydantic_error(request, exc)
        return error_response.to_response()

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        error_response = error_handler.handle_generic_exception(request, exc)
        return error_response.to_response()

    # Thêm middleware cho xử lý lỗi bổ sung
    # Lưu ý: Chúng ta dùng trình xử lý ngoại lệ thay vì middleware tùy chỉnh để tránh xung đột ASGI
    # Cách tiếp cận middleware được giữ lại để tham khảo nhưng đã bị comment
    # middleware = ErrorHandlingMiddleware(app, settings)
    # app.add_middleware(ErrorHandlingMiddleware, settings=settings)

    logger.info("Đã cấu hình xử lý lỗi")


class CustomHTTPException(HTTPException):
    """Ngoại lệ HTTP tùy chỉnh với ngữ cảnh bổ sung."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code
        self.context = context or {}


class BusinessLogicError(CustomHTTPException):
    """Ngoại lệ cho lỗi logic nghiệp vụ."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
            error_code="BUSINESS_LOGIC_ERROR",
            context=context
        )


class ResourceNotFoundError(CustomHTTPException):
    """Ngoại lệ cho lỗi không tìm thấy tài nguyên."""

    def __init__(self, resource: str, identifier: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy {resource}",
            error_code="RESOURCE_NOT_FOUND",
            context={"resource": resource, "identifier": identifier}
        )


class ConflictError(CustomHTTPException):
    """Ngoại lệ cho lỗi xung đột."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
            error_code="CONFLICT_ERROR",
            context=context
        )


class ServiceUnavailableError(CustomHTTPException):
    """Ngoại lệ cho lỗi dịch vụ không khả dụng."""

    def __init__(self, service: str, reason: Optional[str] = None):
        detail = f"Dịch vụ {service} không khả dụng"
        if reason:
            detail += f": {reason}"

        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            error_code="SERVICE_UNAVAILABLE",
            context={"service": service, "reason": reason}
        )
