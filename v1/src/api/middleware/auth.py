"""
Middleware xác thực JWT cho WiFi-DensePose API
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware xác thực JWT."""

    def __init__(self, app):
        super().__init__(app)
        self.settings = get_settings()

        # Các đường dẫn không yêu cầu xác thực
        self.public_paths = {
            "/",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
            "/ready",
            "/live",
            "/version",
            "/metrics"
        }

        # Các đường dẫn yêu cầu xác thực
        self.protected_paths = {
            "/api/v1/pose/analyze",
            "/api/v1/pose/calibrate",
            "/api/v1/pose/historical",
            "/api/v1/stream/start",
            "/api/v1/stream/stop",
            "/api/v1/stream/clients",
            "/api/v1/stream/broadcast"
        }

    async def dispatch(self, request: Request, call_next):
        """Xử lý yêu cầu qua middleware xác thực."""

        # Bỏ qua xác thực cho đường dẫn công khai
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Trích xuất và xác thực token
        token = self._extract_token(request)

        if token:
            try:
                # Xác minh token và thêm thông tin người dùng vào trạng thái yêu cầu
                user_data = await self._verify_token(token)
                request.state.user = user_data
                request.state.authenticated = True

                logger.debug(f"Đã xác thực người dùng: {user_data.get('id')}")

            except Exception as e:
                logger.warning(f"Xác thực token thất bại: {e}")

                # Với đường dẫn được bảo vệ, trả về 401
                if self._is_protected_path(request.url.path):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": {
                                "code": 401,
                                "message": "Token không hợp lệ hoặc đã hết hạn",
                                "type": "authentication_error"
                            }
                        }
                    )

                # Với các đường dẫn khác, tiếp tục không có xác thực
                request.state.user = None
                request.state.authenticated = False
        else:
            # Không có token được cung cấp
            if self._is_protected_path(request.url.path):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": 401,
                            "message": "Yêu cầu xác thực",
                            "type": "authentication_error"
                        }
                    },
                    headers={"WWW-Authenticate": "Bearer"}
                )

            request.state.user = None
            request.state.authenticated = False

        # Tiếp tục xử lý yêu cầu
        response = await call_next(request)

        # Thêm tiêu đề xác thực vào phản hồi
        if hasattr(request.state, 'user') and request.state.user:
            response.headers["X-User-ID"] = request.state.user.get("id", "")
            response.headers["X-Authenticated"] = "true"
        else:
            response.headers["X-Authenticated"] = "false"

        return response

    def _is_public_path(self, path: str) -> bool:
        """Kiểm tra xem đường dẫn có công khai không (không yêu cầu xác thực)."""
        # Khớp chính xác
        if path in self.public_paths:
            return True

        # Khớp mẫu cho đường dẫn công khai
        public_patterns = [
            "/health",
            "/metrics",
            "/api/v1/pose/current",  # Cho phép truy cập ẩn danh vào dữ liệu tư thế hiện tại
            "/api/v1/pose/zones/",   # Cho phép truy cập ẩn danh vào dữ liệu khu vực
            "/api/v1/pose/activities",  # Cho phép truy cập ẩn danh vào hoạt động
            "/api/v1/pose/stats",    # Cho phép truy cập ẩn danh vào thống kê
            "/api/v1/stream/status"  # Cho phép truy cập ẩn danh vào trạng thái luồng
        ]

        for pattern in public_patterns:
            if path.startswith(pattern):
                return True

        return False

    def _is_protected_path(self, path: str) -> bool:
        """Kiểm tra xem đường dẫn có yêu cầu xác thực không."""
        # Khớp chính xác
        if path in self.protected_paths:
            return True

        # Khớp mẫu cho đường dẫn được bảo vệ
        protected_patterns = [
            "/api/v1/pose/analyze",
            "/api/v1/pose/calibrate",
            "/api/v1/pose/historical",
            "/api/v1/stream/start",
            "/api/v1/stream/stop",
            "/api/v1/stream/clients",
            "/api/v1/stream/broadcast"
        ]

        for pattern in protected_patterns:
            if path.startswith(pattern):
                return True

        return False

    def _extract_token(self, request: Request) -> Optional[str]:
        """Trích xuất token JWT từ yêu cầu."""
        # Kiểm tra tiêu đề Authorization
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]

        # Kiểm tra tham số truy vấn (cho kết nối WebSocket)
        token = request.query_params.get("token")
        if token:
            return token

        # Kiểm tra cookie
        token = request.cookies.get("access_token")
        if token:
            return token

        return None

    async def _verify_token(self, token: str) -> Dict[str, Any]:
        """Xác minh token JWT và trả về dữ liệu người dùng."""
        try:
            # Giải mã token JWT
            payload = jwt.decode(
                token,
                self.settings.secret_key,
                algorithms=[self.settings.jwt_algorithm]
            )

            # Trích xuất thông tin người dùng
            user_id = payload.get("sub")
            if not user_id:
                raise ValueError("Token thiếu ID người dùng")

            # Kiểm tra hết hạn token
            exp = payload.get("exp")
            if exp and datetime.utcnow() > datetime.fromtimestamp(exp):
                raise ValueError("Token đã hết hạn")

            # Xây dựng đối tượng người dùng
            user_data = {
                "id": user_id,
                "username": payload.get("username"),
                "email": payload.get("email"),
                "is_admin": payload.get("is_admin", False),
                "permissions": payload.get("permissions", []),
                "accessible_zones": payload.get("accessible_zones", []),
                "token_issued_at": payload.get("iat"),
                "token_expires_at": payload.get("exp"),
                "session_id": payload.get("session_id")
            }

            return user_data

        except JWTError as e:
            raise ValueError(f"Xác thực JWT thất bại: {e}")
        except Exception as e:
            raise ValueError(f"Lỗi xác minh token: {e}")

    # TODO: Kết nối ghi log sự kiện xác thực trong dispatch() để
    # giám sát bảo mật (đăng nhập thất bại, hết hạn token, v.v.).


class TokenBlacklist:
    """Danh sách đen token trong bộ nhớ đơn giản cho chức năng đăng xuất."""

    def __init__(self):
        self._blacklisted_tokens = set()
        self._cleanup_interval = 3600  # 1 giờ
        self._last_cleanup = datetime.utcnow()

    def add_token(self, token: str):
        """Thêm token vào danh sách đen."""
        self._blacklisted_tokens.add(token)
        self._cleanup_if_needed()

    def is_blacklisted(self, token: str) -> bool:
        """Kiểm tra xem token có trong danh sách đen không."""
        self._cleanup_if_needed()
        return token in self._blacklisted_tokens

    def _cleanup_if_needed(self):
        """Dọn dẹp token đã hết hạn khỏi danh sách đen."""
        now = datetime.utcnow()
        if (now - self._last_cleanup).total_seconds() > self._cleanup_interval:
            # Trong triển khai thực tế, bạn sẽ kiểm tra hết hạn token
            # Hiện tại, chúng ta chỉ xóa token cũ định kỳ
            self._blacklisted_tokens.clear()
            self._last_cleanup = now


# Thể hiện toàn cục danh sách đen token
token_blacklist = TokenBlacklist()


class SecurityHeaders:
    """Tiêu đề bảo mật cho phản hồi API."""

    @staticmethod
    def add_security_headers(response: Response) -> Response:
        """Thêm tiêu đề bảo mật vào phản hồi."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:;"
        )

        return response


class APIKeyAuth:
    """Xác thực khóa API thay thế cho giao tiếp giữa các dịch vụ."""

    def __init__(self, api_keys: Dict[str, Dict[str, Any]] = None):
        self.api_keys = api_keys or {}

    def verify_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Xác minh khóa API và trả về thông tin dịch vụ liên kết."""
        if api_key in self.api_keys:
            return self.api_keys[api_key]
        return None

    def add_api_key(self, api_key: str, service_info: Dict[str, Any]):
        """Thêm khóa API mới."""
        self.api_keys[api_key] = service_info

    def revoke_api_key(self, api_key: str):
        """Thu hồi khóa API."""
        if api_key in self.api_keys:
            del self.api_keys[api_key]


# Thể hiện toàn cục xác thực khóa API
api_key_auth = APIKeyAuth()
