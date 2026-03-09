"""
Cấu hình đặc thù miền nghiệp vụ cho WiFi-DensePose
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

from pydantic import BaseModel, Field, validator


class ZoneType(str, Enum):
    """Các loại khu vực cho phát hiện tư thế."""
    ROOM = "room"
    HALLWAY = "hallway"
    ENTRANCE = "entrance"
    OUTDOOR = "outdoor"
    OFFICE = "office"
    MEETING_ROOM = "meeting_room"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    BEDROOM = "bedroom"
    LIVING_ROOM = "living_room"


class ActivityType(str, Enum):
    """Các loại hoạt động cho phân loại tư thế."""
    STANDING = "standing"
    SITTING = "sitting"
    WALKING = "walking"
    LYING = "lying"
    RUNNING = "running"
    JUMPING = "jumping"
    FALLING = "falling"
    UNKNOWN = "unknown"


class HardwareType(str, Enum):
    """Các loại phần cứng cho thiết bị WiFi."""
    ROUTER = "router"
    ACCESS_POINT = "access_point"
    REPEATER = "repeater"
    MESH_NODE = "mesh_node"
    CUSTOM = "custom"


@dataclass
class ZoneConfig:
    """Cấu hình cho một khu vực phát hiện."""

    zone_id: str
    name: str
    zone_type: ZoneType
    description: Optional[str] = None

    # Ranh giới vật lý (tính bằng mét)
    x_min: float = 0.0
    x_max: float = 10.0
    y_min: float = 0.0
    y_max: float = 10.0
    z_min: float = 0.0
    z_max: float = 3.0

    # Cài đặt phát hiện
    enabled: bool = True
    confidence_threshold: float = 0.5
    max_persons: int = 5
    activity_detection: bool = True

    # Gán phần cứng
    primary_router: Optional[str] = None
    secondary_routers: List[str] = field(default_factory=list)

    # Cài đặt xử lý
    processing_interval: float = 0.1  # giây
    data_retention_hours: int = 24

    # Cài đặt cảnh báo
    enable_alerts: bool = False
    alert_threshold: float = 0.8
    alert_activities: List[ActivityType] = field(default_factory=list)


@dataclass
class RouterConfig:
    """Cấu hình cho một router/thiết bị WiFi."""

    router_id: str
    name: str
    hardware_type: HardwareType

    # Cài đặt mạng
    ip_address: str
    mac_address: str
    interface: str = "wlan0"
    channel: int = 6
    frequency: float = 2.4  # GHz

    # Cài đặt CSI
    csi_enabled: bool = True
    csi_rate: int = 100  # Hz
    csi_subcarriers: int = 56
    antenna_count: int = 3

    # Vị trí (tính bằng mét)
    x_position: float = 0.0
    y_position: float = 0.0
    z_position: float = 2.5  # lắp trần điển hình

    # Hiệu chuẩn
    calibrated: bool = False
    calibration_data: Optional[Dict[str, Any]] = None

    # Trạng thái
    enabled: bool = True
    last_seen: Optional[str] = None

    # Cài đặt hiệu suất
    max_connections: int = 50
    power_level: int = 20  # dBm

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi sang dictionary."""
        return {
            "router_id": self.router_id,
            "name": self.name,
            "hardware_type": self.hardware_type.value,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "interface": self.interface,
            "channel": self.channel,
            "frequency": self.frequency,
            "csi_enabled": self.csi_enabled,
            "csi_rate": self.csi_rate,
            "csi_subcarriers": self.csi_subcarriers,
            "antenna_count": self.antenna_count,
            "position": {
                "x": self.x_position,
                "y": self.y_position,
                "z": self.z_position
            },
            "calibrated": self.calibrated,
            "calibration_data": self.calibration_data,
            "enabled": self.enabled,
            "last_seen": self.last_seen,
            "max_connections": self.max_connections,
            "power_level": self.power_level
        }


class PoseModelConfig(BaseModel):
    """Cấu hình cho các mô hình ước lượng tư thế."""

    model_name: str = Field(..., description="Tên mô hình")
    model_path: str = Field(..., description="Đường dẫn đến file mô hình")
    model_type: str = Field(default="densepose", description="Loại mô hình")

    # Cài đặt đầu vào
    input_width: int = Field(default=256, description="Chiều rộng ảnh đầu vào")
    input_height: int = Field(default=256, description="Chiều cao ảnh đầu vào")
    input_channels: int = Field(default=3, description="Số kênh đầu vào")

    # Cài đặt xử lý
    batch_size: int = Field(default=1, description="Kích thước lô cho suy luận")
    confidence_threshold: float = Field(default=0.5, description="Ngưỡng độ tin cậy")
    nms_threshold: float = Field(default=0.4, description="Ngưỡng NMS")

    # Cài đặt đầu ra
    max_detections: int = Field(default=10, description="Số phát hiện tối đa mỗi khung hình")
    keypoint_count: int = Field(default=17, description="Số điểm mấu chốt")

    # Cài đặt hiệu suất
    use_gpu: bool = Field(default=True, description="Sử dụng tăng tốc GPU")
    gpu_memory_fraction: float = Field(default=0.5, description="Tỷ lệ bộ nhớ GPU")
    num_threads: int = Field(default=4, description="Số luồng CPU")

    @validator("confidence_threshold", "nms_threshold", "gpu_memory_fraction")
    def validate_thresholds(cls, v):
        """Xác thực giá trị ngưỡng."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Ngưỡng phải nằm trong khoảng 0.0 đến 1.0")
        return v


class StreamingConfig(BaseModel):
    """Cấu hình cho truyền phát thời gian thực."""

    # Cài đặt truyền phát
    fps: int = Field(default=30, description="Số khung hình mỗi giây")
    resolution: str = Field(default="720p", description="Độ phân giải truyền phát")
    quality: str = Field(default="medium", description="Chất lượng truyền phát")

    # Cài đặt bộ đệm
    buffer_size: int = Field(default=100, description="Kích thước bộ đệm")
    max_latency_ms: int = Field(default=100, description="Độ trễ tối đa tính bằng mili giây")

    # Cài đặt nén
    compression_enabled: bool = Field(default=True, description="Bật nén")
    compression_level: int = Field(default=5, description="Mức nén (1-9)")

    # Cài đặt WebSocket
    ping_interval: int = Field(default=60, description="Khoảng thời gian ping tính bằng giây")
    timeout: int = Field(default=300, description="Thời gian chờ kết nối tính bằng giây")
    max_connections: int = Field(default=100, description="Số kết nối đồng thời tối đa")

    # Lọc dữ liệu
    min_confidence: float = Field(default=0.5, description="Độ tin cậy tối thiểu cho truyền phát")
    include_metadata: bool = Field(default=True, description="Bao gồm metadata trong luồng")

    @validator("fps")
    def validate_fps(cls, v):
        """Xác thực giá trị FPS."""
        if not 1 <= v <= 60:
            raise ValueError("FPS phải nằm trong khoảng 1 đến 60")
        return v

    @validator("compression_level")
    def validate_compression_level(cls, v):
        """Xác thực mức nén."""
        if not 1 <= v <= 9:
            raise ValueError("Mức nén phải nằm trong khoảng 1 đến 9")
        return v


class AlertConfig(BaseModel):
    """Cấu hình cho cảnh báo và thông báo."""

    # Loại cảnh báo
    enable_pose_alerts: bool = Field(default=False, description="Bật cảnh báo dựa trên tư thế")
    enable_activity_alerts: bool = Field(default=False, description="Bật cảnh báo dựa trên hoạt động")
    enable_zone_alerts: bool = Field(default=False, description="Bật cảnh báo dựa trên khu vực")
    enable_system_alerts: bool = Field(default=True, description="Bật cảnh báo hệ thống")

    # Ngưỡng
    confidence_threshold: float = Field(default=0.8, description="Ngưỡng độ tin cậy cảnh báo")
    duration_threshold: int = Field(default=5, description="Ngưỡng thời gian cảnh báo tính bằng giây")

    # Hoạt động kích hoạt cảnh báo
    alert_activities: List[ActivityType] = Field(
        default=[ActivityType.FALLING],
        description="Các hoạt động kích hoạt cảnh báo"
    )

    # Cài đặt thông báo
    email_enabled: bool = Field(default=False, description="Bật thông báo qua email")
    webhook_enabled: bool = Field(default=False, description="Bật thông báo qua webhook")
    sms_enabled: bool = Field(default=False, description="Bật thông báo qua SMS")

    # Giới hạn tốc độ
    max_alerts_per_hour: int = Field(default=10, description="Số cảnh báo tối đa mỗi giờ")
    cooldown_minutes: int = Field(default=5, description="Thời gian chờ giữa các cảnh báo tương tự")


class DomainConfig:
    """Bộ chứa cấu hình miền nghiệp vụ chính."""

    def __init__(self):
        self.zones: Dict[str, ZoneConfig] = {}
        self.routers: Dict[str, RouterConfig] = {}
        self.pose_models: Dict[str, PoseModelConfig] = {}
        self.streaming = StreamingConfig()
        self.alerts = AlertConfig()

        # Tải cấu hình mặc định
        self._load_defaults()

    def _load_defaults(self):
        """Tải các cấu hình mặc định."""
        # Mô hình tư thế mặc định
        self.pose_models["default"] = PoseModelConfig(
            model_name="densepose_rcnn_R_50_FPN_s1x",
            model_path="./models/densepose_rcnn_R_50_FPN_s1x.pkl",
            model_type="densepose"
        )

        # Khu vực ví dụ
        self.zones["living_room"] = ZoneConfig(
            zone_id="living_room",
            name="Phòng khách",
            zone_type=ZoneType.LIVING_ROOM,
            description="Khu vực sinh hoạt chính",
            x_max=5.0,
            y_max=4.0,
            z_max=3.0
        )

        # Router ví dụ
        self.routers["main_router"] = RouterConfig(
            router_id="main_router",
            name="Router Chính",
            hardware_type=HardwareType.ROUTER,
            ip_address="192.168.1.1",
            mac_address="00:11:22:33:44:55",
            x_position=2.5,
            y_position=2.0,
            z_position=2.5
        )

    def add_zone(self, zone: ZoneConfig):
        """Thêm cấu hình khu vực."""
        self.zones[zone.zone_id] = zone

    def add_router(self, router: RouterConfig):
        """Thêm cấu hình router."""
        self.routers[router.router_id] = router

    def add_pose_model(self, model: PoseModelConfig):
        """Thêm cấu hình mô hình tư thế."""
        self.pose_models[model.model_name] = model

    def get_zone(self, zone_id: str) -> Optional[ZoneConfig]:
        """Lấy cấu hình khu vực theo ID."""
        return self.zones.get(zone_id)

    def get_router(self, router_id: str) -> Optional[RouterConfig]:
        """Lấy cấu hình router theo ID."""
        return self.routers.get(router_id)

    def get_pose_model(self, model_name: str) -> Optional[PoseModelConfig]:
        """Lấy cấu hình mô hình tư thế theo tên."""
        return self.pose_models.get(model_name)

    def get_zones_for_router(self, router_id: str) -> List[ZoneConfig]:
        """Lấy các khu vực sử dụng router cụ thể."""
        zones = []
        for zone in self.zones.values():
            if (zone.primary_router == router_id or
                router_id in zone.secondary_routers):
                zones.append(zone)
        return zones

    def get_routers_for_zone(self, zone_id: str) -> List[RouterConfig]:
        """Lấy các router được gán cho khu vực cụ thể."""
        zone = self.get_zone(zone_id)
        if not zone:
            return []

        routers = []

        # Thêm router chính
        if zone.primary_router and zone.primary_router in self.routers:
            routers.append(self.routers[zone.primary_router])

        # Thêm các router phụ
        for router_id in zone.secondary_routers:
            if router_id in self.routers:
                routers.append(self.routers[router_id])

        return routers

    def get_all_routers(self) -> List[RouterConfig]:
        """Lấy tất cả cấu hình router."""
        return list(self.routers.values())

    def validate_configuration(self) -> List[str]:
        """Xác thực toàn bộ cấu hình."""
        issues = []

        # Xác thực khu vực
        for zone_id, zone in self.zones.items():
            if zone.primary_router and zone.primary_router not in self.routers:
                issues.append(f"Khu vực {zone_id} tham chiếu router chính không xác định: {zone.primary_router}")

            for router_id in zone.secondary_routers:
                if router_id not in self.routers:
                    issues.append(f"Khu vực {zone_id} tham chiếu router phụ không xác định: {router_id}")

        # Xác thực router
        for router_id, router in self.routers.items():
            if not router.ip_address:
                issues.append(f"Router {router_id} thiếu địa chỉ IP")

            if not router.mac_address:
                issues.append(f"Router {router_id} thiếu địa chỉ MAC")

        # Xác thực mô hình tư thế
        for model_name, model in self.pose_models.items():
            import os
            if not os.path.exists(model.model_path):
                issues.append(f"File mô hình tư thế {model_name} không tìm thấy: {model.model_path}")

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển đổi cấu hình sang dictionary."""
        return {
            "zones": {
                zone_id: {
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "zone_type": zone.zone_type.value,
                    "description": zone.description,
                    "boundaries": {
                        "x_min": zone.x_min,
                        "x_max": zone.x_max,
                        "y_min": zone.y_min,
                        "y_max": zone.y_max,
                        "z_min": zone.z_min,
                        "z_max": zone.z_max
                    },
                    "settings": {
                        "enabled": zone.enabled,
                        "confidence_threshold": zone.confidence_threshold,
                        "max_persons": zone.max_persons,
                        "activity_detection": zone.activity_detection
                    },
                    "hardware": {
                        "primary_router": zone.primary_router,
                        "secondary_routers": zone.secondary_routers
                    }
                }
                for zone_id, zone in self.zones.items()
            },
            "routers": {
                router_id: router.to_dict()
                for router_id, router in self.routers.items()
            },
            "pose_models": {
                model_name: model.dict()
                for model_name, model in self.pose_models.items()
            },
            "streaming": self.streaming.dict(),
            "alerts": self.alerts.dict()
        }


@lru_cache()
def get_domain_config() -> DomainConfig:
    """Lấy thể hiện cấu hình miền nghiệp vụ được cache."""
    return DomainConfig()


def load_domain_config_from_file(file_path: str) -> DomainConfig:
    """Tải cấu hình miền nghiệp vụ từ file."""
    import json

    config = DomainConfig()

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        # Tải khu vực
        for zone_data in data.get("zones", []):
            zone = ZoneConfig(**zone_data)
            config.add_zone(zone)

        # Tải router
        for router_data in data.get("routers", []):
            router = RouterConfig(**router_data)
            config.add_router(router)

        # Tải mô hình tư thế
        for model_data in data.get("pose_models", []):
            model = PoseModelConfig(**model_data)
            config.add_pose_model(model)

        # Tải cấu hình truyền phát
        if "streaming" in data:
            config.streaming = StreamingConfig(**data["streaming"])

        # Tải cấu hình cảnh báo
        if "alerts" in data:
            config.alerts = AlertConfig(**data["alerts"])

    except Exception as e:
        raise ValueError(f"Không thể tải cấu hình miền nghiệp vụ: {e}")

    return config


def save_domain_config_to_file(config: DomainConfig, file_path: str):
    """Lưu cấu hình miền nghiệp vụ vào file."""
    import json

    try:
        with open(file_path, 'w') as f:
            json.dump(config.to_dict(), f, indent=2)
    except Exception as e:
        raise ValueError(f"Không thể lưu cấu hình miền nghiệp vụ: {e}")
