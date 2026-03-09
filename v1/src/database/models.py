"""
Mô hình SQLAlchemy cho WiFi-DensePose API
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

# Import kiểu mảng tùy chỉnh cho tương thích
from src.database.model_types import StringArray, FloatArray

Base = declarative_base()


class TimestampMixin:
    """Mixin cho trường dấu thời gian."""
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UUIDMixin:
    """Mixin cho khóa chính UUID."""
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)


class DeviceStatus(str, Enum):
    """Liệt kê trạng thái thiết bị."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class SessionStatus(str, Enum):
    """Liệt kê trạng thái phiên."""
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingStatus(str, Enum):
    """Liệt kê trạng thái xử lý."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Device(Base, UUIDMixin, TimestampMixin):
    """Mô hình thiết bị cho router WiFi và cảm biến."""
    __tablename__ = "devices"

    # Thông tin thiết bị cơ bản
    name = Column(String(255), nullable=False)
    device_type = Column(String(50), nullable=False)  # router, cảm biến, v.v.
    mac_address = Column(String(17), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=True)  # IPv4 hoặc IPv6

    # Trạng thái và cấu hình thiết bị
    status = Column(String(20), default=DeviceStatus.INACTIVE, nullable=False)
    firmware_version = Column(String(50), nullable=True)
    hardware_version = Column(String(50), nullable=True)

    # Thông tin vị trí
    location_name = Column(String(255), nullable=True)
    room_id = Column(String(100), nullable=True)
    coordinates_x = Column(Float, nullable=True)
    coordinates_y = Column(Float, nullable=True)
    coordinates_z = Column(Float, nullable=True)

    # Cấu hình
    config = Column(JSON, nullable=True)
    capabilities = Column(StringArray, nullable=True)

    # Siêu dữ liệu
    description = Column(Text, nullable=True)
    tags = Column(StringArray, nullable=True)

    # Quan hệ
    sessions = relationship("Session", back_populates="device", cascade="all, delete-orphan")
    csi_data = relationship("CSIData", back_populates="device", cascade="all, delete-orphan")

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_device_mac_address", "mac_address"),
        Index("idx_device_status", "status"),
        Index("idx_device_type", "device_type"),
        CheckConstraint("status IN ('active', 'inactive', 'maintenance', 'error')", name="check_device_status"),
    )

    @validates('mac_address')
    def validate_mac_address(self, key, address):
        """Xác thực định dạng địa chỉ MAC."""
        if address and len(address) == 17:
            # Xác thực định dạng địa chỉ MAC cơ bản
            parts = address.split(':')
            if len(parts) == 6 and all(len(part) == 2 for part in parts):
                return address.lower()
        raise ValueError("Định dạng địa chỉ MAC không hợp lệ")

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "name": self.name,
            "device_type": self.device_type,
            "mac_address": self.mac_address,
            "ip_address": self.ip_address,
            "status": self.status,
            "firmware_version": self.firmware_version,
            "hardware_version": self.hardware_version,
            "location_name": self.location_name,
            "room_id": self.room_id,
            "coordinates": {
                "x": self.coordinates_x,
                "y": self.coordinates_y,
                "z": self.coordinates_z,
            } if any([self.coordinates_x, self.coordinates_y, self.coordinates_z]) else None,
            "config": self.config,
            "capabilities": self.capabilities,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Session(Base, UUIDMixin, TimestampMixin):
    """Mô hình phiên để theo dõi các phiên thu thập dữ liệu."""
    __tablename__ = "sessions"

    # Định danh phiên
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Thời gian phiên
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # Trạng thái và cấu hình phiên
    status = Column(String(20), default=SessionStatus.ACTIVE, nullable=False)
    config = Column(JSON, nullable=True)

    # Quan hệ thiết bị
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="sessions")

    # Quan hệ dữ liệu
    csi_data = relationship("CSIData", back_populates="session", cascade="all, delete-orphan")
    pose_detections = relationship("PoseDetection", back_populates="session", cascade="all, delete-orphan")

    # Siêu dữ liệu
    tags = Column(StringArray, nullable=True)
    meta_data = Column(JSON, nullable=True)

    # Thống kê
    total_frames = Column(Integer, default=0, nullable=False)
    processed_frames = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_session_device_id", "device_id"),
        Index("idx_session_status", "status"),
        Index("idx_session_started_at", "started_at"),
        CheckConstraint("status IN ('active', 'completed', 'failed', 'cancelled')", name="check_session_status"),
        CheckConstraint("total_frames >= 0", name="check_total_frames_positive"),
        CheckConstraint("processed_frames >= 0", name="check_processed_frames_positive"),
        CheckConstraint("error_count >= 0", name="check_error_count_positive"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "config": self.config,
            "device_id": str(self.device_id),
            "tags": self.tags,
            "metadata": self.meta_data,
            "total_frames": self.total_frames,
            "processed_frames": self.processed_frames,
            "error_count": self.error_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CSIData(Base, UUIDMixin, TimestampMixin):
    """Mô hình dữ liệu CSI (Thông tin Trạng thái Kênh)."""
    __tablename__ = "csi_data"

    # Định danh dữ liệu
    sequence_number = Column(Integer, nullable=False)
    timestamp_ns = Column(Integer, nullable=False)  # Dấu thời gian nano giây

    # Quan hệ thiết bị và phiên
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)

    device = relationship("Device", back_populates="csi_data")
    session = relationship("Session", back_populates="csi_data")

    # Dữ liệu CSI
    amplitude = Column(FloatArray, nullable=False)
    phase = Column(FloatArray, nullable=False)
    frequency = Column(Float, nullable=False)  # MHz
    bandwidth = Column(Float, nullable=False)  # MHz

    # Đặc tính tín hiệu
    rssi = Column(Float, nullable=True)  # dBm
    snr = Column(Float, nullable=True)   # dB
    noise_floor = Column(Float, nullable=True)  # dBm

    # Thông tin ăng-ten
    tx_antenna = Column(Integer, nullable=True)
    rx_antenna = Column(Integer, nullable=True)
    num_subcarriers = Column(Integer, nullable=False)

    # Trạng thái xử lý
    processing_status = Column(String(20), default=ProcessingStatus.PENDING, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # Số liệu chất lượng
    quality_score = Column(Float, nullable=True)
    is_valid = Column(Boolean, default=True, nullable=False)

    # Siêu dữ liệu
    meta_data = Column(JSON, nullable=True)

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_csi_device_id", "device_id"),
        Index("idx_csi_session_id", "session_id"),
        Index("idx_csi_timestamp", "timestamp_ns"),
        Index("idx_csi_sequence", "sequence_number"),
        Index("idx_csi_processing_status", "processing_status"),
        UniqueConstraint("device_id", "sequence_number", "timestamp_ns", name="uq_csi_device_seq_time"),
        CheckConstraint("frequency > 0", name="check_frequency_positive"),
        CheckConstraint("bandwidth > 0", name="check_bandwidth_positive"),
        CheckConstraint("num_subcarriers > 0", name="check_subcarriers_positive"),
        CheckConstraint("processing_status IN ('pending', 'processing', 'completed', 'failed')", name="check_processing_status"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "sequence_number": self.sequence_number,
            "timestamp_ns": self.timestamp_ns,
            "device_id": str(self.device_id),
            "session_id": str(self.session_id) if self.session_id else None,
            "amplitude": self.amplitude,
            "phase": self.phase,
            "frequency": self.frequency,
            "bandwidth": self.bandwidth,
            "rssi": self.rssi,
            "snr": self.snr,
            "noise_floor": self.noise_floor,
            "tx_antenna": self.tx_antenna,
            "rx_antenna": self.rx_antenna,
            "num_subcarriers": self.num_subcarriers,
            "processing_status": self.processing_status,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "quality_score": self.quality_score,
            "is_valid": self.is_valid,
            "metadata": self.meta_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PoseDetection(Base, UUIDMixin, TimestampMixin):
    """Mô hình kết quả phát hiện tư thế."""
    __tablename__ = "pose_detections"

    # Định danh phát hiện
    frame_number = Column(Integer, nullable=False)
    timestamp_ns = Column(Integer, nullable=False)

    # Quan hệ phiên
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    session = relationship("Session", back_populates="pose_detections")

    # Kết quả phát hiện
    person_count = Column(Integer, default=0, nullable=False)
    keypoints = Column(JSON, nullable=True)  # Mảng điểm khớp của người
    bounding_boxes = Column(JSON, nullable=True)  # Mảng hộp bao

    # Điểm tin cậy
    detection_confidence = Column(Float, nullable=True)
    pose_confidence = Column(Float, nullable=True)
    overall_confidence = Column(Float, nullable=True)

    # Thông tin xử lý
    processing_time_ms = Column(Float, nullable=True)
    model_version = Column(String(50), nullable=True)
    algorithm = Column(String(100), nullable=True)

    # Số liệu chất lượng
    image_quality = Column(Float, nullable=True)
    pose_quality = Column(Float, nullable=True)
    is_valid = Column(Boolean, default=True, nullable=False)

    # Siêu dữ liệu
    meta_data = Column(JSON, nullable=True)

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_pose_session_id", "session_id"),
        Index("idx_pose_timestamp", "timestamp_ns"),
        Index("idx_pose_frame", "frame_number"),
        Index("idx_pose_person_count", "person_count"),
        CheckConstraint("person_count >= 0", name="check_person_count_positive"),
        CheckConstraint("detection_confidence >= 0 AND detection_confidence <= 1", name="check_detection_confidence_range"),
        CheckConstraint("pose_confidence >= 0 AND pose_confidence <= 1", name="check_pose_confidence_range"),
        CheckConstraint("overall_confidence >= 0 AND overall_confidence <= 1", name="check_overall_confidence_range"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "frame_number": self.frame_number,
            "timestamp_ns": self.timestamp_ns,
            "session_id": str(self.session_id),
            "person_count": self.person_count,
            "keypoints": self.keypoints,
            "bounding_boxes": self.bounding_boxes,
            "detection_confidence": self.detection_confidence,
            "pose_confidence": self.pose_confidence,
            "overall_confidence": self.overall_confidence,
            "processing_time_ms": self.processing_time_ms,
            "model_version": self.model_version,
            "algorithm": self.algorithm,
            "image_quality": self.image_quality,
            "pose_quality": self.pose_quality,
            "is_valid": self.is_valid,
            "metadata": self.meta_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SystemMetric(Base, UUIDMixin, TimestampMixin):
    """Mô hình số liệu hệ thống cho giám sát."""
    __tablename__ = "system_metrics"

    # Định danh số liệu
    metric_name = Column(String(255), nullable=False)
    metric_type = Column(String(50), nullable=False)  # counter, gauge, histogram

    # Giá trị số liệu
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=True)

    # Nhãn và thẻ
    labels = Column(JSON, nullable=True)
    tags = Column(StringArray, nullable=True)

    # Thông tin nguồn
    source = Column(String(255), nullable=True)
    component = Column(String(100), nullable=True)

    # Siêu dữ liệu
    description = Column(Text, nullable=True)
    meta_data = Column(JSON, nullable=True)

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_metric_name", "metric_name"),
        Index("idx_metric_type", "metric_type"),
        Index("idx_metric_created_at", "created_at"),
        Index("idx_metric_source", "source"),
        Index("idx_metric_component", "component"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "metric_name": self.metric_name,
            "metric_type": self.metric_type,
            "value": self.value,
            "unit": self.unit,
            "labels": self.labels,
            "tags": self.tags,
            "source": self.source,
            "component": self.component,
            "description": self.description,
            "metadata": self.meta_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Mô hình nhật ký kiểm toán để theo dõi sự kiện hệ thống."""
    __tablename__ = "audit_logs"

    # Thông tin sự kiện
    event_type = Column(String(100), nullable=False)
    event_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Thông tin người dùng và phiên
    user_id = Column(String(255), nullable=True)
    session_id = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Thông tin tài nguyên
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(255), nullable=True)

    # Chi tiết sự kiện
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    changes = Column(JSON, nullable=True)

    # Thông tin kết quả
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)

    # Siêu dữ liệu
    meta_data = Column(JSON, nullable=True)
    tags = Column(StringArray, nullable=True)

    # Ràng buộc và chỉ mục
    __table_args__ = (
        Index("idx_audit_event_type", "event_type"),
        Index("idx_audit_user_id", "user_id"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
        Index("idx_audit_created_at", "created_at"),
        Index("idx_audit_success", "success"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang từ điển."""
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "event_name": self.event_name,
            "description": self.description,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "changes": self.changes,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.meta_data,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Sổ đăng ký mô hình để truy cập dễ dàng
MODEL_REGISTRY = {
    "Device": Device,
    "Session": Session,
    "CSIData": CSIData,
    "PoseDetection": PoseDetection,
    "SystemMetric": SystemMetric,
    "AuditLog": AuditLog,
}


def get_model_by_name(name: str):
    """Lấy lớp mô hình theo tên."""
    return MODEL_REGISTRY.get(name)


def get_all_models() -> List:
    """Lấy tất cả lớp mô hình."""
    return list(MODEL_REGISTRY.values())
