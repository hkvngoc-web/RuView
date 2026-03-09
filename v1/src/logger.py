"""
Cấu hình ghi log cho WiFi-DensePose API
"""

import logging
import logging.config
import logging.handlers
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from src.config.settings import Settings


class ColoredFormatter(logging.Formatter):
    """Trình định dạng log có màu cho đầu ra console."""

    # Mã màu ANSI
    COLORS = {
        'DEBUG': '\033[36m',      # Xanh lam nhạt
        'INFO': '\033[32m',       # Xanh lá
        'WARNING': '\033[33m',    # Vàng
        'ERROR': '\033[31m',      # Đỏ
        'CRITICAL': '\033[35m',   # Tím
        'RESET': '\033[0m'        # Đặt lại
    }

    def format(self, record):
        """Định dạng bản ghi log với màu sắc."""
        if hasattr(record, 'levelname'):
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"

        return super().format(record)


class StructuredFormatter(logging.Formatter):
    """Trình định dạng JSON có cấu trúc cho file log."""

    def format(self, record):
        """Định dạng bản ghi log dưới dạng JSON có cấu trúc."""
        import json

        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Thêm thông tin ngoại lệ nếu có
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        # Thêm các trường bổ sung
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'lineno', 'funcName', 'created',
                          'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'getMessage', 'exc_info',
                          'exc_text', 'stack_info']:
                log_entry[key] = value

        return json.dumps(log_entry)


class RequestContextFilter(logging.Filter):
    """Bộ lọc thêm ngữ cảnh yêu cầu vào bản ghi log."""

    def filter(self, record):
        """Thêm ngữ cảnh yêu cầu vào bản ghi log."""
        # Thử lấy ngữ cảnh yêu cầu từ contextvars hoặc thread local
        try:
            import contextvars
            request_id = contextvars.ContextVar('request_id', default=None).get()
            user_id = contextvars.ContextVar('user_id', default=None).get()

            if request_id:
                record.request_id = request_id
            if user_id:
                record.user_id = user_id

        except (ImportError, LookupError):
            pass

        return True


def setup_logging(settings: Settings) -> None:
    """Thiết lập cấu hình ghi log ứng dụng."""

    # Tạo thư mục log nếu ghi log vào file được bật
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Xây dựng cấu hình ghi log
    config = build_logging_config(settings)

    # Áp dụng cấu hình
    logging.config.dictConfig(config)

    # Thiết lập logger gốc
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)

    # Thêm bộ lọc ngữ cảnh yêu cầu vào tất cả handler
    request_filter = RequestContextFilter()
    for handler in root_logger.handlers:
        handler.addFilter(request_filter)

    # Ghi thông báo khởi động
    logger = logging.getLogger(__name__)
    logger.info(f"Đã cấu hình ghi log - Mức: {settings.log_level}, File: {settings.log_file}")


def build_logging_config(settings: Settings) -> Dict[str, Any]:
    """Xây dựng dictionary cấu hình ghi log."""

    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'console': {
                '()': ColoredFormatter,
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'file': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S'
            },
            'structured': {
                '()': StructuredFormatter
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': settings.log_level,
                'formatter': 'console',
                'stream': 'ext://sys.stdout'
            }
        },
        'loggers': {
            '': {  # Logger gốc
                'level': settings.log_level,
                'handlers': ['console'],
                'propagate': False
            },
            'src': {  # Logger ứng dụng
                'level': settings.log_level,
                'handlers': ['console'],
                'propagate': False
            },
            'uvicorn': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'uvicorn.access': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'fastapi': {
                'level': 'INFO',
                'handlers': ['console'],
                'propagate': False
            },
            'sqlalchemy': {
                'level': 'WARNING',
                'handlers': ['console'],
                'propagate': False
            },
            'sqlalchemy.engine': {
                'level': 'INFO' if settings.debug else 'WARNING',
                'handlers': ['console'],
                'propagate': False
            }
        }
    }

    # Thêm handler file nếu file log được chỉ định
    if settings.log_file:
        config['handlers']['file'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': settings.log_level,
            'formatter': 'file',
            'filename': settings.log_file,
            'maxBytes': settings.log_max_size,
            'backupCount': settings.log_backup_count,
            'encoding': 'utf-8'
        }

        # Thêm handler log có cấu trúc cho log JSON
        structured_log_file = str(Path(settings.log_file).with_suffix('.json'))
        config['handlers']['structured'] = {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': settings.log_level,
            'formatter': 'structured',
            'filename': structured_log_file,
            'maxBytes': settings.log_max_size,
            'backupCount': settings.log_backup_count,
            'encoding': 'utf-8'
        }

        # Thêm handler file vào tất cả logger
        for logger_config in config['loggers'].values():
            logger_config['handlers'].extend(['file', 'structured'])

    return config


def get_logger(name: str) -> logging.Logger:
    """Lấy logger với tên được chỉ định."""
    return logging.getLogger(name)


def configure_third_party_loggers(settings: Settings) -> None:
    """Cấu hình logger của thư viện bên thứ ba."""

    # Tắt bớt logger ồn ào trong môi trường sản xuất
    if settings.is_production:
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('requests').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        logging.getLogger('multipart').setLevel(logging.WARNING)

    # Cấu hình ghi log SQLAlchemy
    if settings.debug and settings.is_development:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
        logging.getLogger('sqlalchemy.pool').setLevel(logging.DEBUG)
    else:
        logging.getLogger('sqlalchemy').setLevel(logging.WARNING)

    # Cấu hình ghi log Redis
    logging.getLogger('redis').setLevel(logging.WARNING)

    # Cấu hình ghi log WebSocket
    logging.getLogger('websockets').setLevel(logging.INFO)


class LoggerMixin:
    """Lớp mixin thêm khả năng ghi log vào bất kỳ lớp nào."""

    @property
    def logger(self) -> logging.Logger:
        """Lấy logger cho lớp này."""
        return logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")


def log_function_call(func):
    """Decorator ghi log các lời gọi hàm."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.debug(f"Đang gọi {func.__name__} với args={args}, kwargs={kwargs}")

        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} hoàn thành thành công")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} thất bại với lỗi: {e}")
            raise

    return wrapper


def log_async_function_call(func):
    """Decorator ghi log các lời gọi hàm bất đồng bộ."""
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        logger.debug(f"Đang gọi bất đồng bộ {func.__name__} với args={args}, kwargs={kwargs}")

        try:
            result = await func(*args, **kwargs)
            logger.debug(f"Bất đồng bộ {func.__name__} hoàn thành thành công")
            return result
        except Exception as e:
            logger.error(f"Bất đồng bộ {func.__name__} thất bại với lỗi: {e}")
            raise

    return wrapper


def setup_request_logging():
    """Thiết lập ngữ cảnh ghi log theo yêu cầu."""
    import contextvars
    import uuid

    # Tạo biến ngữ cảnh cho theo dõi yêu cầu
    request_id_var = contextvars.ContextVar('request_id')
    user_id_var = contextvars.ContextVar('user_id')

    def set_request_context(request_id: Optional[str] = None, user_id: Optional[str] = None):
        """Đặt ngữ cảnh yêu cầu cho ghi log."""
        if request_id is None:
            request_id = str(uuid.uuid4())

        request_id_var.set(request_id)
        if user_id:
            user_id_var.set(user_id)

    def get_request_context():
        """Lấy ngữ cảnh yêu cầu hiện tại."""
        try:
            return {
                'request_id': request_id_var.get(),
                'user_id': user_id_var.get(None)
            }
        except LookupError:
            return {}

    return set_request_context, get_request_context


# Khởi tạo ngữ cảnh ghi log yêu cầu
set_request_context, get_request_context = setup_request_logging()
