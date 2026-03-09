"""
Giao diện backend cảm biến chung.

Định nghĩa giao thức ``SensingBackend`` và triển khai cụ thể
``CommodityBackend`` kết nối bộ thu thập RSSI, bộ trích xuất đặc trưng
và bộ phân loại thành một pipeline thống nhất.

Enum ``Capability`` liệt kê tất cả khả năng cảm biến có thể.
``CommodityBackend`` báo cáo trung thực rằng nó chỉ hỗ trợ PRESENCE và MOTION.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import List, Optional, Protocol, Set, runtime_checkable

from v1.src.sensing.classifier import MotionLevel, PresenceClassifier, SensingResult
from v1.src.sensing.feature_extractor import RssiFeatureExtractor, RssiFeatures
from v1.src.sensing.rssi_collector import (
    LinuxWifiCollector,
    SimulatedCollector,
    WindowsWifiCollector,
    WifiCollector,
    WifiSample,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enum khả năng
# ---------------------------------------------------------------------------

class Capability(Enum):
    """Tất cả khả năng cảm biến có thể trên các tầng backend."""

    PRESENCE = auto()
    MOTION = auto()
    RESPIRATION = auto()
    LOCATION = auto()
    POSE = auto()


# ---------------------------------------------------------------------------
# Giao thức backend
# ---------------------------------------------------------------------------

@runtime_checkable
class SensingBackend(Protocol):
    """Giao thức mà tất cả backend cảm biến phải triển khai."""

    def get_features(self) -> RssiFeatures:
        """Trích xuất đặc trưng hiện tại từ pipeline cảm biến."""
        ...

    def get_capabilities(self) -> Set[Capability]:
        """Trả về tập hợp khả năng mà backend này hỗ trợ."""
        ...


# ---------------------------------------------------------------------------
# Backend hàng hóa
# ---------------------------------------------------------------------------

class CommodityBackend:
    """
    Backend cảm biến hàng hóa dựa trên RSSI.

    Kết nối:
        - Bộ thu thập WiFi (thực hoặc mô phỏng)
        - Bộ trích xuất đặc trưng RSSI
        - Bộ phân loại hiện diện/chuyển động

    Khả năng: chỉ PRESENCE và MOTION.

    Parameters
    ----------
    collector : đối tượng tương thích WifiCollector
        Nguồn dữ liệu (LinuxWifiCollector hoặc SimulatedCollector).
    extractor : RssiFeatureExtractor, tùy chọn
        Bộ trích xuất đặc trưng (tạo với mặc định nếu không cung cấp).
    classifier : PresenceClassifier, tùy chọn
        Bộ phân loại (tạo với mặc định nếu không cung cấp).
    """

    SUPPORTED_CAPABILITIES: Set[Capability] = frozenset(
        {Capability.PRESENCE, Capability.MOTION}
    )

    def __init__(
        self,
        collector: LinuxWifiCollector | SimulatedCollector | WindowsWifiCollector,
        extractor: Optional[RssiFeatureExtractor] = None,
        classifier: Optional[PresenceClassifier] = None,
    ) -> None:
        self._collector = collector
        self._extractor = extractor or RssiFeatureExtractor()
        self._classifier = classifier or PresenceClassifier()

    @property
    def collector(self) -> LinuxWifiCollector | SimulatedCollector | WindowsWifiCollector:
        return self._collector

    @property
    def extractor(self) -> RssiFeatureExtractor:
        return self._extractor

    @property
    def classifier(self) -> PresenceClassifier:
        return self._classifier

    # -- Giao thức SensingBackend ---------------------------------------------

    def get_features(self) -> RssiFeatures:
        """
        Lấy đặc trưng hiện tại từ các mẫu thu thập mới nhất.

        Sử dụng window_seconds của bộ trích xuất để xác định số lượng mẫu
        cần lấy từ bộ đệm vòng của bộ thu thập.
        """
        window = self._extractor.window_seconds
        sample_rate = self._collector.sample_rate_hz
        n_needed = int(window * sample_rate)
        samples = self._collector.get_samples(n=n_needed)
        return self._extractor.extract(samples)

    def get_capabilities(self) -> Set[Capability]:
        """CommodityBackend chỉ hỗ trợ PRESENCE và MOTION."""
        return set(self.SUPPORTED_CAPABILITIES)

    # -- phương thức tiện ích -------------------------------------------------

    def get_result(self) -> SensingResult:
        """
        Chạy toàn bộ pipeline: thu thập -> trích xuất -> phân loại.

        Returns
        -------
        SensingResult
            Kết quả phân loại với mức chuyển động và độ tin cậy.
        """
        features = self.get_features()
        return self._classifier.classify(features)

    def start(self) -> None:
        """Khởi động bộ thu thập bên dưới."""
        self._collector.start()
        logger.info(
            "CommodityBackend đã khởi động (khả năng: %s)",
            ", ".join(c.name for c in self.SUPPORTED_CAPABILITIES),
        )

    def stop(self) -> None:
        """Dừng bộ thu thập bên dưới."""
        self._collector.stop()
        logger.info("CommodityBackend đã dừng")

    def is_capable(self, capability: Capability) -> bool:
        """Kiểm tra xem backend này có hỗ trợ khả năng cụ thể không."""
        return capability in self.SUPPORTED_CAPABILITIES

    def __repr__(self) -> str:
        caps = ", ".join(c.name for c in sorted(self.SUPPORTED_CAPABILITIES, key=lambda c: c.value))
        return f"CommodityBackend(capabilities=[{caps}])"
