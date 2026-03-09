"""
Trích xuất đặc trưng tín hiệu từ chuỗi thời gian RSSI.

Trích xuất cả đặc trưng thống kê miền thời gian và đặc trưng phổ miền tần số
sử dụng toán học thực (scipy.fft, scipy.stats). Cũng triển khai phát hiện
điểm thay đổi CUSUM cho các chuyển tiếp RSSI đột ngột.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from numpy.typing import NDArray
from scipy import fft as scipy_fft
from scipy import stats as scipy_stats

from v1.src.sensing.rssi_collector import WifiSample

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass đặc trưng
# ---------------------------------------------------------------------------

@dataclass
class RssiFeatures:
    """Vùng chứa cho tất cả đặc trưng RSSI đã trích xuất."""

    # -- miền thời gian --------------------------------------------------------
    mean: float = 0.0
    variance: float = 0.0
    std: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    range: float = 0.0
    iqr: float = 0.0              # khoảng tứ phân vị

    # -- miền tần số ---------------------------------------------------
    dominant_freq_hz: float = 0.0
    breathing_band_power: float = 0.0   # 0.1 - 0.5 Hz
    motion_band_power: float = 0.0      # 0.5 - 3.0 Hz
    total_spectral_power: float = 0.0

    # -- điểm thay đổi -------------------------------------------------------
    change_points: List[int] = field(default_factory=list)
    n_change_points: int = 0

    # -- siêu dữ liệu -----------------------------------------------------------
    n_samples: int = 0
    duration_seconds: float = 0.0
    sample_rate_hz: float = 0.0


# ---------------------------------------------------------------------------
# Bộ trích xuất đặc trưng
# ---------------------------------------------------------------------------

class RssiFeatureExtractor:
    """
    Trích xuất đặc trưng miền thời gian và miền tần số từ chuỗi thời gian RSSI.

    Parameters
    ----------
    window_seconds : float
        Độ dài cửa sổ phân tích tính bằng giây (mặc định 30).
    cusum_threshold : float
        Ngưỡng CUSUM cho phát hiện điểm thay đổi (mặc định 3.0 độ lệch chuẩn
        của tín hiệu).
    cusum_drift : float
        Độ trôi cho phép CUSUM (mặc định 0.5 độ lệch chuẩn).
    """

    def __init__(
        self,
        window_seconds: float = 30.0,
        cusum_threshold: float = 3.0,
        cusum_drift: float = 0.5,
    ) -> None:
        self._window_seconds = window_seconds
        self._cusum_threshold = cusum_threshold
        self._cusum_drift = cusum_drift

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def extract(self, samples: List[WifiSample]) -> RssiFeatures:
        """
        Trích xuất đặc trưng từ danh sách đối tượng WifiSample.

        Chỉ sử dụng ``window_seconds`` dữ liệu gần nhất.
        Cần ít nhất 4 mẫu cho đặc trưng có ý nghĩa.
        """
        if len(samples) < 4:
            logger.warning(
                "Không đủ mẫu cho trích xuất đặc trưng (%d < 4)", len(samples)
            )
            return RssiFeatures(n_samples=len(samples))

        # Cắt theo cửa sổ
        samples = self._trim_to_window(samples)
        if len(samples) < 4:
            return RssiFeatures(n_samples=len(samples))
        rssi = np.array([s.rssi_dbm for s in samples], dtype=np.float64)
        timestamps = np.array([s.timestamp for s in samples], dtype=np.float64)

        # Ước lượng tốc độ lấy mẫu từ dấu thời gian thực
        dt = np.diff(timestamps)
        if len(dt) == 0 or np.mean(dt) <= 0:
            sample_rate = 10.0  # dự phòng
        else:
            sample_rate = 1.0 / np.mean(dt)

        duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0

        # Xây dựng đặc trưng
        features = RssiFeatures(
            n_samples=len(rssi),
            duration_seconds=float(duration),
            sample_rate_hz=float(sample_rate),
        )

        self._compute_time_domain(rssi, features)
        self._compute_frequency_domain(rssi, sample_rate, features)
        self._compute_change_points(rssi, features)

        return features

    def extract_from_array(
        self, rssi: NDArray[np.float64], sample_rate_hz: float
    ) -> RssiFeatures:
        """
        Trích xuất đặc trưng trực tiếp từ mảng numpy (hữu ích cho kiểm thử).

        Parameters
        ----------
        rssi : ndarray
            Mảng 1-D giá trị RSSI tính bằng dBm.
        sample_rate_hz : float
            Tốc độ lấy mẫu tính bằng Hz.
        """
        if len(rssi) < 4:
            return RssiFeatures(n_samples=len(rssi))

        duration = len(rssi) / sample_rate_hz

        features = RssiFeatures(
            n_samples=len(rssi),
            duration_seconds=float(duration),
            sample_rate_hz=float(sample_rate_hz),
        )

        self._compute_time_domain(rssi, features)
        self._compute_frequency_domain(rssi, sample_rate_hz, features)
        self._compute_change_points(rssi, features)

        return features

    # -- cắt cửa sổ -----------------------------------------------------

    def _trim_to_window(self, samples: List[WifiSample]) -> List[WifiSample]:
        """Chỉ giữ các mẫu trong ``window_seconds`` gần nhất."""
        if not samples:
            return samples
        latest_ts = samples[-1].timestamp
        cutoff = latest_ts - self._window_seconds
        trimmed = [s for s in samples if s.timestamp >= cutoff]
        return trimmed

    # -- miền thời gian ---------------------------------------------------------

    @staticmethod
    def _compute_time_domain(rssi: NDArray[np.float64], features: RssiFeatures) -> None:
        features.mean = float(np.mean(rssi))
        features.variance = float(np.var(rssi, ddof=1)) if len(rssi) > 1 else 0.0
        features.std = float(np.std(rssi, ddof=1)) if len(rssi) > 1 else 0.0
        features.range = float(np.ptp(rssi))

        # Bảo vệ cho tín hiệu hằng số khi các moment bậc cao không xác định
        if features.std < 1e-12:
            features.skewness = 0.0
            features.kurtosis = 0.0
        else:
            features.skewness = float(scipy_stats.skew(rssi, bias=False)) if len(rssi) > 2 else 0.0
            features.kurtosis = float(scipy_stats.kurtosis(rssi, bias=False)) if len(rssi) > 3 else 0.0

        q75, q25 = np.percentile(rssi, [75, 25])
        features.iqr = float(q75 - q25)

    # -- miền tần số ----------------------------------------------------

    @staticmethod
    def _compute_frequency_domain(
        rssi: NDArray[np.float64],
        sample_rate: float,
        features: RssiFeatures,
    ) -> None:
        """Tính phổ công suất FFT một phía và trích xuất công suất băng."""
        n = len(rssi)
        if n < 4:
            return

        # Loại bỏ DC (trừ trung bình)
        signal = rssi - np.mean(rssi)

        # Áp dụng cửa sổ Hann để giảm rò phổ
        window = np.hanning(n)
        windowed = signal * window

        # Tính FFT thực
        fft_vals = scipy_fft.rfft(windowed)
        freqs = scipy_fft.rfftfreq(n, d=1.0 / sample_rate)

        # Mật độ phổ công suất (bình phương biên độ, chuẩn hóa theo N)
        psd = (np.abs(fft_vals) ** 2) / n

        # Bỏ qua thành phần DC (chỉ mục 0)
        if len(freqs) > 1:
            freqs_no_dc = freqs[1:]
            psd_no_dc = psd[1:]
        else:
            return

        # Tổng công suất phổ
        features.total_spectral_power = float(np.sum(psd_no_dc))

        # Tần số chủ đạo
        if len(psd_no_dc) > 0:
            peak_idx = int(np.argmax(psd_no_dc))
            features.dominant_freq_hz = float(freqs_no_dc[peak_idx])

        # Công suất băng
        features.breathing_band_power = float(
            _band_power(freqs_no_dc, psd_no_dc, 0.1, 0.5)
        )
        features.motion_band_power = float(
            _band_power(freqs_no_dc, psd_no_dc, 0.5, 3.0)
        )

    # -- phát hiện điểm thay đổi (CUSUM) --------------------------------------

    def _compute_change_points(
        self, rssi: NDArray[np.float64], features: RssiFeatures
    ) -> None:
        """
        Phát hiện điểm thay đổi sử dụng thuật toán CUSUM.

        Thống kê CUSUM theo dõi độ lệch tích lũy từ trung bình,
        đánh dấu các điểm nơi trung bình tín hiệu thay đổi đột ngột.
        """
        if len(rssi) < 4:
            return

        mean_val = np.mean(rssi)
        std_val = np.std(rssi, ddof=1)
        if std_val < 1e-12:
            features.change_points = []
            features.n_change_points = 0
            return

        threshold = self._cusum_threshold * std_val
        drift = self._cusum_drift * std_val

        change_points = cusum_detect(rssi, mean_val, threshold, drift)
        features.change_points = change_points
        features.n_change_points = len(change_points)


# ---------------------------------------------------------------------------
# Hàm trợ giúp
# ---------------------------------------------------------------------------

def _band_power(
    freqs: NDArray[np.float64],
    psd: NDArray[np.float64],
    low_hz: float,
    high_hz: float,
) -> float:
    """Tính tổng PSD trong băng tần [low_hz, high_hz]."""
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return float(np.sum(psd[mask]))


def cusum_detect(
    signal: NDArray[np.float64],
    target: float,
    threshold: float,
    drift: float,
) -> List[int]:
    """
    Phát hiện điểm thay đổi CUSUM (tổng tích lũy).

    Phát hiện cả dịch chuyển hướng lên và hướng xuống trong trung bình tín hiệu.

    Parameters
    ----------
    signal : ndarray
        Tín hiệu 1-D cần phân tích.
    target : float
        Trung bình kỳ vọng của tín hiệu.
    threshold : float
        Ngưỡng quyết định để tuyên bố điểm thay đổi.
    drift : float
        Độ trôi cho phép trước khi tích lũy độ lệch.

    Returns
    -------
    danh sách int
        Các chỉ mục nơi phát hiện điểm thay đổi.
    """
    n = len(signal)
    s_pos = 0.0
    s_neg = 0.0
    change_points: List[int] = []

    for i in range(n):
        deviation = signal[i] - target
        s_pos = max(0.0, s_pos + deviation - drift)
        s_neg = max(0.0, s_neg - deviation - drift)

        if s_pos > threshold or s_neg > threshold:
            change_points.append(i)
            # Đặt lại sau khi phát hiện để tìm thay đổi tiếp theo
            s_pos = 0.0
            s_neg = 0.0

    return change_points
