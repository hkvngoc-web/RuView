"""
Quản lý cấu hình tập trung cho WiFi-DensePose API
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from functools import lru_cache

from src.config.settings import Settings, get_settings
from src.config.domains import DomainConfig, get_domain_config

logger = logging.getLogger(__name__)


class ConfigManager:
    """Trình quản lý cấu hình tập trung."""

    def __init__(self):
        self._settings: Optional[Settings] = None
        self._domain_config: Optional[DomainConfig] = None
        self._environment_overrides: Dict[str, Any] = {}

    @property
    def settings(self) -> Settings:
        """Lấy cài đặt ứng dụng."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def domain_config(self) -> DomainConfig:
        """Lấy cấu hình miền nghiệp vụ."""
        if self._domain_config is None:
            self._domain_config = get_domain_config()
        return self._domain_config

    def reload_settings(self) -> Settings:
        """Tải lại cài đặt từ môi trường."""
        self._settings = None
        return self.settings

    def reload_domain_config(self) -> DomainConfig:
        """Tải lại cấu hình miền nghiệp vụ."""
        self._domain_config = None
        return self.domain_config

    def set_environment_override(self, key: str, value: Any):
        """Đặt ghi đè biến môi trường."""
        self._environment_overrides[key] = value
        os.environ[key] = str(value)

    def get_environment_override(self, key: str, default: Any = None) -> Any:
        """Lấy ghi đè biến môi trường."""
        return self._environment_overrides.get(key, os.environ.get(key, default))

    def clear_environment_overrides(self):
        """Xóa tất cả ghi đè môi trường."""
        for key in self._environment_overrides:
            if key in os.environ:
                del os.environ[key]
        self._environment_overrides.clear()

    def get_database_config(self) -> Dict[str, Any]:
        """Lấy cấu hình cơ sở dữ liệu."""
        settings = self.settings

        config = {
            "url": settings.get_database_url(),
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "echo": settings.is_development and settings.debug,
            "pool_pre_ping": True,
            "pool_recycle": 3600,  # 1 giờ
        }

        return config

    def get_redis_config(self) -> Optional[Dict[str, Any]]:
        """Lấy cấu hình Redis."""
        settings = self.settings
        redis_url = settings.get_redis_url()

        if not redis_url:
            return None

        config = {
            "url": redis_url,
            "password": settings.redis_password,
            "db": settings.redis_db,
            "decode_responses": True,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry_on_timeout": True,
            "health_check_interval": 30,
        }

        return config

    def get_logging_config(self) -> Dict[str, Any]:
        """Lấy cấu hình ghi log."""
        return self.settings.get_logging_config()

    def get_cors_config(self) -> Dict[str, Any]:
        """Lấy cấu hình CORS."""
        return self.settings.get_cors_config()

    def get_security_config(self) -> Dict[str, Any]:
        """Lấy cấu hình bảo mật."""
        settings = self.settings

        config = {
            "secret_key": settings.secret_key,
            "jwt_algorithm": settings.jwt_algorithm,
            "jwt_expire_hours": settings.jwt_expire_hours,
            "allowed_hosts": settings.allowed_hosts,
            "enable_authentication": settings.enable_authentication,
        }

        return config

    def get_hardware_config(self) -> Dict[str, Any]:
        """Lấy cấu hình phần cứng."""
        settings = self.settings
        domain_config = self.domain_config

        config = {
            "wifi_interface": settings.wifi_interface,
            "csi_buffer_size": settings.csi_buffer_size,
            "polling_interval": settings.hardware_polling_interval,
            "mock_hardware": settings.mock_hardware,
            "routers": [router.dict() for router in domain_config.routers],
        }

        return config

    def get_pose_config(self) -> Dict[str, Any]:
        """Lấy cấu hình ước lượng tư thế."""
        settings = self.settings
        domain_config = self.domain_config

        config = {
            "model_path": settings.pose_model_path,
            "confidence_threshold": settings.pose_confidence_threshold,
            "batch_size": settings.pose_processing_batch_size,
            "max_persons": settings.pose_max_persons,
            "mock_pose_data": settings.mock_pose_data,
            "models": [model.dict() for model in domain_config.pose_models],
        }

        return config

    def get_streaming_config(self) -> Dict[str, Any]:
        """Lấy cấu hình truyền phát."""
        settings = self.settings
        domain_config = self.domain_config

        config = {
            "fps": settings.stream_fps,
            "buffer_size": settings.stream_buffer_size,
            "websocket_ping_interval": settings.websocket_ping_interval,
            "websocket_timeout": settings.websocket_timeout,
            "enable_websockets": settings.enable_websockets,
            "enable_real_time_processing": settings.enable_real_time_processing,
            "max_connections": domain_config.streaming.max_connections,
            "compression": domain_config.streaming.compression,
        }

        return config

    def get_storage_config(self) -> Dict[str, Any]:
        """Lấy cấu hình lưu trữ."""
        settings = self.settings

        config = {
            "data_path": Path(settings.data_storage_path),
            "model_path": Path(settings.model_storage_path),
            "temp_path": Path(settings.temp_storage_path),
            "max_size_gb": settings.max_storage_size_gb,
            "enable_historical_data": settings.enable_historical_data,
        }

        # Đảm bảo các thư mục tồn tại
        for path in [config["data_path"], config["model_path"], config["temp_path"]]:
            path.mkdir(parents=True, exist_ok=True)

        return config

    def get_monitoring_config(self) -> Dict[str, Any]:
        """Lấy cấu hình giám sát."""
        settings = self.settings

        config = {
            "metrics_enabled": settings.metrics_enabled,
            "health_check_interval": settings.health_check_interval,
            "performance_monitoring": settings.performance_monitoring,
            "log_level": settings.log_level,
            "log_file": settings.log_file,
        }

        return config

    def get_rate_limiting_config(self) -> Dict[str, Any]:
        """Lấy cấu hình giới hạn tốc độ."""
        settings = self.settings

        config = {
            "enabled": settings.enable_rate_limiting,
            "requests": settings.rate_limit_requests,
            "authenticated_requests": settings.rate_limit_authenticated_requests,
            "window": settings.rate_limit_window,
        }

        return config

    def validate_configuration(self) -> List[str]:
        """Xác thực toàn bộ cấu hình và trả về các vấn đề."""
        issues = []

        try:
            # Xác thực cài đặt
            from src.config.settings import validate_settings
            settings_issues = validate_settings(self.settings)
            issues.extend(settings_issues)

            # Xác thực cấu hình cơ sở dữ liệu
            try:
                db_config = self.get_database_config()
                if not db_config["url"]:
                    issues.append("URL cơ sở dữ liệu chưa được cấu hình")
            except Exception as e:
                issues.append(f"Lỗi cấu hình cơ sở dữ liệu: {e}")

            # Xác thực đường dẫn lưu trữ
            try:
                storage_config = self.get_storage_config()
                for name, path in storage_config.items():
                    if name.endswith("_path") and not path.exists():
                        issues.append(f"Đường dẫn lưu trữ không tồn tại: {path}")
            except Exception as e:
                issues.append(f"Lỗi cấu hình lưu trữ: {e}")

            # Xác thực cấu hình phần cứng
            try:
                hw_config = self.get_hardware_config()
                if not hw_config["routers"]:
                    issues.append("Chưa cấu hình router nào")
            except Exception as e:
                issues.append(f"Lỗi cấu hình phần cứng: {e}")

            # Xác thực cấu hình tư thế
            try:
                pose_config = self.get_pose_config()
                if not pose_config["models"]:
                    issues.append("Chưa cấu hình mô hình tư thế nào")
            except Exception as e:
                issues.append(f"Lỗi cấu hình tư thế: {e}")

        except Exception as e:
            issues.append(f"Lỗi xác thực cấu hình: {e}")

        return issues

    def get_full_config(self) -> Dict[str, Any]:
        """Lấy dictionary cấu hình đầy đủ."""
        return {
            "settings": self.settings.dict(),
            "domain_config": self.domain_config.to_dict(),
            "database": self.get_database_config(),
            "redis": self.get_redis_config(),
            "security": self.get_security_config(),
            "hardware": self.get_hardware_config(),
            "pose": self.get_pose_config(),
            "streaming": self.get_streaming_config(),
            "storage": self.get_storage_config(),
            "monitoring": self.get_monitoring_config(),
            "rate_limiting": self.get_rate_limiting_config(),
        }


# Thể hiện trình quản lý cấu hình toàn cục
@lru_cache()
def get_config_manager() -> ConfigManager:
    """Lấy thể hiện trình quản lý cấu hình được cache."""
    return ConfigManager()


# Các hàm tiện ích
def get_app_settings() -> Settings:
    """Lấy cài đặt ứng dụng."""
    return get_config_manager().settings


def get_app_domain_config() -> DomainConfig:
    """Lấy cấu hình miền nghiệp vụ."""
    return get_config_manager().domain_config


def validate_app_configuration() -> List[str]:
    """Xác thực cấu hình ứng dụng."""
    return get_config_manager().validate_configuration()


def reload_configuration():
    """Tải lại toàn bộ cấu hình."""
    config_manager = get_config_manager()
    config_manager.reload_settings()
    config_manager.reload_domain_config()
    logger.info("Đã tải lại cấu hình")
