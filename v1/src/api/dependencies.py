"""
Tiêm phụ thuộc cho WiFi-DensePose API
"""

import logging
from typing import Optional, Dict, Any
from functools import lru_cache

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.config.settings import get_settings
from src.config.domains import get_domain_config
from src.services.pose_service import PoseService
from src.services.stream_service import StreamService
from src.services.hardware_service import HardwareService

logger = logging.getLogger(__name__)

# Sơ đồ bảo mật cho xác thực JWT
security = HTTPBearer(auto_error=False)


# Phụ thuộc dịch vụ
@lru_cache()
def get_pose_service() -> PoseService:
    """Lấy thể hiện dịch vụ tư thế."""
    settings = get_settings()
    domain_config = get_domain_config()

    return PoseService(
        settings=settings,
        domain_config=domain_config
    )


@lru_cache()
def get_stream_service() -> StreamService:
    """Lấy thể hiện dịch vụ truyền phát."""
    settings = get_settings()
    domain_config = get_domain_config()

    return StreamService(
        settings=settings,
        domain_config=domain_config
    )


@lru_cache()
def get_hardware_service() -> HardwareService:
    """Lấy thể hiện dịch vụ phần cứng."""
    settings = get_settings()
    domain_config = get_domain_config()

    return HardwareService(
        settings=settings,
        domain_config=domain_config
    )


# Phụ thuộc xác thực
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """Lấy người dùng đã xác thực hiện tại."""
    settings = get_settings()

    # Bỏ qua xác thực nếu đã tắt
    if not settings.enable_authentication:
        return None

    # Kiểm tra xem người dùng đã được thiết lập bởi middleware chưa
    if hasattr(request.state, 'user') and request.state.user:
        return request.state.user

    # Không có thông tin xác thực được cung cấp
    if not credentials:
        return None

    # Xác thực token JWT
    # Xác thực JWT phải được cấu hình qua cài đặt (ví dụ: JWT_SECRET, JWT_ALGORITHM)
    if settings.is_development:
        logger.warning(
            "Thông tin xác thực được cung cấp trong chế độ phát triển nhưng "
            "xác thực JWT chưa được cấu hình. Thiết lập xác thực JWT qua "
            "biến môi trường (JWT_SECRET, JWT_ALGORITHM) hoặc tắt "
            "xác thực. Đang từ chối yêu cầu."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Xác thực JWT chưa được cấu hình. Trong chế độ phát triển, "
                "hãy tắt xác thực (enable_authentication=False) hoặc cấu hình "
                "xác thực JWT. Trả về người dùng giả không được phép trong bất kỳ môi trường nào."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Trong môi trường sản xuất, triển khai xác thực JWT đúng cách
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Xác thực JWT chưa được cấu hình. Cấu hình biến môi trường "
            "JWT_SECRET và JWT_ALGORITHM, hoặc tích hợp nhà cung cấp danh tính "
            "bên ngoài. Xem docs/authentication.md để biết hướng dẫn thiết lập."
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_active_user(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> Dict[str, Any]:
    """Lấy người dùng hoạt động hiện tại (yêu cầu xác thực)."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Kiểm tra xem người dùng có hoạt động không
    if not current_user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Người dùng không hoạt động"
        )

    return current_user


async def get_admin_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """Lấy người dùng quản trị hiện tại (yêu cầu quyền quản trị)."""
    if not current_user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Yêu cầu quyền quản trị"
        )

    return current_user


# Phụ thuộc quyền hạn
def require_permission(permission: str):
    """Factory phụ thuộc cho kiểm tra quyền hạn."""

    async def check_permission(
        current_user: Dict[str, Any] = Depends(get_current_active_user)
    ) -> Dict[str, Any]:
        """Kiểm tra xem người dùng có quyền hạn yêu cầu không."""
        user_permissions = current_user.get("permissions", [])

        # Người dùng quản trị có tất cả quyền hạn
        if current_user.get("is_admin", False):
            return current_user

        # Kiểm tra quyền hạn cụ thể
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yêu cầu quyền hạn '{permission}'"
            )

        return current_user

    return check_permission


# Phụ thuộc truy cập khu vực
async def validate_zone_access(
    zone_id: str,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> str:
    """Xác thực quyền truy cập của người dùng vào khu vực cụ thể."""
    domain_config = get_domain_config()

    # Kiểm tra xem khu vực có tồn tại không
    zone = domain_config.get_zone(zone_id)
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy khu vực '{zone_id}'"
        )

    # Kiểm tra xem khu vực có được bật không
    if not zone.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Khu vực '{zone_id}' đã bị tắt"
        )

    # Nếu xác thực được bật, kiểm tra quyền truy cập người dùng
    if current_user:
        # Người dùng quản trị có quyền truy cập tất cả khu vực
        if current_user.get("is_admin", False):
            return zone_id

        # Kiểm tra quyền khu vực của người dùng
        user_zones = current_user.get("zones", [])
        if user_zones and zone_id not in user_zones:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bị từ chối truy cập khu vực '{zone_id}'"
            )

    return zone_id


# Phụ thuộc truy cập router
async def validate_router_access(
    router_id: str,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> str:
    """Xác thực quyền truy cập của người dùng vào router cụ thể."""
    domain_config = get_domain_config()

    # Kiểm tra xem router có tồn tại không
    router = domain_config.get_router(router_id)
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy router '{router_id}'"
        )

    # Kiểm tra xem router có được bật không
    if not router.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Router '{router_id}' đã bị tắt"
        )

    # Nếu xác thực được bật, kiểm tra quyền truy cập người dùng
    if current_user:
        # Người dùng quản trị có quyền truy cập tất cả router
        if current_user.get("is_admin", False):
            return router_id

        # Kiểm tra quyền router của người dùng
        user_routers = current_user.get("routers", [])
        if user_routers and router_id not in user_routers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bị từ chối truy cập router '{router_id}'"
            )

    return router_id


# Phụ thuộc sức khỏe dịch vụ
async def check_service_health(
    request: Request,
    service_name: str
) -> bool:
    """Kiểm tra xem dịch vụ có khỏe mạnh không."""
    try:
        if service_name == "pose":
            service = getattr(request.app.state, 'pose_service', None)
        elif service_name == "stream":
            service = getattr(request.app.state, 'stream_service', None)
        elif service_name == "hardware":
            service = getattr(request.app.state, 'hardware_service', None)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dịch vụ không xác định: {service_name}"
            )

        if not service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Dịch vụ '{service_name}' không khả dụng"
            )

        # Kiểm tra sức khỏe dịch vụ
        status_info = await service.get_status()
        if status_info.get("status") != "healthy":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Dịch vụ '{service_name}' không khỏe mạnh: {status_info.get('error', 'Lỗi không xác định')}"
            )

        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi kiểm tra sức khỏe dịch vụ {service_name}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Kiểm tra sức khỏe dịch vụ '{service_name}' thất bại"
        )


# Phụ thuộc giới hạn tốc độ
async def check_rate_limit(
    request: Request,
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user)
) -> bool:
    """Kiểm tra trạng thái giới hạn tốc độ."""
    settings = get_settings()

    # Bỏ qua nếu giới hạn tốc độ bị tắt
    if not settings.enable_rate_limiting:
        return True

    # Giới hạn tốc độ được xử lý bởi middleware
    # Phụ thuộc này có thể dùng cho các kiểm tra bổ sung
    return True


# Phụ thuộc cấu hình
def get_zone_config(zone_id: str = Depends(validate_zone_access)):
    """Lấy cấu hình khu vực."""
    domain_config = get_domain_config()
    return domain_config.get_zone(zone_id)


def get_router_config(router_id: str = Depends(validate_router_access)):
    """Lấy cấu hình router."""
    domain_config = get_domain_config()
    return domain_config.get_router(router_id)


# Phụ thuộc phân trang
class PaginationParams:
    """Tham số phân trang."""

    def __init__(
        self,
        page: int = 1,
        size: int = 20,
        max_size: int = 100
    ):
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Trang phải >= 1"
            )

        if size < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kích thước phải >= 1"
            )

        if size > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Kích thước phải <= {max_size}"
            )

        self.page = page
        self.size = size
        self.offset = (page - 1) * size
        self.limit = size


def get_pagination_params(
    page: int = 1,
    size: int = 20
) -> PaginationParams:
    """Lấy tham số phân trang."""
    return PaginationParams(page=page, size=size)


# Phụ thuộc bộ lọc truy vấn
class QueryFilters:
    """Bộ lọc truy vấn phổ biến."""

    def __init__(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        min_confidence: Optional[float] = None,
        activity: Optional[str] = None
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.min_confidence = min_confidence
        self.activity = activity

        # Xác thực độ tin cậy
        if min_confidence is not None:
            if not 0.0 <= min_confidence <= 1.0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="min_confidence phải nằm trong khoảng 0.0 đến 1.0"
                )


def get_query_filters(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    min_confidence: Optional[float] = None,
    activity: Optional[str] = None
) -> QueryFilters:
    """Lấy bộ lọc truy vấn."""
    return QueryFilters(
        start_time=start_time,
        end_time=end_time,
        min_confidence=min_confidence,
        activity=activity
    )


# Phụ thuộc WebSocket
async def get_websocket_user(
    websocket_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Lấy người dùng từ token WebSocket."""
    settings = get_settings()

    # Bỏ qua xác thực nếu đã tắt
    if not settings.enable_authentication:
        return None

    # Xác thực token WebSocket
    if not websocket_token:
        return None

    if settings.is_development:
        logger.warning(
            "Token WebSocket được cung cấp trong chế độ phát triển nhưng "
            "xác thực token chưa được cấu hình. Đang từ chối. Tắt xác thực hoặc "
            "cấu hình xác thực JWT để cho phép kết nối WebSocket."
        )
        return None

    # Xác thực token WebSocket yêu cầu khóa bí mật JWT và nhà phát hành đã cấu hình.
    # Cho đến khi cài đặt JWT được cung cấp qua biến môi trường
    # (JWT_SECRET_KEY, JWT_ALGORITHM), token sẽ bị từ chối để ngăn
    # truy cập trái phép. Cấu hình cài đặt xác thực và triển khai
    # xác minh token ở đây sử dụng cùng logic như get_current_user().
    logger.warning("Xác thực token WebSocket yêu cầu cấu hình JWT. Đang từ chối token.")
    return None


async def get_current_user_ws(
    websocket_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Lấy người dùng hiện tại cho kết nối WebSocket."""
    return await get_websocket_user(websocket_token)


# Phụ thuộc yêu cầu xác thực
async def require_auth(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """Yêu cầu xác thực để truy cập endpoint."""
    return current_user


# Phụ thuộc môi trường phát triển
async def development_only():
    """Phụ thuộc chỉ cho phép truy cập trong môi trường phát triển."""
    settings = get_settings()

    if not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint không khả dụng trong môi trường sản xuất"
        )

    return True
