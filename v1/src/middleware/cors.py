"""
Middleware CORS cho WiFi-DensePose API
"""

import logging
from typing import List, Optional, Union, Callable
from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware as FastAPICORSMiddleware
from starlette.types import ASGIApp

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class CORSMiddleware:
    """Middleware CORS nâng cao với các tính năng bảo mật bổ sung."""

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        allow_origins: Optional[List[str]] = None,
        allow_methods: Optional[List[str]] = None,
        allow_headers: Optional[List[str]] = None,
        allow_credentials: bool = False,
        expose_headers: Optional[List[str]] = None,
        max_age: int = 600,
    ):
        self.app = app
        self.settings = settings
        self.allow_origins = allow_origins or settings.cors_origins
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
        self.allow_headers = allow_headers or [
            "Accept",
            "Accept-Language",
            "Content-Language",
            "Content-Type",
            "Authorization",
            "X-Requested-With",
            "X-Request-ID",
            "X-User-Agent",
        ]
        self.allow_credentials = allow_credentials or settings.cors_allow_credentials
        self.expose_headers = expose_headers or [
            "X-Request-ID",
            "X-Response-Time",
            "X-Rate-Limit-Remaining",
            "X-Rate-Limit-Reset",
        ]
        self.max_age = max_age

        # Cài đặt bảo mật
        self.strict_origin_check = settings.is_production
        self.log_cors_violations = True

    async def __call__(self, scope, receive, send):
        """Triển khai middleware ASGI."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Kiểm tra xem đây có phải yêu cầu preflight CORS không
        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            response = await self._handle_preflight(request)
            await response(scope, receive, send)
            return

        # Xử lý yêu cầu thực tế
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Thêm header CORS vào phản hồi
                headers = dict(message.get("headers", []))
                cors_headers = self._get_cors_headers(request)

                for key, value in cors_headers.items():
                    headers[key.encode()] = value.encode()

                message["headers"] = list(headers.items())

            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _handle_preflight(self, request: Request) -> Response:
        """Xử lý yêu cầu preflight CORS."""
        origin = request.headers.get("origin")
        requested_method = request.headers.get("access-control-request-method")
        requested_headers = request.headers.get("access-control-request-headers", "")

        # Xác thực nguồn gốc
        if not self._is_origin_allowed(origin):
            if self.log_cors_violations:
                logger.warning(f"Preflight CORS bị từ chối cho nguồn gốc: {origin}")

            return Response(
                status_code=403,
                content="Yêu cầu preflight CORS bị từ chối",
                headers={"Content-Type": "text/plain"}
            )

        # Xác thực phương thức
        if requested_method not in self.allow_methods:
            if self.log_cors_violations:
                logger.warning(f"Preflight CORS bị từ chối cho phương thức: {requested_method}")

            return Response(
                status_code=405,
                content="Phương thức không được phép",
                headers={"Content-Type": "text/plain"}
            )

        # Xác thực header
        if requested_headers:
            requested_header_list = [h.strip().lower() for h in requested_headers.split(",")]
            allowed_headers_lower = [h.lower() for h in self.allow_headers]

            for header in requested_header_list:
                if header not in allowed_headers_lower:
                    if self.log_cors_violations:
                        logger.warning(f"Preflight CORS bị từ chối cho header: {header}")

                    return Response(
                        status_code=400,
                        content="Header không được phép",
                        headers={"Content-Type": "text/plain"}
                    )

        # Xây dựng header phản hồi preflight
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ", ".join(self.allow_methods),
            "Access-Control-Allow-Headers": ", ".join(self.allow_headers),
            "Access-Control-Max-Age": str(self.max_age),
        }

        if self.allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

        if self.expose_headers:
            headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

        logger.debug(f"Preflight CORS được chấp nhận cho nguồn gốc: {origin}")

        return Response(
            status_code=200,
            headers=headers
        )

    def _get_cors_headers(self, request: Request) -> dict:
        """Lấy header CORS cho yêu cầu thực tế."""
        origin = request.headers.get("origin")
        headers = {}

        if self._is_origin_allowed(origin):
            headers["Access-Control-Allow-Origin"] = origin

            if self.allow_credentials:
                headers["Access-Control-Allow-Credentials"] = "true"

            if self.expose_headers:
                headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)

        return headers

    def _is_origin_allowed(self, origin: Optional[str]) -> bool:
        """Kiểm tra xem nguồn gốc có được phép không."""
        if not origin:
            return not self.strict_origin_check

        # Cho phép tất cả nguồn gốc trong môi trường phát triển
        if not self.settings.is_production and "*" in self.allow_origins:
            return True

        # Kiểm tra khớp chính xác
        if origin in self.allow_origins:
            return True

        # Kiểm tra mẫu ký tự đại diện
        for allowed_origin in self.allow_origins:
            if allowed_origin == "*":
                return not self.strict_origin_check

            if self._match_origin_pattern(origin, allowed_origin):
                return True

        return False

    def _match_origin_pattern(self, origin: str, pattern: str) -> bool:
        """So khớp nguồn gốc với mẫu hỗ trợ ký tự đại diện."""
        if "*" not in pattern:
            return origin == pattern

        # So khớp ký tự đại diện đơn giản
        if pattern.startswith("*."):
            domain = pattern[2:]
            parsed_origin = urlparse(origin)
            origin_host = parsed_origin.netloc

            # Kiểm tra xem nguồn gốc có kết thúc bằng tên miền không
            return origin_host.endswith(domain) or origin_host == domain[1:] if domain.startswith('.') else origin_host == domain

        return False


def setup_cors_middleware(app: ASGIApp, settings: Settings) -> ASGIApp:
    """Thiết lập middleware CORS cho ứng dụng."""

    if settings.cors_enabled:
        logger.info("Đang thiết lập middleware CORS")

        # Sử dụng middleware CORS tích hợp của FastAPI cho chức năng cơ bản
        app = FastAPICORSMiddleware(
            app,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            allow_headers=[
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization",
                "X-Requested-With",
                "X-Request-ID",
                "X-User-Agent",
            ],
            expose_headers=[
                "X-Request-ID",
                "X-Response-Time",
                "X-Rate-Limit-Remaining",
                "X-Rate-Limit-Reset",
            ],
            max_age=600,
        )

        logger.info(f"CORS đã bật cho các nguồn gốc: {settings.cors_origins}")
    else:
        logger.info("Middleware CORS đã bị tắt")

    return app


class CORSConfig:
    """Trình trợ giúp cấu hình CORS."""

    @staticmethod
    def development_config() -> dict:
        """Lấy cấu hình CORS cho môi trường phát triển."""
        return {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
            "expose_headers": [
                "X-Request-ID",
                "X-Response-Time",
                "X-Rate-Limit-Remaining",
                "X-Rate-Limit-Reset",
            ],
            "max_age": 600,
        }

    @staticmethod
    def production_config(allowed_origins: List[str]) -> dict:
        """Lấy cấu hình CORS cho môi trường sản xuất."""
        return {
            "allow_origins": allowed_origins,
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            "allow_headers": [
                "Accept",
                "Accept-Language",
                "Content-Language",
                "Content-Type",
                "Authorization",
                "X-Requested-With",
                "X-Request-ID",
                "X-User-Agent",
            ],
            "expose_headers": [
                "X-Request-ID",
                "X-Response-Time",
                "X-Rate-Limit-Remaining",
                "X-Rate-Limit-Reset",
            ],
            "max_age": 3600,  # 1 giờ cho môi trường sản xuất
        }

    @staticmethod
    def api_only_config(allowed_origins: List[str]) -> dict:
        """Lấy cấu hình CORS cho truy cập chỉ API."""
        return {
            "allow_origins": allowed_origins,
            "allow_credentials": False,
            "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": [
                "Accept",
                "Content-Type",
                "Authorization",
                "X-Request-ID",
            ],
            "expose_headers": [
                "X-Request-ID",
                "X-Rate-Limit-Remaining",
                "X-Rate-Limit-Reset",
            ],
            "max_age": 3600,
        }

    @staticmethod
    def websocket_config(allowed_origins: List[str]) -> dict:
        """Lấy cấu hình CORS cho kết nối WebSocket."""
        return {
            "allow_origins": allowed_origins,
            "allow_credentials": True,
            "allow_methods": ["GET", "OPTIONS"],
            "allow_headers": [
                "Accept",
                "Authorization",
                "Sec-WebSocket-Protocol",
                "Sec-WebSocket-Extensions",
            ],
            "expose_headers": [],
            "max_age": 86400,  # 24 giờ cho WebSocket
        }


def validate_cors_config(settings: Settings) -> List[str]:
    """Xác thực cấu hình CORS và trả về các vấn đề."""
    issues = []

    if not settings.cors_enabled:
        return issues

    # Kiểm tra nguồn gốc
    if not settings.cors_origins:
        issues.append("CORS đã bật nhưng không có nguồn gốc nào được cấu hình")

    # Kiểm tra ký tự đại diện trong môi trường sản xuất
    if settings.is_production and "*" in settings.cors_origins:
        issues.append("Nguồn gốc ký tự đại diện (*) không nên dùng trong môi trường sản xuất")

    # Xác thực định dạng nguồn gốc
    for origin in settings.cors_origins:
        if origin != "*" and not origin.startswith(("http://", "https://")):
            issues.append(f"Định dạng nguồn gốc không hợp lệ: {origin}")

    # Kiểm tra thông tin xác thực với ký tự đại diện
    if settings.cors_allow_credentials and "*" in settings.cors_origins:
        issues.append("Không thể sử dụng thông tin xác thực với nguồn gốc ký tự đại diện")

    return issues


def get_cors_headers_for_origin(origin: str, settings: Settings) -> dict:
    """Lấy header CORS phù hợp cho nguồn gốc cụ thể."""
    headers = {}

    if not settings.cors_enabled:
        return headers

    # Kiểm tra xem nguồn gốc có được phép không
    cors_middleware = CORSMiddleware(None, settings)
    if cors_middleware._is_origin_allowed(origin):
        headers["Access-Control-Allow-Origin"] = origin

        if settings.cors_allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

    return headers
