"""
Thu thập dữ liệu RSSI từ giao diện WiFi Linux.

Cung cấp hai bộ thu thập cụ thể:
    - LinuxWifiCollector: đọc RSSI thực từ /proc/net/wireless và lệnh iw
    - SimulatedCollector: tạo tín hiệu tổng hợp xác định cho kiểm thử

Cả hai đều chia sẻ cùng dataclass WifiSample và bộ đệm vòng an toàn luồng.
"""

from __future__ import annotations

import logging
import math
import os
import platform
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Protocol, Union

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kiểu dữ liệu
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WifiSample:
    """Một mẫu đo WiFi đơn lẻ."""

    timestamp: float          # Giây epoch UNIX (time.time())
    rssi_dbm: float           # Cường độ tín hiệu nhận được tính bằng dBm
    noise_dbm: float          # Sàn nhiễu tính bằng dBm
    link_quality: float       # Chất lượng liên kết 0-1 (đã chuẩn hóa)
    tx_bytes: int             # Tổng byte TX tích lũy
    rx_bytes: int             # Tổng byte RX tích lũy
    retry_count: int          # Tổng số lần thử lại tích lũy
    interface: str            # Tên giao diện WiFi


# ---------------------------------------------------------------------------
# Bộ đệm vòng an toàn luồng
# ---------------------------------------------------------------------------

class RingBuffer:
    """Bộ đệm vòng kích thước cố định an toàn luồng cho đối tượng WifiSample."""

    def __init__(self, max_size: int) -> None:
        self._buf: Deque[WifiSample] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def append(self, sample: WifiSample) -> None:
        with self._lock:
            self._buf.append(sample)

    def get_all(self) -> List[WifiSample]:
        """Trả về bản chụp tất cả mẫu (cũ nhất trước)."""
        with self._lock:
            return list(self._buf)

    def get_last_n(self, n: int) -> List[WifiSample]:
        """Trả về *n* mẫu gần nhất."""
        with self._lock:
            items = list(self._buf)
            return items[-n:] if n < len(items) else items

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# ---------------------------------------------------------------------------
# Giao thức bộ thu thập
# ---------------------------------------------------------------------------

class WifiCollector(Protocol):
    """Giao thức mà tất cả bộ thu thập WiFi phải tuân thủ."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]: ...
    @property
    def sample_rate_hz(self) -> float: ...


# ---------------------------------------------------------------------------
# Bộ thu thập WiFi Linux (phần cứng thực)
# ---------------------------------------------------------------------------

class LinuxWifiCollector:
    """
    Thu thập dữ liệu RSSI thực từ giao diện WiFi Linux.

    Nguồn dữ liệu:
        - /proc/net/wireless  (RSSI, nhiễu, chất lượng liên kết)
        - iw dev <iface> station dump  (byte TX/RX, số lần thử lại)

    Parameters
    ----------
    interface : str
        Tên giao diện WiFi, ví dụ ``"wlan0"``.
    sample_rate_hz : float
        Tốc độ lấy mẫu mục tiêu tính bằng Hz (mặc định 10).
    buffer_seconds : int
        Số giây lịch sử giữ trong bộ đệm vòng (mặc định 120).
    """

    def __init__(
        self,
        interface: str = "wlan0",
        sample_rate_hz: float = 10.0,
        buffer_seconds: int = 120,
    ) -> None:
        self._interface = interface
        self._rate = sample_rate_hz
        self._buffer = RingBuffer(max_size=int(sample_rate_hz * buffer_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # -- API công khai -------------------------------------------------------

    @property
    def sample_rate_hz(self) -> float:
        return self._rate

    def start(self) -> None:
        """Khởi động luồng lấy mẫu nền."""
        if self._running:
            return
        self._validate_interface()
        self._running = True
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="wifi-rssi-collector"
        )
        self._thread.start()
        logger.info(
            "LinuxWifiCollector đã khởi động trên %s ở %.1f Hz",
            self._interface,
            self._rate,
        )

    def stop(self) -> None:
        """Dừng luồng lấy mẫu nền."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("LinuxWifiCollector đã dừng")

    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]:
        """
        Trả về các mẫu đã thu thập.

        Parameters
        ----------
        n : int hoặc None
            Nếu được cung cấp, chỉ trả về *n* mẫu gần nhất.
        """
        if n is not None:
            return self._buffer.get_last_n(n)
        return self._buffer.get_all()

    def collect_once(self) -> WifiSample:
        """Thu thập một mẫu đơn lẻ ngay lập tức (chặn)."""
        return self._read_sample()

    # -- kiểm tra khả dụng --------------------------------------------------

    @classmethod
    def is_available(cls, interface: str = "wlan0") -> tuple[bool, str]:
        """Kiểm tra xem có thể thu thập WiFi Linux mà không ném lỗi hay không.

        Returns
        -------
        (available, reason) : tuple[bool, str]
            ``available`` là True khi /proc/net/wireless tồn tại và liệt kê
            giao diện được yêu cầu. ``reason`` là giải thích dễ đọc khi
            không khả dụng.
        """
        if not os.path.exists("/proc/net/wireless"):
            return False, (
                "Không tìm thấy /proc/net/wireless. "
                "Môi trường này không có hệ thống con không dây Linux "
                "(phổ biến trong Docker, WSL, hoặc máy chủ headless)."
            )
        try:
            with open("/proc/net/wireless", "r") as f:
                content = f.read()
        except OSError as exc:
            return False, f"Không thể đọc /proc/net/wireless: {exc}"

        if interface not in content:
            names = cls._parse_interface_names(content)
            return False, (
                f"Giao diện '{interface}' không được liệt kê trong /proc/net/wireless. "
                f"Khả dụng: {names or '(không có)'}. "
                f"Đảm bảo giao diện đang hoạt động và đã kết nối với AP."
            )
        return True, "ok"

    # -- nội bộ --------------------------------------------------------------

    def _validate_interface(self) -> None:
        """Kiểm tra giao diện tồn tại trên máy này."""
        available, reason = self.is_available(self._interface)
        if not available:
            raise RuntimeError(reason)

    @staticmethod
    def _parse_interface_names(proc_content: str) -> List[str]:
        """Trích xuất tên giao diện từ nội dung /proc/net/wireless."""
        names: List[str] = []
        for line in proc_content.splitlines()[2:]:  # bỏ qua dòng tiêu đề
            parts = line.split(":")
            if len(parts) >= 2:
                names.append(parts[0].strip())
        return names

    def _sample_loop(self) -> None:
        interval = 1.0 / self._rate
        while self._running:
            t0 = time.monotonic()
            try:
                sample = self._read_sample()
                self._buffer.append(sample)
            except Exception:
                logger.exception("Lỗi khi đọc mẫu WiFi")
            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _read_sample(self) -> WifiSample:
        """Đọc một mẫu từ hệ điều hành."""
        rssi, noise, quality = self._read_proc_wireless()
        tx_bytes, rx_bytes, retries = self._read_iw_station()
        return WifiSample(
            timestamp=time.time(),
            rssi_dbm=rssi,
            noise_dbm=noise,
            link_quality=quality,
            tx_bytes=tx_bytes,
            rx_bytes=rx_bytes,
            retry_count=retries,
            interface=self._interface,
        )

    def _read_proc_wireless(self) -> tuple[float, float, float]:
        """Phân tích /proc/net/wireless cho giao diện đã cấu hình."""
        try:
            with open("/proc/net/wireless", "r") as f:
                for line in f:
                    if self._interface in line:
                        # Định dạng: iface: status quality signal noise ...
                        parts = line.split()
                        # parts[0] = "wlan0:", parts[2]=quality, parts[3]=signal, parts[4]=noise
                        quality_raw = float(parts[2].rstrip("."))
                        signal_raw = float(parts[3].rstrip("."))
                        noise_raw = float(parts[4].rstrip("."))
                        # Chuẩn hóa chất lượng về 0..1 (tối đa thường là 70)
                        quality = min(1.0, max(0.0, quality_raw / 70.0))
                        return signal_raw, noise_raw, quality
        except (FileNotFoundError, IndexError, ValueError) as exc:
            raise RuntimeError(
                f"Không thể đọc /proc/net/wireless cho {self._interface}: {exc}"
            ) from exc
        raise RuntimeError(
            f"Không tìm thấy giao diện {self._interface} trong /proc/net/wireless"
        )

    def _read_iw_station(self) -> tuple[int, int, int]:
        """Chạy ``iw dev <iface> station dump`` và phân tích TX/RX/thử lại."""
        try:
            result = subprocess.run(
                ["iw", "dev", self._interface, "station", "dump"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            text = result.stdout

            tx_bytes = self._extract_int(text, r"tx bytes:\s*(\d+)")
            rx_bytes = self._extract_int(text, r"rx bytes:\s*(\d+)")
            retries = self._extract_int(text, r"tx retries:\s*(\d+)")
            return tx_bytes, rx_bytes, retries
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # iw chưa cài đặt hoặc hết thời gian -- giảm cấp nhẹ nhàng
            return 0, 0, 0

    @staticmethod
    def _extract_int(text: str, pattern: str) -> int:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Bộ thu thập mô phỏng (xác định, cho kiểm thử)
# ---------------------------------------------------------------------------

class SimulatedCollector:
    """
    Bộ thu thập WiFi mô phỏng xác định cho kiểm thử.

    Tạo tín hiệu RSSI tổng hợp bao gồm:
        - Một đường cơ sở hằng số (-50 dBm mặc định)
        - Một thành phần hình sin tùy chọn (tần số/biên độ có thể cấu hình)
        - Tiêm thay đổi bước tùy chọn (cho kiểm thử điểm thay đổi)
        - Nhiễu xác định từ PRNG có hạt giống

    Đây rõ ràng là công cụ kiểm thử/phát triển và không cố gắng
    giả dạng phần cứng thực.

    Parameters
    ----------
    seed : int
        Hạt giống ngẫu nhiên cho đầu ra xác định.
    sample_rate_hz : float
        Tốc độ lấy mẫu mục tiêu tính bằng Hz (mặc định 10).
    buffer_seconds : int
        Dung lượng bộ đệm vòng tính bằng giây (mặc định 120).
    baseline_dbm : float
        Đường cơ sở RSSI tính bằng dBm (mặc định -50).
    sine_freq_hz : float
        Tần số thành phần hình sin RSSI (mặc định 0.3 Hz, băng hô hấp).
    sine_amplitude_dbm : float
        Biên độ thành phần hình sin (mặc định 2.0 dBm).
    noise_std_dbm : float
        Độ lệch chuẩn nhiễu Gaussian cộng (mặc định 0.5 dBm).
    step_change_at : float hoặc None
        Nếu đặt, tiêm thay đổi bước ``step_change_dbm`` tại độ lệch thời gian
        này (giây từ khi bắt đầu).
    step_change_dbm : float
        Độ lớn thay đổi bước (mặc định -10 dBm).
    """

    def __init__(
        self,
        seed: int = 42,
        sample_rate_hz: float = 10.0,
        buffer_seconds: int = 120,
        baseline_dbm: float = -50.0,
        sine_freq_hz: float = 0.3,
        sine_amplitude_dbm: float = 2.0,
        noise_std_dbm: float = 0.5,
        step_change_at: Optional[float] = None,
        step_change_dbm: float = -10.0,
    ) -> None:
        self._rate = sample_rate_hz
        self._buffer = RingBuffer(max_size=int(sample_rate_hz * buffer_seconds))
        self._rng = np.random.default_rng(seed)

        self._baseline = baseline_dbm
        self._sine_freq = sine_freq_hz
        self._sine_amp = sine_amplitude_dbm
        self._noise_std = noise_std_dbm
        self._step_at = step_change_at
        self._step_dbm = step_change_dbm

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._sample_index: int = 0

    # -- API công khai -------------------------------------------------------

    @property
    def sample_rate_hz(self) -> float:
        return self._rate

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._sample_index = 0
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="sim-rssi-collector"
        )
        self._thread.start()
        logger.info("SimulatedCollector đã khởi động ở %.1f Hz (hạt giống tái sử dụng từ khởi tạo)", self._rate)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]:
        if n is not None:
            return self._buffer.get_last_n(n)
        return self._buffer.get_all()

    def generate_samples(self, duration_seconds: float) -> List[WifiSample]:
        """
        Tạo một loạt mẫu mà không cần luồng nền.

        Hữu ích cho kiểm thử đơn vị cần tín hiệu đã biết mà không có jitter thời gian.

        Parameters
        ----------
        duration_seconds : float
            Số giây tín hiệu cần tạo.

        Returns
        -------
        danh sách WifiSample
        """
        n_samples = int(duration_seconds * self._rate)
        samples: List[WifiSample] = []
        base_time = time.time()
        for i in range(n_samples):
            t = i / self._rate
            sample = self._make_sample(base_time + t, t, i)
            samples.append(sample)
        return samples

    # -- nội bộ --------------------------------------------------------------

    def _sample_loop(self) -> None:
        interval = 1.0 / self._rate
        while self._running:
            t0 = time.monotonic()
            now = time.time()
            t_offset = now - self._start_time
            sample = self._make_sample(now, t_offset, self._sample_index)
            self._buffer.append(sample)
            self._sample_index += 1
            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _make_sample(self, timestamp: float, t_offset: float, index: int) -> WifiSample:
        """Xây dựng một mẫu xác định."""
        # Thành phần hình sin
        sine = self._sine_amp * math.sin(2.0 * math.pi * self._sine_freq * t_offset)

        # Nhiễu Gaussian xác định (sử dụng RNG có hạt giống)
        noise = self._rng.normal(0.0, self._noise_std)

        # Thay đổi bước
        step = 0.0
        if self._step_at is not None and t_offset >= self._step_at:
            step = self._step_dbm

        rssi = self._baseline + sine + noise + step

        return WifiSample(
            timestamp=timestamp,
            rssi_dbm=float(rssi),
            noise_dbm=-95.0,
            link_quality=max(0.0, min(1.0, (rssi + 100.0) / 60.0)),
            tx_bytes=index * 1500,
            rx_bytes=index * 3000,
            retry_count=max(0, index // 100),
            interface="sim0",
        )


# ---------------------------------------------------------------------------
# Bộ thu thập WiFi Windows (phần cứng thực qua netsh)
# ---------------------------------------------------------------------------

class WindowsWifiCollector:
    """
    Thu thập dữ liệu RSSI thực từ giao diện WiFi Windows.

    Nguồn dữ liệu: ``netsh wlan show interfaces`` cung cấp RSSI tính bằng dBm,
    phần trăm chất lượng tín hiệu, kênh, băng tần, và trạng thái kết nối.

    Parameters
    ----------
    interface : str
        Tên giao diện WiFi (mặc định ``"Wi-Fi"``). Phải khớp với trường ``Name``
        hiển thị bởi ``netsh wlan show interfaces``.
    sample_rate_hz : float
        Tốc độ lấy mẫu mục tiêu tính bằng Hz (mặc định 2.0). ``netsh`` Windows chậm
        (~200-400ms mỗi lần gọi) nên tốc độ trên 2 Hz có thể không đạt được.
    buffer_seconds : int
        Dung lượng bộ đệm vòng tính bằng giây (mặc định 120).
    """

    def __init__(
        self,
        interface: str = "Wi-Fi",
        sample_rate_hz: float = 2.0,
        buffer_seconds: int = 120,
    ) -> None:
        self._interface = interface
        self._rate = sample_rate_hz
        self._buffer = RingBuffer(max_size=int(sample_rate_hz * buffer_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cumulative_tx: int = 0
        self._cumulative_rx: int = 0

    # -- API công khai -------------------------------------------------------

    @property
    def sample_rate_hz(self) -> float:
        return self._rate

    def start(self) -> None:
        if self._running:
            return
        self._validate_interface()
        self._running = True
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="win-rssi-collector"
        )
        self._thread.start()
        logger.info(
            "WindowsWifiCollector đã khởi động trên '%s' ở %.1f Hz",
            self._interface,
            self._rate,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("WindowsWifiCollector đã dừng")

    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]:
        if n is not None:
            return self._buffer.get_last_n(n)
        return self._buffer.get_all()

    def collect_once(self) -> WifiSample:
        return self._read_sample()

    # -- nội bộ --------------------------------------------------------------

    def _validate_interface(self) -> None:
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5.0,
            )
            if self._interface not in result.stdout:
                raise RuntimeError(
                    f"Không tìm thấy giao diện WiFi '{self._interface}'. "
                    f"Kiểm tra 'netsh wlan show interfaces' để biết tên chính xác."
                )
            if "disconnected" in result.stdout.lower().split(self._interface.lower())[1][:200]:
                raise RuntimeError(
                    f"Giao diện WiFi '{self._interface}' đã ngắt kết nối. "
                    f"Hãy kết nối với mạng WiFi trước."
                )
        except FileNotFoundError:
            raise RuntimeError(
                "Không tìm thấy netsh. Bộ thu thập này yêu cầu Windows."
            )

    def _sample_loop(self) -> None:
        interval = 1.0 / self._rate
        while self._running:
            t0 = time.monotonic()
            try:
                sample = self._read_sample()
                self._buffer.append(sample)
            except Exception:
                logger.exception("Lỗi khi đọc mẫu WiFi")
            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _read_sample(self) -> WifiSample:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=5.0,
        )
        rssi = -80.0
        signal_pct = 0.0

        for line in result.stdout.splitlines():
            stripped = line.strip()
            # Dòng "Rssi" chứa giá trị dBm thô (khả dụng trên Win10+)
            if stripped.lower().startswith("rssi"):
                try:
                    rssi = float(stripped.split(":")[1].strip())
                except (IndexError, ValueError):
                    pass
            # Dòng "Signal" chứa phần trăm (luôn khả dụng)
            elif stripped.lower().startswith("signal"):
                try:
                    pct_str = stripped.split(":")[1].strip().rstrip("%")
                    signal_pct = float(pct_str)
                    # Nếu dòng RSSI bị thiếu, ước lượng từ phần trăm
                    # Signal% ánh xạ xấp xỉ: 100% ≈ -30 dBm, 0% ≈ -90 dBm
                except (IndexError, ValueError):
                    pass

        # Chuẩn hóa chất lượng liên kết từ phần trăm tín hiệu
        link_quality = signal_pct / 100.0

        # Ước lượng sàn nhiễu (Windows không công khai trực tiếp)
        noise_dbm = -95.0

        # Theo dõi byte tích lũy (không khả dụng từ netsh; tăng bộ đếm tổng hợp)
        self._cumulative_tx += 1500
        self._cumulative_rx += 3000

        return WifiSample(
            timestamp=time.time(),
            rssi_dbm=rssi,
            noise_dbm=noise_dbm,
            link_quality=link_quality,
            tx_bytes=self._cumulative_tx,
            rx_bytes=self._cumulative_rx,
            retry_count=0,
            interface=self._interface,
        )


# ---------------------------------------------------------------------------
# Bộ thu thập WiFi macOS (phần cứng thực qua tiện ích Swift CoreWLAN)
# ---------------------------------------------------------------------------

class MacosWifiCollector:
    """
    Thu thập dữ liệu RSSI thực từ giao diện WiFi macOS bằng tiện ích Swift.

    Nguồn dữ liệu: Một tệp nhị phân Swift nhỏ đã biên dịch (`mac_wifi`) thăm dò
    CoreWLAN `CWWiFiClient.shared().interface()` ở tốc độ cao.
    """

    def __init__(
        self,
        sample_rate_hz: float = 10.0,
        buffer_seconds: int = 120,
    ) -> None:
        self._rate = sample_rate_hz
        self._buffer = RingBuffer(max_size=int(sample_rate_hz * buffer_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._interface = "en0"  # CoreWLAN tự động nhắm vào giao diện Wi-Fi đang hoạt động

        # Biên dịch tiện ích Swift nếu tệp nhị phân chưa tồn tại
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.swift_src = os.path.join(base_dir, "mac_wifi.swift")
        self.swift_bin = os.path.join(base_dir, "mac_wifi")

    # -- API công khai -------------------------------------------------------

    @property
    def sample_rate_hz(self) -> float:
        return self._rate

    def start(self) -> None:
        if self._running:
            return

        # Đảm bảo tệp nhị phân tồn tại
        import os
        if not os.path.exists(self.swift_bin):
            logger.info("Đang biên dịch mac_wifi.swift sang %s", self.swift_bin)
            try:
                subprocess.run(["swiftc", "-O", "-o", self.swift_bin, self.swift_src], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Biên dịch tiện ích WiFi macOS thất bại: {e.stderr.decode('utf-8')}")
            except FileNotFoundError:
                raise RuntimeError("swiftc chưa được cài đặt. Hãy cài Xcode Command Line Tools để sử dụng cảm biến WiFi macOS gốc.")

        self._running = True
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="mac-rssi-collector"
        )
        self._thread.start()
        logger.info("MacosWifiCollector đã khởi động ở %.1f Hz", self._rate)

    def stop(self) -> None:
        self._running = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("MacosWifiCollector đã dừng")

    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]:
        if n is not None:
            return self._buffer.get_last_n(n)
        return self._buffer.get_all()

    # -- nội bộ --------------------------------------------------------------

    def _sample_loop(self) -> None:
        import json

        # Khởi động tệp nhị phân Swift
        self._process = subprocess.Popen(
            [self.swift_bin],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # Đệm theo dòng
        )

        while self._running and self._process and self._process.poll() is None:
            try:
                line = self._process.stdout.readline()
                if not line:
                    continue

                line = line.strip()
                if not line:
                    continue

                if line.startswith("{"):
                    data = json.loads(line)
                    if "error" in data:
                        logger.error("Lỗi tiện ích WiFi macOS: %s", data["error"])
                        continue

                    rssi = float(data.get("rssi", -80.0))
                    noise = float(data.get("noise", -95.0))

                    link_quality = max(0.0, min(1.0, (rssi + 100.0) / 60.0))

                    sample = WifiSample(
                        timestamp=time.time(),
                        rssi_dbm=rssi,
                        noise_dbm=noise,
                        link_quality=link_quality,
                        tx_bytes=0,
                        rx_bytes=0,
                        retry_count=0,
                        interface=self._interface,
                    )
                    self._buffer.append(sample)
            except Exception as e:
                logger.error("Lỗi khi đọc luồng WiFi macOS: %s", e)
                time.sleep(1.0)

        # Tiến trình thoát bất ngờ
        if self._running:
            logger.error("Tiện ích WiFi macOS đã thoát bất ngờ. Bộ thu thập đã dừng.")
            self._running = False


# ---------------------------------------------------------------------------
# Nhà máy bộ thu thập (ADR-049)
# ---------------------------------------------------------------------------

CollectorType = Union[LinuxWifiCollector, WindowsWifiCollector, MacosWifiCollector, SimulatedCollector]


def create_collector(
    preferred: str = "auto",
    interface: str = "wlan0",
    sample_rate_hz: float = 10.0,
) -> CollectorType:
    """Tạo bộ thu thập WiFi tốt nhất khả dụng cho nền tảng hiện tại.

    Thứ tự giải quyết (khi ``preferred="auto"``):
      1. WiFi gốc nền tảng:
         - Linux: LinuxWifiCollector (yêu cầu /proc/net/wireless + giao diện hoạt động)
         - Windows: WindowsWifiCollector (netsh wlan)
         - macOS: MacosWifiCollector (CoreWLAN)
      2. SimulatedCollector (luôn khả dụng)

    Hàm này không bao giờ ném lỗi -- luôn trả về bộ thu thập khả dụng.

    Parameters
    ----------
    preferred : str
        ``"auto"`` cho phát hiện nền tảng, hoặc một trong ``"linux"``,
        ``"windows"``, ``"macos"``, ``"simulated"`` để ép buộc bộ thu thập
        cụ thể.
    interface : str
        Tên giao diện WiFi (chỉ Linux/Windows).
    sample_rate_hz : float
        Tốc độ lấy mẫu mục tiêu.
    """
    _VALID_PREFERRED = {"auto", "linux", "windows", "macos", "simulated"}
    if preferred not in _VALID_PREFERRED:
        logger.warning(
            "Bộ thu thập WiFi: preferred=%r không xác định (hợp lệ: %s). Chuyển về auto.",
            preferred, ", ".join(sorted(_VALID_PREFERRED)),
        )
        preferred = "auto"

    system = platform.system()

    if preferred == "auto":
        if system == "Linux":
            available, reason = LinuxWifiCollector.is_available(interface)
            if available:
                logger.info("Bộ thu thập WiFi: sử dụng LinuxWifiCollector trên %s", interface)
                return LinuxWifiCollector(interface=interface, sample_rate_hz=sample_rate_hz)
            logger.warning("Bộ thu thập WiFi: LinuxWifiCollector không khả dụng (%s).", reason)
        elif system == "Windows":
            try:
                win_iface = interface if interface != "wlan0" else "Wi-Fi"
                collector = WindowsWifiCollector(interface=win_iface, sample_rate_hz=min(sample_rate_hz, 2.0))
                collector.collect_once()
                logger.info("Bộ thu thập WiFi: sử dụng WindowsWifiCollector trên '%s'", interface)
                return collector
            except Exception as exc:
                logger.warning("Bộ thu thập WiFi: WindowsWifiCollector không khả dụng (%s).", exc)
        elif system == "Darwin":
            try:
                collector = MacosWifiCollector(sample_rate_hz=sample_rate_hz)
                logger.info("Bộ thu thập WiFi: sử dụng MacosWifiCollector")
                return collector
            except Exception as exc:
                logger.warning("Bộ thu thập WiFi: MacosWifiCollector không khả dụng (%s).", exc)
    elif preferred == "linux":
        return LinuxWifiCollector(interface=interface, sample_rate_hz=sample_rate_hz)
    elif preferred == "windows":
        return WindowsWifiCollector(interface=interface, sample_rate_hz=min(sample_rate_hz, 2.0))
    elif preferred == "macos":
        return MacosWifiCollector(sample_rate_hz=sample_rate_hz)
    elif preferred == "simulated":
        return SimulatedCollector(seed=42, sample_rate_hz=sample_rate_hz)

    logger.info(
        "Bộ thu thập WiFi: chuyển về SimulatedCollector. "
        "Để cảm biến thực, kết nối nút ESP32 qua UDP:5005 hoặc cài driver WiFi nền tảng."
    )
    return SimulatedCollector(seed=42, sample_rate_hz=sample_rate_hz)
