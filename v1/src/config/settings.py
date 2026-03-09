"""
Cài đặt Pydantic cho WiFi-DensePose API
"""

import os
from typing import List, Optional, Dict, Any
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cài đặt ứng dụng với hỗ trợ biến môi trường."""

    # Cài đặt ứng dụng
    app_name: str = Field(default="WiFi-DensePose API", description="Tên ứng dụng")
    version: str = Field(default="1.0.0", description="Phiên bản ứng dụng")
    environment: str = Field(default="development", description="Môi trường (development, staging, production)")
    debug: bool = Field(default=False, description="Chế độ gỡ lỗi")

    # Cài đặt máy chủ
    host: str = Field(default="0.0.0.0", description="Máy chủ lắng nghe")
    port: int = Field(default=8000, description="Cổng máy chủ")
    reload: bool = Field(default=False, description="Tự động tải lại khi thay đổi mã")
    workers: int = Field(default=1, description="Số tiến trình worker")

    # Cài đặt bảo mật
    secret_key: str = Field(..., description="Khóa bí mật cho token JWT")
    jwt_algorithm: str = Field(default="HS256", description="Thuật toán JWT")
    jwt_expire_hours: int = Field(default=24, description="Thời gian hết hạn token JWT tính bằng giờ")
    allowed_hosts: List[str] = Field(default=["*"], description="Các máy chủ được phép")
    cors_origins: List[str] = Field(default=["*"], description="Các nguồn gốc CORS được phép")

    # Cài đặt giới hạn tốc độ
    rate_limit_requests: int = Field(default=100, description="Số yêu cầu giới hạn mỗi cửa sổ")
    rate_limit_authenticated_requests: int = Field(default=1000, description="Giới hạn tốc độ cho người dùng đã xác thực")
    rate_limit_window: int = Field(default=3600, description="Cửa sổ giới hạn tốc độ tính bằng giây")

    # Cài đặt cơ sở dữ liệu
    database_url: Optional[str] = Field(default=None, description="URL kết nối cơ sở dữ liệu")
    database_pool_size: int = Field(default=10, description="Kích thước pool kết nối cơ sở dữ liệu")
    database_max_overflow: int = Field(default=20, description="Số kết nối tràn tối đa của cơ sở dữ liệu")

    # Cài đặt pool kết nối cơ sở dữ liệu (tên thay thế cho tương thích)
    db_pool_size: int = Field(default=10, description="Kích thước pool kết nối cơ sở dữ liệu")
    db_max_overflow: int = Field(default=20, description="Số kết nối tràn tối đa của cơ sở dữ liệu")
    db_pool_timeout: int = Field(default=30, description="Thời gian chờ pool cơ sở dữ liệu tính bằng giây")
    db_pool_recycle: int = Field(default=3600, description="Thời gian tái chế pool cơ sở dữ liệu tính bằng giây")

    # Cài đặt kết nối cơ sở dữ liệu
    db_host: Optional[str] = Field(default=None, description="Máy chủ cơ sở dữ liệu")
    db_port: int = Field(default=5432, description="Cổng cơ sở dữ liệu")
    db_name: Optional[str] = Field(default=None, description="Tên cơ sở dữ liệu")
    db_user: Optional[str] = Field(default=None, description="Người dùng cơ sở dữ liệu")
    db_password: Optional[str] = Field(default=None, description="Mật khẩu cơ sở dữ liệu")
    db_echo: bool = Field(default=False, description="Bật ghi log truy vấn cơ sở dữ liệu")

    # Cài đặt Redis (cho bộ nhớ đệm và giới hạn tốc độ)
    redis_url: Optional[str] = Field(default=None, description="URL kết nối Redis")
    redis_password: Optional[str] = Field(default=None, description="Mật khẩu Redis")
    redis_db: int = Field(default=0, description="Số cơ sở dữ liệu Redis")
    redis_enabled: bool = Field(default=True, description="Bật Redis")
    redis_host: str = Field(default="localhost", description="Máy chủ Redis")
    redis_port: int = Field(default=6379, description="Cổng Redis")
    redis_required: bool = Field(default=False, description="Yêu cầu kết nối Redis (thất bại nếu không khả dụng)")
    redis_max_connections: int = Field(default=10, description="Số kết nối Redis tối đa")
    redis_socket_timeout: int = Field(default=5, description="Thời gian chờ socket Redis tính bằng giây")
    redis_connect_timeout: int = Field(default=5, description="Thời gian chờ kết nối Redis tính bằng giây")

    # Cài đặt dự phòng
    enable_database_failsafe: bool = Field(default=True, description="Bật dự phòng SQLite tự động khi PostgreSQL không khả dụng")
    enable_redis_failsafe: bool = Field(default=True, description="Bật dự phòng Redis tự động (tắt khi không khả dụng)")
    sqlite_fallback_path: str = Field(default="./data/wifi_densepose_fallback.db", description="Đường dẫn cơ sở dữ liệu SQLite dự phòng")

    # Cài đặt phần cứng
    wifi_interface: str = Field(default="wlan0", description="Tên giao diện WiFi")
    csi_buffer_size: int = Field(default=1000, description="Kích thước bộ đệm dữ liệu CSI")
    hardware_polling_interval: float = Field(default=0.1, description="Khoảng thời gian thăm dò phần cứng tính bằng giây")
    router_ssh_username: str = Field(default="admin", description="Tên đăng nhập SSH mặc định cho kết nối router")
    router_ssh_password: str = Field(default="", description="Mật khẩu SSH mặc định cho kết nối router (đặt qua biến môi trường ROUTER_SSH_PASSWORD)")

    # Cài đặt xử lý CSI
    csi_sampling_rate: int = Field(default=1000, description="Tốc độ lấy mẫu CSI")
    csi_window_size: int = Field(default=512, description="Kích thước cửa sổ CSI")
    csi_overlap: float = Field(default=0.5, description="Độ chồng lấp cửa sổ CSI")
    csi_noise_threshold: float = Field(default=0.1, description="Ngưỡng nhiễu CSI")
    csi_human_detection_threshold: float = Field(default=0.8, description="Ngưỡng phát hiện con người CSI")
    csi_smoothing_factor: float = Field(default=0.9, description="Hệ số làm mịn CSI")
    csi_max_history_size: int = Field(default=500, description="Kích thước lịch sử CSI tối đa")

    # Cài đặt ước lượng tư thế
    pose_model_path: Optional[str] = Field(default=None, description="Đường dẫn đến mô hình ước lượng tư thế")
    pose_confidence_threshold: float = Field(default=0.5, description="Ngưỡng độ tin cậy tối thiểu")
    pose_processing_batch_size: int = Field(default=32, description="Kích thước lô xử lý tư thế")
    pose_max_persons: int = Field(default=10, description="Số người tối đa phát hiện mỗi khung hình")

    # Cài đặt truyền phát
    stream_fps: int = Field(default=30, description="Số khung hình mỗi giây khi truyền phát")
    stream_buffer_size: int = Field(default=100, description="Kích thước bộ đệm truyền phát")
    websocket_ping_interval: int = Field(default=60, description="Khoảng thời gian ping WebSocket tính bằng giây")
    websocket_timeout: int = Field(default=300, description="Thời gian chờ WebSocket tính bằng giây")

    # Cài đặt ghi log
    log_level: str = Field(default="INFO", description="Mức ghi log")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Định dạng log"
    )
    log_file: Optional[str] = Field(default=None, description="Đường dẫn file log")
    log_directory: str = Field(default="./logs", description="Đường dẫn thư mục log")
    log_max_size: int = Field(default=10485760, description="Kích thước file log tối đa tính bằng byte (10MB)")
    log_backup_count: int = Field(default=5, description="Số file log sao lưu")

    # Cài đặt giám sát
    metrics_enabled: bool = Field(default=True, description="Bật thu thập số liệu")
    health_check_interval: int = Field(default=30, description="Khoảng thời gian kiểm tra sức khỏe tính bằng giây")
    performance_monitoring: bool = Field(default=True, description="Bật giám sát hiệu suất")
    monitoring_interval_seconds: int = Field(default=60, description="Khoảng thời gian tác vụ giám sát tính bằng giây")
    cleanup_interval_seconds: int = Field(default=3600, description="Khoảng thời gian tác vụ dọn dẹp tính bằng giây")
    backup_interval_seconds: int = Field(default=86400, description="Khoảng thời gian tác vụ sao lưu tính bằng giây")

    # Cài đặt lưu trữ
    data_storage_path: str = Field(default="./data", description="Thư mục lưu trữ dữ liệu")
    model_storage_path: str = Field(default="./models", description="Thư mục lưu trữ mô hình")
    temp_storage_path: str = Field(default="./temp", description="Thư mục lưu trữ tạm thời")
    backup_directory: str = Field(default="./backups", description="Thư mục lưu trữ sao lưu")
    max_storage_size_gb: int = Field(default=100, description="Kích thước lưu trữ tối đa tính bằng GB")

    # Cài đặt API
    api_prefix: str = Field(default="/api/v1", description="Tiền tố API")
    docs_url: str = Field(default="/docs", description="URL tài liệu API")
    redoc_url: str = Field(default="/redoc", description="URL tài liệu ReDoc")
    openapi_url: str = Field(default="/openapi.json", description="URL schema OpenAPI")

    # Cờ tính năng
    enable_authentication: bool = Field(default=True, description="Bật xác thực")
    enable_rate_limiting: bool = Field(default=True, description="Bật giới hạn tốc độ")
    enable_websockets: bool = Field(default=True, description="Bật hỗ trợ WebSocket")
    enable_historical_data: bool = Field(default=True, description="Bật lưu trữ dữ liệu lịch sử")
    enable_real_time_processing: bool = Field(default=True, description="Bật xử lý thời gian thực")
    cors_enabled: bool = Field(default=True, description="Bật middleware CORS")
    cors_allow_credentials: bool = Field(default=True, description="Cho phép thông tin xác thực trong CORS")

    # Cài đặt phát triển
    mock_hardware: bool = Field(default=False, description="Sử dụng phần cứng giả lập cho phát triển")
    mock_pose_data: bool = Field(default=False, description="Sử dụng dữ liệu tư thế giả lập cho phát triển")
    enable_test_endpoints: bool = Field(default=False, description="Bật endpoint kiểm thử")

    # Cài đặt dọn dẹp
    csi_data_retention_days: int = Field(default=30, description="Thời gian lưu giữ dữ liệu CSI tính bằng ngày")
    pose_detection_retention_days: int = Field(default=30, description="Thời gian lưu giữ phát hiện tư thế tính bằng ngày")
    metrics_retention_days: int = Field(default=7, description="Thời gian lưu giữ số liệu tính bằng ngày")
    audit_log_retention_days: int = Field(default=90, description="Thời gian lưu giữ log kiểm toán tính bằng ngày")
    orphaned_session_threshold_days: int = Field(default=7, description="Ngưỡng phiên mồ côi tính bằng ngày")
    cleanup_batch_size: int = Field(default=1000, description="Kích thước lô dọn dẹp")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        """Xác thực cài đặt môi trường."""
        allowed_environments = ["development", "staging", "production"]
        if v not in allowed_environments:
            raise ValueError(f"Môi trường phải là một trong: {allowed_environments}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Xác thực cài đặt mức ghi log."""
        allowed_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed_levels:
            raise ValueError(f"Mức ghi log phải là một trong: {allowed_levels}")
        return v.upper()

    @field_validator("pose_confidence_threshold")
    @classmethod
    def validate_confidence_threshold(cls, v):
        """Xác thực ngưỡng độ tin cậy."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Ngưỡng độ tin cậy phải nằm trong khoảng 0.0 đến 1.0")
        return v

    @field_validator("stream_fps")
    @classmethod
    def validate_stream_fps(cls, v):
        """Xác thực FPS truyền phát."""
        if not 1 <= v <= 60:
            raise ValueError("FPS truyền phát phải nằm trong khoảng 1 đến 60")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v):
        """Xác thực số cổng."""
        if not 1 <= v <= 65535:
            raise ValueError("Cổng phải nằm trong khoảng 1 đến 65535")
        return v

    @field_validator("workers")
    @classmethod
    def validate_workers(cls, v):
        """Xác thực số worker."""
        if v < 1:
            raise ValueError("Số worker phải ít nhất là 1")
        return v

    @field_validator("db_port")
    @classmethod
    def validate_db_port(cls, v):
        """Xác thực cổng cơ sở dữ liệu."""
        if not 1 <= v <= 65535:
            raise ValueError("Cổng cơ sở dữ liệu phải nằm trong khoảng 1 đến 65535")
        return v

    @field_validator("redis_port")
    @classmethod
    def validate_redis_port(cls, v):
        """Xác thực cổng Redis."""
        if not 1 <= v <= 65535:
            raise ValueError("Cổng Redis phải nằm trong khoảng 1 đến 65535")
        return v

    @field_validator("db_pool_size")
    @classmethod
    def validate_db_pool_size(cls, v):
        """Xác thực kích thước pool cơ sở dữ liệu."""
        if v < 1:
            raise ValueError("Kích thước pool cơ sở dữ liệu phải ít nhất là 1")
        return v

    @field_validator("monitoring_interval_seconds", "cleanup_interval_seconds", "backup_interval_seconds")
    @classmethod
    def validate_interval_seconds(cls, v):
        """Xác thực cài đặt khoảng thời gian."""
        if v < 0:
            raise ValueError("Khoảng thời gian tính bằng giây phải không âm")
        return v
    @property
    def is_development(self) -> bool:
        """Kiểm tra có đang chạy trong môi trường phát triển không."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """Kiểm tra có đang chạy trong môi trường sản xuất không."""
        return self.environment == "production"

    @property
    def is_testing(self) -> bool:
        """Kiểm tra có đang chạy trong môi trường kiểm thử không."""
        return self.environment == "testing"

    def get_database_url(self) -> str:
        """Lấy URL cơ sở dữ liệu với dự phòng."""
        if self.database_url:
            return self.database_url

        # Xây dựng URL từ các thành phần riêng lẻ nếu có
        if self.db_host and self.db_name and self.db_user:
            password_part = f":{self.db_password}" if self.db_password else ""
            return f"postgresql://{self.db_user}{password_part}@{self.db_host}:{self.db_port}/{self.db_name}"

        # Cơ sở dữ liệu SQLite mặc định cho phát triển
        if self.is_development:
            return f"sqlite:///{self.data_storage_path}/wifi_densepose.db"

        # Dự phòng SQLite cho sản xuất nếu được bật
        if self.enable_database_failsafe:
            return f"sqlite:///{self.sqlite_fallback_path}"

        raise ValueError("URL cơ sở dữ liệu phải được cấu hình cho môi trường không phải phát triển")

    def get_sqlite_fallback_url(self) -> str:
        """Lấy URL cơ sở dữ liệu SQLite dự phòng."""
        return f"sqlite:///{self.sqlite_fallback_path}"

    def get_redis_url(self) -> Optional[str]:
        """Lấy URL Redis với dự phòng."""
        if not self.redis_enabled:
            return None

        if self.redis_url:
            return self.redis_url

        # Xây dựng URL từ các thành phần riêng lẻ
        password_part = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def get_cors_config(self) -> Dict[str, Any]:
        """Lấy cấu hình CORS."""
        if self.is_development:
            return {
                "allow_origins": ["*"],
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            }

        return {
            "allow_origins": self.cors_origins,
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
        }

    def get_logging_config(self) -> Dict[str, Any]:
        """Lấy cấu hình ghi log."""
        config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": self.log_format,
                },
                "detailed": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": self.log_level,
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "": {
                    "level": self.log_level,
                    "handlers": ["console"],
                },
                "uvicorn": {
                    "level": "INFO",
                    "handlers": ["console"],
                    "propagate": False,
                },
                "fastapi": {
                    "level": "INFO",
                    "handlers": ["console"],
                    "propagate": False,
                },
            },
        }

        # Thêm handler file nếu file log được chỉ định
        if self.log_file:
            config["handlers"]["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": self.log_level,
                "formatter": "detailed",
                "filename": self.log_file,
                "maxBytes": self.log_max_size,
                "backupCount": self.log_backup_count,
            }

            # Thêm handler file vào tất cả logger
            for logger_config in config["loggers"].values():
                logger_config["handlers"].append("file")

        return config

    def create_directories(self):
        """Tạo các thư mục cần thiết."""
        directories = [
            self.data_storage_path,
            self.model_storage_path,
            self.temp_storage_path,
            self.log_directory,
            self.backup_directory,
        ]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Lấy thể hiện cài đặt được cache."""
    settings = Settings()
    settings.create_directories()
    return settings


def get_test_settings() -> Settings:
    """Lấy cài đặt cho kiểm thử."""
    return Settings(
        environment="testing",
        debug=True,
        secret_key="test-secret-key",
        database_url="sqlite:///:memory:",
        mock_hardware=True,
        mock_pose_data=True,
        enable_test_endpoints=True,
        log_level="DEBUG"
    )


def load_settings_from_file(file_path: str) -> Settings:
    """Tải cài đặt từ file cụ thể."""
    return Settings(_env_file=file_path)


def validate_settings(settings: Settings) -> List[str]:
    """Xác thực cài đặt và trả về danh sách các vấn đề."""
    issues = []

    # Kiểm tra cài đặt bắt buộc cho sản xuất
    if settings.is_production:
        if not settings.secret_key or settings.secret_key == "change-me":
            issues.append("Khóa bí mật phải được đặt cho môi trường sản xuất")

        if not settings.database_url and not (settings.db_host and settings.db_name and settings.db_user):
            issues.append("URL cơ sở dữ liệu hoặc thông số kết nối cơ sở dữ liệu phải được đặt cho môi trường sản xuất")

        if settings.debug:
            issues.append("Chế độ gỡ lỗi nên được tắt trong môi trường sản xuất")

        if "*" in settings.allowed_hosts:
            issues.append("Máy chủ được phép nên được giới hạn trong môi trường sản xuất")

        if "*" in settings.cors_origins:
            issues.append("Nguồn gốc CORS nên được giới hạn trong môi trường sản xuất")

    # Kiểm tra đường dẫn lưu trữ tồn tại
    try:
        settings.create_directories()
    except Exception as e:
        issues.append(f"Không thể tạo thư mục lưu trữ: {e}")

    return issues
