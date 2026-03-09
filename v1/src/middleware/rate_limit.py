"""
Middleware giới hạn tốc độ cho WiFi-DensePose API
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Callable, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request, Response, HTTPException, status
from starlette.types import ASGIApp

from src.config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class RateLimitInfo:
    """Thông tin giới hạn tốc độ."""
    requests: int
    window_start: float
    window_size: int
    limit: int

    @property
    def remaining(self) -> int:
        """Lấy số yêu cầu còn lại trong cửa sổ hiện tại."""
        return max(0, self.limit - self.requests)

    @property
    def reset_time(self) -> float:
        """Lấy thời gian khi cửa sổ được đặt lại."""
        return self.window_start + self.window_size

    @property
    def is_exceeded(self) -> bool:
        """Kiểm tra xem giới hạn tốc độ có bị vượt quá không."""
        return self.requests >= self.limit


class TokenBucket:
    """Thuật toán nhóm token cho giới hạn tốc độ."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """Thử tiêu thụ token từ nhóm."""
        async with self._lock:
            now = time.time()

            # Nạp lại token dựa trên thời gian đã trôi qua
            time_passed = now - self.last_refill
            tokens_to_add = time_passed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now

            # Kiểm tra xem có đủ token không
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    def get_info(self) -> Dict[str, Any]:
        """Lấy thông tin nhóm token."""
        return {
            "capacity": self.capacity,
            "tokens": self.tokens,
            "refill_rate": self.refill_rate,
            "last_refill": self.last_refill
        }


class SlidingWindowCounter:
    """Bộ đếm cửa sổ trượt cho giới hạn tốc độ."""

    def __init__(self, window_size: int, limit: int):
        self.window_size = window_size
        self.limit = limit
        self.requests = deque()
        self._lock = asyncio.Lock()

    async def is_allowed(self) -> Tuple[bool, RateLimitInfo]:
        """Kiểm tra xem yêu cầu có được phép không."""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_size

            # Loại bỏ các yêu cầu cũ ngoài cửa sổ
            while self.requests and self.requests[0] < window_start:
                self.requests.popleft()

            # Kiểm tra xem giới hạn có bị vượt quá không
            current_requests = len(self.requests)
            allowed = current_requests < self.limit

            if allowed:
                self.requests.append(now)

            rate_limit_info = RateLimitInfo(
                requests=current_requests + (1 if allowed else 0),
                window_start=window_start,
                window_size=self.window_size,
                limit=self.limit
            )

            return allowed, rate_limit_info


class RateLimiter:
    """Bộ giới hạn tốc độ với nhiều thuật toán."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = settings.enable_rate_limiting

        # Cấu hình giới hạn tốc độ
        self.default_limit = settings.rate_limit_requests
        self.authenticated_limit = settings.rate_limit_authenticated_requests
        self.window_size = settings.rate_limit_window

        # Lưu trữ dữ liệu giới hạn tốc độ
        self._sliding_windows: Dict[str, SlidingWindowCounter] = {}
        self._token_buckets: Dict[str, TokenBucket] = {}

        # Tác vụ dọn dẹp
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 300  # 5 phút

    async def start(self):
        """Khởi động các tác vụ nền của bộ giới hạn tốc độ."""
        if self.enabled:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Đã khởi động bộ giới hạn tốc độ")

    async def stop(self):
        """Dừng các tác vụ nền của bộ giới hạn tốc độ."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Đã dừng bộ giới hạn tốc độ")

    async def _cleanup_loop(self):
        """Tác vụ nền dọn dẹp dữ liệu giới hạn tốc độ cũ."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_old_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Lỗi trong quá trình dọn dẹp bộ giới hạn tốc độ: {e}")

    async def _cleanup_old_data(self):
        """Xóa dữ liệu giới hạn tốc độ cũ."""
        now = time.time()
        cutoff = now - (self.window_size * 2)  # Giữ dữ liệu trong 2 cửa sổ

        # Dọn dẹp cửa sổ trượt
        keys_to_remove = []
        for key, window in self._sliding_windows.items():
            # Loại bỏ yêu cầu cũ
            while window.requests and window.requests[0] < cutoff:
                window.requests.popleft()

            # Loại bỏ cửa sổ rỗng
            if not window.requests:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._sliding_windows[key]

        logger.debug(f"Đã dọn dẹp {len(keys_to_remove)} cửa sổ giới hạn tốc độ cũ")

    def _get_client_identifier(self, request: Request) -> str:
        """Lấy định danh máy khách cho giới hạn tốc độ."""
        # Thử lấy ID người dùng từ yêu cầu đã xác thực
        user = getattr(request.state, "user", None)
        if user:
            return f"user:{user.get('username', 'unknown')}"

        # Quay về sử dụng địa chỉ IP
        client_ip = self._get_client_ip(request)
        return f"ip:{client_ip}"

    def _get_client_ip(self, request: Request) -> str:
        """Lấy địa chỉ IP máy khách."""
        # Kiểm tra tiêu đề chuyển tiếp
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Quay về kết nối trực tiếp
        return request.client.host if request.client else "unknown"

    def _get_rate_limit(self, request: Request) -> int:
        """Lấy giới hạn tốc độ cho yêu cầu."""
        # Kiểm tra xem người dùng đã xác thực chưa
        user = getattr(request.state, "user", None)
        if user:
            return self.authenticated_limit

        return self.default_limit

    def _get_rate_limit_key(self, request: Request) -> str:
        """Lấy khóa giới hạn tốc độ cho yêu cầu."""
        client_id = self._get_client_identifier(request)
        endpoint = f"{request.method}:{request.url.path}"
        return f"{client_id}:{endpoint}"

    async def check_rate_limit(self, request: Request) -> Tuple[bool, RateLimitInfo]:
        """Kiểm tra xem yêu cầu có nằm trong giới hạn tốc độ không."""
        if not self.enabled:
            # Trả về thông tin giả khi giới hạn tốc độ bị tắt
            return True, RateLimitInfo(
                requests=0,
                window_start=time.time(),
                window_size=self.window_size,
                limit=float('inf')
            )

        key = self._get_rate_limit_key(request)
        limit = self._get_rate_limit(request)

        # Lấy hoặc tạo bộ đếm cửa sổ trượt
        if key not in self._sliding_windows:
            self._sliding_windows[key] = SlidingWindowCounter(self.window_size, limit)

        window = self._sliding_windows[key]

        # Cập nhật giới hạn nếu thay đổi (ví dụ: người dùng đã xác thực)
        window.limit = limit

        return await window.is_allowed()

    async def check_token_bucket(self, request: Request, tokens: int = 1) -> bool:
        """Kiểm tra giới hạn tốc độ bằng thuật toán nhóm token."""
        if not self.enabled:
            return True

        key = self._get_client_identifier(request)
        limit = self._get_rate_limit(request)

        # Lấy hoặc tạo nhóm token
        if key not in self._token_buckets:
            # Tốc độ nạp lại: giới hạn trên kích thước cửa sổ
            refill_rate = limit / self.window_size
            self._token_buckets[key] = TokenBucket(limit, refill_rate)

        bucket = self._token_buckets[key]
        return await bucket.consume(tokens)

    def get_rate_limit_headers(self, rate_limit_info: RateLimitInfo) -> Dict[str, str]:
        """Lấy tiêu đề giới hạn tốc độ cho phản hồi."""
        return {
            "X-RateLimit-Limit": str(rate_limit_info.limit),
            "X-RateLimit-Remaining": str(rate_limit_info.remaining),
            "X-RateLimit-Reset": str(int(rate_limit_info.reset_time)),
            "X-RateLimit-Window": str(rate_limit_info.window_size),
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê bộ giới hạn tốc độ."""
        return {
            "enabled": self.enabled,
            "default_limit": self.default_limit,
            "authenticated_limit": self.authenticated_limit,
            "window_size": self.window_size,
            "active_windows": len(self._sliding_windows),
            "active_buckets": len(self._token_buckets),
        }


class RateLimitMiddleware:
    """Middleware giới hạn tốc độ cho FastAPI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.rate_limiter = RateLimiter(settings)
        self.enabled = settings.enable_rate_limiting

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Xử lý yêu cầu qua middleware giới hạn tốc độ."""
        if not self.enabled:
            return await call_next(request)

        # Bỏ qua giới hạn tốc độ cho một số đường dẫn nhất định
        if self._should_skip_rate_limit(request):
            return await call_next(request)

        try:
            # Kiểm tra giới hạn tốc độ
            allowed, rate_limit_info = await self.rate_limiter.check_rate_limit(request)

            if not allowed:
                # Giới hạn tốc độ bị vượt quá
                logger.warning(
                    f"Giới hạn tốc độ bị vượt quá cho {self.rate_limiter._get_client_identifier(request)} "
                    f"tại {request.method} {request.url.path}"
                )

                headers = self.rate_limiter.get_rate_limit_headers(rate_limit_info)
                headers["Retry-After"] = str(int(rate_limit_info.reset_time - time.time()))

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Giới hạn tốc độ bị vượt quá",
                    headers=headers
                )

            # Xử lý yêu cầu
            response = await call_next(request)

            # Thêm tiêu đề giới hạn tốc độ vào phản hồi
            headers = self.rate_limiter.get_rate_limit_headers(rate_limit_info)
            for key, value in headers.items():
                response.headers[key] = value

            return response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Lỗi middleware giới hạn tốc độ: {e}")
            # Tiếp tục mà không giới hạn tốc độ khi gặp lỗi
            return await call_next(request)

    def _should_skip_rate_limit(self, request: Request) -> bool:
        """Kiểm tra xem có nên bỏ qua giới hạn tốc độ cho yêu cầu này không."""
        path = request.url.path

        # Bỏ qua giới hạn tốc độ cho các đường dẫn này
        skip_paths = [
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/static",
        ]

        return any(path.startswith(skip_path) for skip_path in skip_paths)

    async def start(self):
        """Khởi động middleware giới hạn tốc độ."""
        await self.rate_limiter.start()

    async def stop(self):
        """Dừng middleware giới hạn tốc độ."""
        await self.rate_limiter.stop()


# Thể hiện toàn cục của middleware giới hạn tốc độ
_rate_limit_middleware: Optional[RateLimitMiddleware] = None


def get_rate_limit_middleware(settings: Settings) -> RateLimitMiddleware:
    """Lấy thể hiện middleware giới hạn tốc độ."""
    global _rate_limit_middleware
    if _rate_limit_middleware is None:
        _rate_limit_middleware = RateLimitMiddleware(settings)
    return _rate_limit_middleware


def setup_rate_limiting(app: ASGIApp, settings: Settings) -> ASGIApp:
    """Thiết lập middleware giới hạn tốc độ cho ứng dụng."""
    if settings.enable_rate_limiting:
        logger.info("Đang thiết lập middleware giới hạn tốc độ")

        middleware = get_rate_limit_middleware(settings)

        # Thêm middleware vào ứng dụng
        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            return await middleware(request, call_next)

        logger.info(
            f"Đã bật giới hạn tốc độ - Mặc định: {settings.rate_limit_requests}/"
            f"{settings.rate_limit_window}s, Đã xác thực: "
            f"{settings.rate_limit_authenticated_requests}/{settings.rate_limit_window}s"
        )
    else:
        logger.info("Giới hạn tốc độ đã bị tắt")

    return app


class RateLimitConfig:
    """Trợ giúp cấu hình giới hạn tốc độ."""

    @staticmethod
    def development_config() -> dict:
        """Lấy cấu hình giới hạn tốc độ cho môi trường phát triển."""
        return {
            "enable_rate_limiting": False,  # Tắt trong môi trường phát triển
            "rate_limit_requests": 1000,
            "rate_limit_authenticated_requests": 5000,
            "rate_limit_window": 3600,  # 1 giờ
        }

    @staticmethod
    def production_config() -> dict:
        """Lấy cấu hình giới hạn tốc độ cho môi trường sản xuất."""
        return {
            "enable_rate_limiting": True,
            "rate_limit_requests": 100,  # 100 yêu cầu mỗi giờ cho chưa xác thực
            "rate_limit_authenticated_requests": 1000,  # 1000 yêu cầu mỗi giờ cho đã xác thực
            "rate_limit_window": 3600,  # 1 giờ
        }

    @staticmethod
    def api_config() -> dict:
        """Lấy cấu hình giới hạn tốc độ cho truy cập API."""
        return {
            "enable_rate_limiting": True,
            "rate_limit_requests": 60,  # 60 yêu cầu mỗi phút
            "rate_limit_authenticated_requests": 300,  # 300 yêu cầu mỗi phút
            "rate_limit_window": 60,  # 1 phút
        }

    @staticmethod
    def strict_config() -> dict:
        """Lấy cấu hình giới hạn tốc độ nghiêm ngặt."""
        return {
            "enable_rate_limiting": True,
            "rate_limit_requests": 10,  # 10 yêu cầu mỗi phút
            "rate_limit_authenticated_requests": 100,  # 100 yêu cầu mỗi phút
            "rate_limit_window": 60,  # 1 phút
        }


def validate_rate_limit_config(settings: Settings) -> list:
    """Xác thực cấu hình giới hạn tốc độ."""
    issues = []

    if settings.enable_rate_limiting:
        if settings.rate_limit_requests <= 0:
            issues.append("Số yêu cầu giới hạn tốc độ phải là số dương")

        if settings.rate_limit_authenticated_requests <= 0:
            issues.append("Số yêu cầu giới hạn tốc độ đã xác thực phải là số dương")

        if settings.rate_limit_window <= 0:
            issues.append("Cửa sổ giới hạn tốc độ phải là số dương")

        if settings.rate_limit_authenticated_requests < settings.rate_limit_requests:
            issues.append("Giới hạn tốc độ đã xác thực nên cao hơn giới hạn tốc độ mặc định")

    return issues
