"""
Phân loại hiện diện và chuyển động từ đặc trưng RSSI.

Sử dụng logic dựa trên quy tắc với ngưỡng có thể cấu hình để phân loại
trạng thái cảm biến hiện tại thành một trong ba mức chuyển động:
    ABSENT        -- không phát hiện người
    PRESENT_STILL -- có người nhưng đứng yên
    ACTIVE        -- có người và đang di chuyển

Độ tin cậy được tính từ cường độ đặc trưng phổ và sự đồng thuận
chéo bộ thu tùy chọn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from v1.src.sensing.feature_extractor import RssiFeatures

logger = logging.getLogger(__name__)


class MotionLevel(Enum):
    """Trạng thái chuyển động đã phân loại."""

    ABSENT = "absent"
    PRESENT_STILL = "present_still"
    ACTIVE = "active"


@dataclass
class SensingResult:
    """Đầu ra của bộ phân loại hiện diện/chuyển động."""

    motion_level: MotionLevel
    confidence: float                 # 0.0 đến 1.0
    presence_detected: bool
    rssi_variance: float
    motion_band_energy: float
    breathing_band_energy: float
    n_change_points: int
    details: str = ""


class PresenceClassifier:
    """
    Bộ phân loại hiện diện và chuyển động dựa trên quy tắc.

    Quy tắc phân loại
    ------------------
    1. **Hiện diện**: Phương sai RSSI vượt ``presence_variance_threshold``.
    2. **Mức chuyển động**:
       - ABSENT  nếu phương sai < ngưỡng hiện diện
       - ACTIVE  nếu phương sai >= ngưỡng hiện diện VÀ năng lượng băng chuyển động
         vượt ``motion_energy_threshold``
       - PRESENT_STILL trong các trường hợp còn lại (phương sai trên ngưỡng nhưng năng lượng chuyển động thấp)

    Mô hình độ tin cậy
    -------------------
    Độ tin cậy cơ sở đến từ mức độ phương sai / năng lượng đo được vượt qua
    các ngưỡng tương ứng. Sự đồng thuận chéo bộ thu (khi nhiều bộ thu
    báo cáo kết quả) có thể tăng thêm độ tin cậy.

    Parameters
    ----------
    presence_variance_threshold : float
        Phương sai RSSI tối thiểu (dBm^2) để tuyên bố hiện diện (mặc định 0.5).
    motion_energy_threshold : float
        Năng lượng phổ băng chuyển động tối thiểu để phân loại là ACTIVE (mặc định 0.1).
    max_receivers : int
        Số lượng bộ thu tối đa cho sự đồng thuận chéo bộ thu (mặc định 1).
    """

    def __init__(
        self,
        presence_variance_threshold: float = 0.5,
        motion_energy_threshold: float = 0.1,
        max_receivers: int = 1,
    ) -> None:
        self._var_thresh = presence_variance_threshold
        self._motion_thresh = motion_energy_threshold
        self._max_receivers = max_receivers

    @property
    def presence_variance_threshold(self) -> float:
        return self._var_thresh

    @property
    def motion_energy_threshold(self) -> float:
        return self._motion_thresh

    def classify(
        self,
        features: RssiFeatures,
        other_receiver_results: Optional[List[SensingResult]] = None,
    ) -> SensingResult:
        """
        Phân loại hiện diện và chuyển động từ đặc trưng RSSI đã trích xuất.

        Parameters
        ----------
        features : RssiFeatures
            Đặc trưng trích xuất từ chuỗi thời gian RSSI của một bộ thu.
        other_receiver_results : danh sách SensingResult, tùy chọn
            Kết quả từ các bộ thu khác cho sự đồng thuận chéo bộ thu.

        Returns
        -------
        SensingResult
        """
        variance = features.variance
        motion_energy = features.motion_band_power
        breathing_energy = features.breathing_band_power

        # -- quyết định hiện diện ------------------------------------------------
        presence = variance >= self._var_thresh

        # -- mức chuyển động -----------------------------------------------------
        if not presence:
            level = MotionLevel.ABSENT
        elif motion_energy >= self._motion_thresh:
            level = MotionLevel.ACTIVE
        else:
            level = MotionLevel.PRESENT_STILL

        # -- độ tin cậy -----------------------------------------------------------
        confidence = self._compute_confidence(
            variance, motion_energy, breathing_energy, level, other_receiver_results
        )

        # -- chuỗi chi tiết -------------------------------------------------------
        details = (
            f"var={variance:.4f} (thresh={self._var_thresh}), "
            f"motion_energy={motion_energy:.4f} (thresh={self._motion_thresh}), "
            f"breathing_energy={breathing_energy:.4f}, "
            f"change_points={features.n_change_points}"
        )

        return SensingResult(
            motion_level=level,
            confidence=confidence,
            presence_detected=presence,
            rssi_variance=variance,
            motion_band_energy=motion_energy,
            breathing_band_energy=breathing_energy,
            n_change_points=features.n_change_points,
            details=details,
        )

    def _compute_confidence(
        self,
        variance: float,
        motion_energy: float,
        breathing_energy: float,
        level: MotionLevel,
        other_results: Optional[List[SensingResult]],
    ) -> float:
        """
        Tính điểm tin cậy trong [0, 1].

        Điểm số bao gồm:
            - Cơ sở (60%): mức độ phương sai rõ ràng vượt qua (hoặc dưới)
              ngưỡng hiện diện.
            - Phổ (20%): cường độ của băng phổ liên quan.
            - Đồng thuận (20%): sự nhất quán chéo bộ thu (nếu có).
        """
        # -- độ tin cậy cơ sở (0..1) ------------------------------------------
        if level == MotionLevel.ABSENT:
            # Độ tin cậy vắng mặt tăng khi phương sai giảm so với ngưỡng
            if self._var_thresh > 0:
                base = max(0.0, 1.0 - variance / self._var_thresh)
            else:
                base = 1.0
        else:
            # Độ tin cậy hiện diện tăng khi phương sai vượt ngưỡng
            ratio = variance / self._var_thresh if self._var_thresh > 0 else 10.0
            base = min(1.0, ratio)

        # -- độ tin cậy phổ (0..1) --------------------------------------
        if level == MotionLevel.ACTIVE:
            spectral = min(1.0, motion_energy / max(self._motion_thresh, 1e-12))
        elif level == MotionLevel.PRESENT_STILL:
            # Đối với đứng yên, năng lượng băng hô hấp liên quan hơn
            spectral = min(1.0, breathing_energy / max(self._motion_thresh, 1e-12))
        else:
            spectral = 1.0  # Không yêu cầu phổ cho vắng mặt

        # -- đồng thuận chéo bộ thu (0..1) ---------------------------------
        agreement = 1.0  # mặc định: một bộ thu
        if other_results:
            same_level = sum(
                1 for r in other_results if r.motion_level == level
            )
            agreement = (same_level + 1) / (len(other_results) + 1)

        # Kết hợp có trọng số
        confidence = 0.6 * base + 0.2 * spectral + 0.2 * agreement
        return max(0.0, min(1.0, confidence))
