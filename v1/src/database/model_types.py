"""
Trợ giúp tương thích kiểu cơ sở dữ liệu cho WiFi-DensePose API
"""

from typing import Type, Any
from sqlalchemy import String, Text, JSON
from sqlalchemy.dialects.postgresql import ARRAY as PostgreSQL_ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import sqltypes


class ArrayType(sqltypes.TypeDecorator):
    """Kiểu mảng hoạt động với cả PostgreSQL và SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, item_type: Type = String):
        super().__init__()
        self.item_type = item_type

    def load_dialect_impl(self, dialect):
        """Tải triển khai cụ thể theo phương ngữ."""
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PostgreSQL_ARRAY(self.item_type))
        else:
            # Đối với SQLite và các loại khác, sử dụng JSON
            return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        """Xử lý giá trị trước khi lưu vào cơ sở dữ liệu."""
        if value is None:
            return value

        if dialect.name == 'postgresql':
            return value
        else:
            # Đối với SQLite, chuyển đổi sang JSON
            return value if isinstance(value, (list, type(None))) else list(value)

    def process_result_value(self, value, dialect):
        """Xử lý giá trị sau khi tải từ cơ sở dữ liệu."""
        if value is None:
            return value

        if dialect.name == 'postgresql':
            return value
        else:
            # Đối với SQLite, giá trị đã là danh sách từ JSON
            return value if isinstance(value, list) else []


def get_array_type(item_type: Type = String) -> Type:
    """Lấy kiểu mảng phù hợp dựa trên cơ sở dữ liệu."""
    return ArrayType(item_type)


# Kiểu tiện lợi
StringArray = ArrayType(String)
FloatArray = ArrayType(sqltypes.Float)
