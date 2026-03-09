"""
Middleware xác thực cho WiFi-DensePose API
"""

import logging
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timedelta

from fastapi import Request, Response, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config.settings import Settings
from src.logger import set_request_context

logger = logging.getLogger(__name__)

# Băm mật khẩu
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Trình xử lý token JWT
security = HTTPBearer(auto_error=False)


class AuthenticationError(Exception):
    """Lỗi xác thực."""
    pass


class AuthorizationError(Exception):
    """Lỗi phân quyền."""
    pass


class TokenManager:
    """Quản lý token JWT."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.secret_key = settings.secret_key
        self.algorithm = settings.jwt_algorithm
        self.expire_hours = settings.jwt_expire_hours

    def create_access_token(self, data: Dict[str, Any]) -> str:
        """Tạo token truy cập JWT."""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(hours=self.expire_hours)
        to_encode.update({"exp": expire, "iat": datetime.utcnow()})

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Xác minh và giải mã token JWT."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except JWTError as e:
            logger.warning(f"Xác minh JWT thất bại: {e}")
            raise AuthenticationError("Token không hợp lệ")

    def decode_token_claims(self, token: str) -> Optional[Dict[str, Any]]:
        """Giải mã và xác minh token, trả về các claim.

        Khác với triển khai trước, phương thức này luôn xác minh
        chữ ký token. Sử dụng verify_token() để xác thực đầy đủ
        bao gồm kiểm tra hết hạn; trình trợ giúp này chỉ được cung cấp
        để kiểm tra claim từ token đã được xác minh.
        """
        try:
            return jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            return None


class UserManager:
    """Quản lý người dùng cho xác thực."""

    def __init__(self):
        # Trong ứng dụng thực, đây sẽ kết nối đến cơ sở dữ liệu.
        # Không tạo người dùng mặc định -- người dùng phải được cấp phát
        # thông qua phương thức create_user() hoặc nhà cung cấp danh tính bên ngoài.
        self._users: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def hash_password(password: str) -> str:
        """Băm mật khẩu."""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Xác minh mật khẩu với bản băm."""
        return pwd_context.verify(plain_password, hashed_password)

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Lấy người dùng theo tên đăng nhập."""
        return self._users.get(username)

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Xác thực người dùng bằng tên đăng nhập và mật khẩu."""
        user = self.get_user(username)
        if not user:
            return None

        if not self.verify_password(password, user["hashed_password"]):
            return None

        if not user.get("is_active", False):
            return None

        return user

    def create_user(self, username: str, email: str, password: str, roles: list = None) -> Dict[str, Any]:
        """Tạo người dùng mới."""
        if username in self._users:
            raise ValueError("Người dùng đã tồn tại")

        user = {
            "username": username,
            "email": email,
            "hashed_password": self.hash_password(password),
            "roles": roles or ["user"],
            "is_active": True,
            "created_at": datetime.utcnow(),
        }

        self._users[username] = user
        return user

    def update_user(self, username: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Cập nhật thông tin người dùng."""
        user = self._users.get(username)
        if not user:
            return None

        # Không cho phép cập nhật một số trường nhất định
        protected_fields = {"username", "created_at", "hashed_password"}
        updates = {k: v for k, v in updates.items() if k not in protected_fields}

        user.update(updates)
        return user

    def deactivate_user(self, username: str) -> bool:
        """Vô hiệu hóa người dùng."""
        user = self._users.get(username)
        if user:
            user["is_active"] = False
            return True
        return False


class AuthenticationMiddleware:
    """Middleware xác thực cho FastAPI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.token_manager = TokenManager(settings)
        self.user_manager = UserManager()
        self.enabled = settings.enable_authentication

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Xử lý yêu cầu qua middleware xác thực."""
        start_time = time.time()

        try:
            # Bỏ qua xác thực cho một số đường dẫn nhất định
            if self._should_skip_auth(request):
                response = await call_next(request)
                return response

            # Bỏ qua nếu xác thực bị tắt
            if not self.enabled:
                response = await call_next(request)
                return response

            # Trích xuất và xác minh token
            user_info = await self._authenticate_request(request)

            # Đặt ngữ cảnh người dùng
            if user_info:
                request.state.user = user_info
                set_request_context(user_id=user_info.get("username"))

            # Xử lý yêu cầu
            response = await call_next(request)

            # Thêm header xác thực
            self._add_auth_headers(response, user_info)

            return response

        except AuthenticationError as e:
            logger.warning(f"Xác thực thất bại: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )
        except AuthorizationError as e:
            logger.warning(f"Phân quyền thất bại: {e}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )
        except Exception as e:
            logger.error(f"Lỗi middleware xác thực: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Lỗi dịch vụ xác thực",
            )
        finally:
            # Ghi log thời gian xử lý yêu cầu
            processing_time = time.time() - start_time
            logger.debug(f"Thời gian xử lý middleware xác thực: {processing_time:.3f}s")

    def _should_skip_auth(self, request: Request) -> bool:
        """Kiểm tra xem có nên bỏ qua xác thực cho yêu cầu này không."""
        path = request.url.path

        # Bỏ qua xác thực cho các đường dẫn sau
        skip_paths = [
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/auth/login",
            "/auth/register",
            "/static",
        ]

        return any(path.startswith(skip_path) for skip_path in skip_paths)

    async def _authenticate_request(self, request: Request) -> Optional[Dict[str, Any]]:
        """Xác thực yêu cầu và trả về thông tin người dùng."""
        # Thử lấy token từ header Authorization
        authorization = request.headers.get("Authorization")
        if not authorization:
            # Đối với kết nối WebSocket, thử lấy token từ tham số truy vấn
            if request.url.path.startswith("/ws"):
                token = request.query_params.get("token")
                if token:
                    authorization = f"Bearer {token}"

        if not authorization:
            if self._requires_auth(request):
                raise AuthenticationError("Thiếu header xác thực")
            return None

        # Trích xuất token
        try:
            scheme, token = authorization.split()
            if scheme.lower() != "bearer":
                raise AuthenticationError("Phương thức xác thực không hợp lệ")
        except ValueError:
            raise AuthenticationError("Định dạng header xác thực không hợp lệ")

        # Xác minh token
        try:
            payload = self.token_manager.verify_token(token)
            username = payload.get("sub")
            if not username:
                raise AuthenticationError("Payload token không hợp lệ")

            # Lấy thông tin người dùng
            user = self.user_manager.get_user(username)
            if not user:
                raise AuthenticationError("Không tìm thấy người dùng")

            if not user.get("is_active", False):
                raise AuthenticationError("Tài khoản người dùng đã bị vô hiệu hóa")

            # Trả về thông tin người dùng không có dữ liệu nhạy cảm
            return {
                "username": user["username"],
                "email": user["email"],
                "roles": user["roles"],
                "is_active": user["is_active"],
            }

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Lỗi xác minh token: {e}")
            raise AuthenticationError("Xác minh token thất bại")

    def _requires_auth(self, request: Request) -> bool:
        """Kiểm tra xem yêu cầu có cần xác thực không."""
        # Tất cả endpoint API yêu cầu xác thực theo mặc định
        path = request.url.path
        return path.startswith("/api/") or path.startswith("/ws/")

    def _add_auth_headers(self, response: Response, user_info: Optional[Dict[str, Any]]):
        """Thêm header liên quan đến xác thực vào phản hồi."""
        if user_info:
            response.headers["X-User"] = user_info["username"]
            response.headers["X-User-Roles"] = ",".join(user_info["roles"])

    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """Xác thực người dùng và trả về token."""
        user = self.user_manager.authenticate_user(username, password)
        if not user:
            raise AuthenticationError("Tên đăng nhập hoặc mật khẩu không hợp lệ")

        # Tạo token
        token_data = {
            "sub": user["username"],
            "email": user["email"],
            "roles": user["roles"],
        }

        access_token = self.token_manager.create_access_token(token_data)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": self.settings.jwt_expire_hours * 3600,
            "user": {
                "username": user["username"],
                "email": user["email"],
                "roles": user["roles"],
            }
        }

    async def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """Đăng ký người dùng mới."""
        try:
            user = self.user_manager.create_user(username, email, password)

            # Tạo token cho người dùng mới
            token_data = {
                "sub": user["username"],
                "email": user["email"],
                "roles": user["roles"],
            }

            access_token = self.token_manager.create_access_token(token_data)

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": self.settings.jwt_expire_hours * 3600,
                "user": {
                    "username": user["username"],
                    "email": user["email"],
                    "roles": user["roles"],
                }
            }

        except ValueError as e:
            raise AuthenticationError(str(e))

    async def refresh_token(self, token: str) -> Dict[str, Any]:
        """Làm mới token truy cập."""
        try:
            payload = self.token_manager.verify_token(token)
            username = payload.get("sub")

            user = self.user_manager.get_user(username)
            if not user or not user.get("is_active", False):
                raise AuthenticationError("Không tìm thấy người dùng hoặc tài khoản không hoạt động")

            # Tạo token mới
            token_data = {
                "sub": user["username"],
                "email": user["email"],
                "roles": user["roles"],
            }

            new_token = self.token_manager.create_access_token(token_data)

            return {
                "access_token": new_token,
                "token_type": "bearer",
                "expires_in": self.settings.jwt_expire_hours * 3600,
            }

        except Exception as e:
            raise AuthenticationError("Làm mới token thất bại")

    def check_permission(self, user_info: Dict[str, Any], required_role: str) -> bool:
        """Kiểm tra xem người dùng có vai trò/quyền cần thiết không."""
        user_roles = user_info.get("roles", [])

        # Vai trò admin có tất cả quyền
        if "admin" in user_roles:
            return True

        # Kiểm tra vai trò cụ thể
        return required_role in user_roles

    def require_role(self, required_role: str):
        """Decorator yêu cầu vai trò cụ thể."""
        def decorator(func):
            import functools

            @functools.wraps(func)
            async def wrapper(request: Request, *args, **kwargs):
                user_info = getattr(request.state, "user", None)
                if not user_info:
                    raise AuthorizationError("Yêu cầu xác thực")

                if not self.check_permission(user_info, required_role):
                    raise AuthorizationError(f"Yêu cầu vai trò '{required_role}'")

                return await func(request, *args, **kwargs)

            return wrapper
        return decorator


# Thể hiện middleware xác thực toàn cục
_auth_middleware: Optional[AuthenticationMiddleware] = None


def get_auth_middleware(settings: Settings) -> AuthenticationMiddleware:
    """Lấy thể hiện middleware xác thực."""
    global _auth_middleware
    if _auth_middleware is None:
        _auth_middleware = AuthenticationMiddleware(settings)
    return _auth_middleware


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Lấy người dùng đã xác thực hiện tại từ yêu cầu."""
    return getattr(request.state, "user", None)


def require_authentication(request: Request) -> Dict[str, Any]:
    """Yêu cầu xác thực và trả về thông tin người dùng."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(role: str):
    """Dependency yêu cầu vai trò cụ thể."""
    def dependency(request: Request) -> Dict[str, Any]:
        user = require_authentication(request)

        auth_middleware = get_auth_middleware(request.app.state.settings)
        if not auth_middleware.check_permission(user, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yêu cầu vai trò '{role}'",
            )

        return user

    return dependency
