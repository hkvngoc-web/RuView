"""
Module Cảm Biến WiFi Thương Phẩm (ADR-013)
============================================

Phát hiện sự hiện diện và chuyển động dựa trên RSSI sử dụng các chỉ số WiFi Linux tiêu chuẩn.
Module này cung cấp xử lý tín hiệu thực từ phần cứng WiFi thương phẩm,
trích xuất các đặc trưng hiện diện và chuyển động từ chuỗi thời gian RSSI.

Thành phần:
    - rssi_collector: Thu thập dữ liệu từ giao diện WiFi Linux
    - feature_extractor: Trích xuất đặc trưng miền thời gian và miền tần số
    - classifier: Phân loại hiện diện và chuyển động từ đặc trưng
    - backend: Giao diện backend cảm biến chung

Khả năng:
    - PRESENCE: Phát hiện có người hiện diện trong vùng cảm biến hay không
    - MOTION: Phân loại mức chuyển động (vắng mặt / đứng yên / hoạt động)

Lưu ý: Module này chỉ sử dụng RSSI. Để cảm biến độ trung thực cao hơn (hô hấp,
ước lượng tư thế), cần phần cứng có khả năng CSI và đường ống DensePose đầy đủ.
"""

from v1.src.sensing.rssi_collector import (
    LinuxWifiCollector,
    SimulatedCollector,
    WindowsWifiCollector,
    WifiSample,
)
from v1.src.sensing.feature_extractor import (
    RssiFeatureExtractor,
    RssiFeatures,
)
from v1.src.sensing.classifier import (
    PresenceClassifier,
    SensingResult,
    MotionLevel,
)
from v1.src.sensing.backend import (
    SensingBackend,
    CommodityBackend,
    Capability,
)

__all__ = [
    "LinuxWifiCollector",
    "SimulatedCollector",
    "WindowsWifiCollector",
    "WifiSample",
    "RssiFeatureExtractor",
    "RssiFeatures",
    "PresenceClassifier",
    "SensingResult",
    "MotionLevel",
    "SensingBackend",
    "CommodityBackend",
    "Capability",
]
