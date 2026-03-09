"""
Gói WiFi-DensePose API
==========================

Hệ thống toàn diện cho ước lượng tư thế con người dựa trên WiFi sử dụng dữ liệu CSI
và mạng nơ-ron DensePose.

Gói này cung cấp:
- Thu thập dữ liệu CSI thời gian thực từ router WiFi
- Xử lý tín hiệu nâng cao và làm sạch pha
- Tích hợp mạng nơ-ron DensePose để ước lượng tư thế
- API RESTful để truy cập dữ liệu và điều khiển
- Quản lý tác vụ nền để xử lý dữ liệu
- Giám sát và ghi log toàn diện

Ví dụ sử dụng:
    >>> from src.app import app
    >>> from src.config.settings import get_settings
    >>>
    >>> settings = get_settings()
    >>> # Chạy với: uvicorn src.app:app --host 0.0.0.0 --port 8000

Sử dụng CLI:
    $ wifi-densepose start --host 0.0.0.0 --port 8000
    $ wifi-densepose status
    $ wifi-densepose stop

Tác giả: Đội WiFi-DensePose
Giấy phép: MIT
"""

__version__ = "1.1.0"
__author__ = "WiFi-DensePose Team"
__email__ = "team@wifi-densepose.com"
__license__ = "MIT"
__copyright__ = "Copyright 2024 WiFi-DensePose Team"

# Siêu dữ liệu gói
__title__ = "wifi-densepose"
__description__ = "Ước lượng tư thế con người dựa trên WiFi sử dụng dữ liệu CSI và mạng nơ-ron DensePose"
__url__ = "https://github.com/wifi-densepose/wifi-densepose"
__download_url__ = "https://github.com/wifi-densepose/wifi-densepose/archive/main.zip"

# Tuple thông tin phiên bản
__version_info__ = tuple(int(x) for x in __version__.split('.'))

# Import các thành phần chính để truy cập dễ dàng
try:
    from src.app import app
    from src.config.settings import get_settings, Settings
    from src.logger import setup_logging, get_logger

    # Thành phần cốt lõi
    from src.core.csi_processor import CSIProcessor
    from src.core.phase_sanitizer import PhaseSanitizer
    from src.core.pose_estimator import PoseEstimator
    from src.core.router_interface import RouterInterface

    # Dịch vụ
    from src.services.orchestrator import ServiceOrchestrator
    from src.services.health_check import HealthCheckService
    from src.services.metrics import MetricsService

    # Cơ sở dữ liệu
    from src.database.connection import get_database_manager
    from src.database.models import (
        Device, Session, CSIData, PoseDetection,
        SystemMetric, AuditLog
    )

    __all__ = [
        # Ứng dụng cốt lõi
        'app',
        'get_settings',
        'Settings',
        'setup_logging',
        'get_logger',

        # Xử lý cốt lõi
        'CSIProcessor',
        'PhaseSanitizer',
        'PoseEstimator',
        'RouterInterface',

        # Dịch vụ
        'ServiceOrchestrator',
        'HealthCheckService',
        'MetricsService',

        # Cơ sở dữ liệu
        'get_database_manager',
        'Device',
        'Session',
        'CSIData',
        'PoseDetection',
        'SystemMetric',
        'AuditLog',

        # Siêu dữ liệu
        '__version__',
        '__version_info__',
        '__author__',
        '__email__',
        '__license__',
        '__copyright__',
    ]

except ImportError as e:
    # Xử lý lỗi import một cách nhẹ nhàng trong quá trình cài đặt gói
    import warnings
    warnings.warn(
        f"Một số thành phần không thể import được: {e}. "
        "Điều này là bình thường trong quá trình cài đặt gói.",
        ImportWarning
    )

    __all__ = [
        '__version__',
        '__version_info__',
        '__author__',
        '__email__',
        '__license__',
        '__copyright__',
    ]


def get_version():
    """Lấy phiên bản gói."""
    return __version__


def get_version_info():
    """Lấy phiên bản gói dưới dạng tuple."""
    return __version_info__


def get_package_info():
    """Lấy thông tin gói toàn diện."""
    return {
        'name': __title__,
        'version': __version__,
        'version_info': __version_info__,
        'description': __description__,
        'author': __author__,
        'author_email': __email__,
        'license': __license__,
        'copyright': __copyright__,
        'url': __url__,
        'download_url': __download_url__,
    }


def check_dependencies():
    """Kiểm tra xem tất cả phụ thuộc bắt buộc có khả dụng không."""
    missing_deps = []
    optional_deps = []

    # Phụ thuộc cốt lõi
    required_modules = [
        ('fastapi', 'FastAPI'),
        ('uvicorn', 'Uvicorn'),
        ('pydantic', 'Pydantic'),
        ('sqlalchemy', 'SQLAlchemy'),
        ('numpy', 'NumPy'),
        ('torch', 'PyTorch'),
        ('cv2', 'OpenCV'),
        ('scipy', 'SciPy'),
        ('pandas', 'Pandas'),
        ('redis', 'Redis'),
        ('psutil', 'psutil'),
        ('click', 'Click'),
    ]

    for module_name, display_name in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            missing_deps.append(display_name)

    # Phụ thuộc tùy chọn
    optional_modules = [
        ('scapy', 'Scapy (để bắt gói mạng)'),
        ('paramiko', 'Paramiko (để kết nối SSH)'),
        ('serial', 'PySerial (để giao tiếp nối tiếp)'),
        ('matplotlib', 'Matplotlib (để vẽ đồ thị)'),
        ('prometheus_client', 'Prometheus Client (để xuất chỉ số)'),
    ]

    for module_name, display_name in optional_modules:
        try:
            __import__(module_name)
        except ImportError:
            optional_deps.append(display_name)

    return {
        'missing_required': missing_deps,
        'missing_optional': optional_deps,
        'all_required_available': len(missing_deps) == 0,
    }


def print_system_info():
    """In thông tin hệ thống và gói."""
    import sys
    import platform

    info = get_package_info()
    deps = check_dependencies()

    print(f"WiFi-DensePose v{info['version']}")
    print(f"Python {sys.version}")
    print(f"Nền tảng: {platform.platform()}")
    print(f"Kiến trúc: {platform.architecture()[0]}")
    print()

    if deps['all_required_available']:
        print("✅ Tất cả phụ thuộc bắt buộc đều khả dụng")
    else:
        print("❌ Thiếu phụ thuộc bắt buộc:")
        for dep in deps['missing_required']:
            print(f"   - {dep}")

    if deps['missing_optional']:
        print("\n⚠️  Thiếu phụ thuộc tùy chọn:")
        for dep in deps['missing_optional']:
            print(f"   - {dep}")

    print(f"\nĐể biết thêm thông tin, truy cập: {info['url']}")


# Cấu hình cấp gói
import logging

# Thiết lập cấu hình logging cơ bản
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Tắt bớt một số logger bên thứ ba gây ồn
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)

# Thông báo khởi tạo gói
if __name__ != '__main__':
    logger = logging.getLogger(__name__)
    logger.debug(f"Gói WiFi-DensePose v{__version__} đã được khởi tạo")


# Bí danh tương thích ngược
try:
    WifiDensePose = app  # Bí danh cũ
except NameError:
    WifiDensePose = None  # Sẽ là None nếu import app thất bại

try:
    get_config = get_settings  # Bí danh cũ
except NameError:
    get_config = None  # Sẽ là None nếu import get_settings thất bại


def main():
    """Điểm vào chính khi gói được chạy như module."""
    print_system_info()


if __name__ == '__main__':
    main()
