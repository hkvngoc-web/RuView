"""
Máy chủ WebSocket cảm biến.

Máy chủ asyncio nhẹ kết nối pipeline cảm biến WiFi với
giao diện trình duyệt. Chạy bộ trích xuất đặc trưng RSSI + bộ phân loại
trên nhịp 500 ms và phát sóng khung JSON đến tất cả máy khách WebSocket
đã kết nối trên ``ws://localhost:8765``.

Cách dùng
---------
    pip install websockets
    python -m v1.src.sensing.ws_server          # hoặc  python v1/src/sensing/ws_server.py

Nguồn dữ liệu (thử theo thứ tự):
    1. ESP32 CSI qua cổng UDP 5005 (khung nhị phân ADR-018)
    2. WiFi RSSI Windows qua netsh
    3. WiFi RSSI Linux qua /proc/net/wireless
    4. Bộ thu thập mô phỏng (dự phòng)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import signal
import socket
import struct
import sys
import threading
import time
from collections import deque
from typing import Dict, List, Optional, Set

import numpy as np

# Import pipeline cảm biến
from v1.src.sensing.rssi_collector import (
    WifiSample,
    RingBuffer,
)
from v1.src.sensing.feature_extractor import RssiFeatureExtractor, RssiFeatures
from v1.src.sensing.classifier import MotionLevel, PresenceClassifier, SensingResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------

HOST = "localhost"
PORT = 8765
TICK_INTERVAL = 0.5  # giây giữa các lần phát sóng
SIGNAL_FIELD_GRID = 20  # Lưới NxN cho trực quan hóa trường tín hiệu
ESP32_UDP_PORT = 5005


# ---------------------------------------------------------------------------
# Bộ thu thập UDP ESP32 — đọc khung nhị phân ADR-018
# ---------------------------------------------------------------------------

class Esp32UdpCollector:
    """
    Thu thập dữ liệu CSI thực từ nút ESP32 qua UDP (định dạng nhị phân ADR-018).

    Phân tích cặp I/Q, tính biên độ trung bình mỗi khung, và lưu dưới dạng
    giá trị tương đương RSSI trong bộ đệm vòng WifiSample tiêu chuẩn để
    bộ trích xuất đặc trưng và bộ phân loại hiện có hoạt động không thay đổi.

    Cũng giữ khung CSI đã phân tích gần nhất để UI hiển thị dữ liệu sóng mang con.
    """

    # Tiêu đề ADR-018: magic(4) node_id(1) n_ant(1) n_sc(2) freq(4) seq(4) rssi(1) noise(1) reserved(2)
    MAGIC = 0xC5110001
    HEADER_SIZE = 20
    HEADER_FMT = '<IBBHIIBB2x'

    def __init__(
        self,
        bind_addr: str = "0.0.0.0",
        port: int = ESP32_UDP_PORT,
        sample_rate_hz: float = 10.0,
        buffer_seconds: int = 120,
    ) -> None:
        self._bind = bind_addr
        self._port = port
        self._rate = sample_rate_hz
        self._buffer = RingBuffer(max_size=int(sample_rate_hz * buffer_seconds))
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

        # Khung CSI gần nhất cho UI nâng cao
        self.last_csi: Optional[Dict] = None
        self._frames_received = 0

    @property
    def sample_rate_hz(self) -> float:
        return self._rate

    @property
    def frames_received(self) -> int:
        return self._frames_received

    def start(self) -> None:
        if self._running:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._sock.bind((self._bind, self._port))
        self._running = True
        self._thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="esp32-udp-collector"
        )
        self._thread.start()
        logger.info("Esp32UdpCollector đang lắng nghe trên %s:%d", self._bind, self._port)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sock:
            self._sock.close()
            self._sock = None
        logger.info("Esp32UdpCollector đã dừng (%d khung đã nhận)", self._frames_received)

    def get_samples(self, n: Optional[int] = None) -> List[WifiSample]:
        if n is not None:
            return self._buffer.get_last_n(n)
        return self._buffer.get_all()

    def _recv_loop(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(4096)
                self._parse_and_store(data, addr)
            except socket.timeout:
                continue
            except Exception:
                if self._running:
                    logger.exception("Lỗi khi nhận gói UDP ESP32")

    def _parse_and_store(self, raw: bytes, addr) -> None:
        if len(raw) < self.HEADER_SIZE:
            return

        magic, node_id, n_ant, n_sc, freq_mhz, seq, rssi_u8, noise_u8 = \
            struct.unpack_from(self.HEADER_FMT, raw, 0)

        if magic != self.MAGIC:
            return

        rssi = rssi_u8 if rssi_u8 < 128 else rssi_u8 - 256
        noise = noise_u8 if noise_u8 < 128 else noise_u8 - 256

        # Phân tích dữ liệu I/Q nếu có
        iq_count = n_ant * n_sc
        iq_bytes_needed = self.HEADER_SIZE + iq_count * 2
        amplitude_list = []

        if len(raw) >= iq_bytes_needed and iq_count > 0:
            iq_raw = struct.unpack_from(f'<{iq_count * 2}b', raw, self.HEADER_SIZE)
            i_vals = np.array(iq_raw[0::2], dtype=np.float64)
            q_vals = np.array(iq_raw[1::2], dtype=np.float64)
            amplitudes = np.sqrt(i_vals ** 2 + q_vals ** 2)
            mean_amp = float(np.mean(amplitudes))
            amplitude_list = amplitudes.tolist()
        else:
            mean_amp = 0.0

        # Lưu thông tin CSI nâng cao cho UI
        self.last_csi = {
            "node_id": node_id,
            "n_antennas": n_ant,
            "n_subcarriers": n_sc,
            "freq_mhz": freq_mhz,
            "sequence": seq,
            "rssi_dbm": rssi,
            "noise_floor_dbm": noise,
            "mean_amplitude": mean_amp,
            "amplitude": amplitude_list[:56],  # giới hạn cho kích thước JSON
            "source_addr": f"{addr[0]}:{addr[1]}",
        }

        # Sử dụng RSSI từ tiêu đề khung ESP32 làm số liệu tín hiệu chính.
        # Nếu RSSI là giá trị placeholder -80 mặc định, suy ra pseudo-RSSI từ
        # biên độ trung bình để bộ trích xuất đặc trưng vẫn có ý nghĩa.
        effective_rssi = float(rssi)
        if rssi == -80 and mean_amp > 0:
            # Ánh xạ biên độ (thường 1-20) sang phạm vi dBm (-70 đến -30)
            effective_rssi = -70.0 + min(mean_amp, 20.0) * 2.0

        sample = WifiSample(
            timestamp=time.time(),
            rssi_dbm=effective_rssi,
            noise_dbm=float(noise),
            link_quality=max(0.0, min(1.0, (effective_rssi + 100.0) / 60.0)),
            tx_bytes=seq * 1500,
            rx_bytes=seq * 3000,
            retry_count=0,
            interface=f"esp32-node{node_id}",
        )
        self._buffer.append(sample)
        self._frames_received += 1


# ---------------------------------------------------------------------------
# Thăm dò UDP ESP32
# ---------------------------------------------------------------------------

def probe_esp32_udp(port: int = ESP32_UDP_PORT, timeout: float = 2.0) -> bool:
    """Trả về True nếu ESP32 đang phát trực tuyến trên cổng UDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("0.0.0.0", port))
        data, _ = sock.recvfrom(256)
        if len(data) >= 20:
            magic = struct.unpack_from('<I', data, 0)[0]
            return magic == 0xC5110001
        return False
    except (socket.timeout, OSError):
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Bộ tạo trường tín hiệu
# ---------------------------------------------------------------------------

def generate_signal_field(
    features: RssiFeatures,
    result: SensingResult,
    grid_size: int = SIGNAL_FIELD_GRID,
    csi_data: Optional[Dict] = None,
) -> Dict:
    """
    Tạo trường cường độ tín hiệu 2-D cho trực quan hóa Gaussian splat.
    Khi có dữ liệu biên độ CSI thực, nó điều chế trường.
    """
    field = np.zeros((grid_size, grid_size), dtype=np.float64)

    # Sàn nhiễu cơ sở
    rng = np.random.default_rng(int(abs(features.mean * 100)) % (2**31))
    field += rng.uniform(0.02, 0.08, size=(grid_size, grid_size))

    cx, cy = grid_size // 2, grid_size // 2

    # Suy hao hướng tâm từ router
    for y in range(grid_size):
        for x in range(grid_size):
            dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            attenuation = max(0.0, 1.0 - dist / (grid_size * 0.7))
            field[y, x] += attenuation * 0.3

    # Nếu có biên độ sóng mang con CSI thực, vẽ chúng dọc theo một trục
    if csi_data and csi_data.get("amplitude"):
        amps = np.array(csi_data["amplitude"][:grid_size], dtype=np.float64)
        if len(amps) > 0:
            max_a = np.max(amps) if np.max(amps) > 0 else 1.0
            norm_amps = amps / max_a
            # Trải năng lượng sóng mang con dưới dạng sọc dọc
            for ix, a in enumerate(norm_amps):
                col = int(ix * grid_size / len(norm_amps))
                col = min(col, grid_size - 1)
                field[:, col] += a * 0.4

    if result.presence_detected:
        body_x = cx + int(3 * math.sin(time.time() * 0.2))
        body_y = cy + int(2 * math.cos(time.time() * 0.15))
        sigma = 2.0 + features.variance * 0.5

        for y in range(grid_size):
            for x in range(grid_size):
                dx = x - body_x
                dy = y - body_y
                blob = math.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
                intensity = 0.3 + 0.7 * min(1.0, features.motion_band_power * 5)
                field[y, x] += blob * intensity

        if features.breathing_band_power > 0.01:
            breath_phase = math.sin(2 * math.pi * 0.3 * time.time())
            breath_radius = 3.0 + breath_phase * 0.8
            for y in range(grid_size):
                for x in range(grid_size):
                    dist_body = math.sqrt((x - body_x) ** 2 + (y - body_y) ** 2)
                    ring = math.exp(-((dist_body - breath_radius) ** 2) / 1.5)
                    field[y, x] += ring * features.breathing_band_power * 2

    field = np.clip(field, 0.0, 1.0)

    return {
        "grid_size": [grid_size, 1, grid_size],
        "values": field.flatten().tolist(),
    }


# ---------------------------------------------------------------------------
# Máy chủ WebSocket
# ---------------------------------------------------------------------------

class SensingWebSocketServer:
    """Máy chủ WebSocket bất đồng bộ phát sóng cập nhật cảm biến."""

    def __init__(self) -> None:
        self.clients: Set = set()
        self.collector = None
        self.extractor = RssiFeatureExtractor(window_seconds=10.0)
        self.classifier = PresenceClassifier()
        self.source: str = "unknown"
        self._running = False

    def _create_collector(self):
        """Tự động phát hiện nguồn dữ liệu: ESP32 UDP > WiFi nền tảng > mô phỏng.

        Sử dụng nhà máy ``create_collector`` (ADR-049) cho phát hiện WiFi
        nền tảng, không bao giờ ném lỗi và ghi nhật ký thông báo dự phòng có ý nghĩa.
        """
        from .rssi_collector import create_collector

        # 1. Thử ESP32 UDP trước
        print("  Đang thăm dò ESP32 trên UDP :5005 ...")
        if probe_esp32_udp(ESP32_UDP_PORT, timeout=2.0):
            logger.info("Phát hiện luồng CSI ESP32 trên UDP :%d", ESP32_UDP_PORT)
            self.source = "esp32"
            return Esp32UdpCollector(port=ESP32_UDP_PORT, sample_rate_hz=10.0)

        # 2. WiFi theo nền tảng (tự động phát hiện với dự phòng nhẹ nhàng)
        collector = create_collector(preferred="auto", sample_rate_hz=10.0)

        # Ánh xạ lớp bộ thu thập sang nhãn nguồn
        source_map = {
            "LinuxWifiCollector": "linux_wifi",
            "WindowsWifiCollector": "windows_wifi",
            "MacosWifiCollector": "macos_wifi",
            "SimulatedCollector": "simulated",
        }
        self.source = source_map.get(type(collector).__name__, "unknown")
        return collector

    def _build_message(self, features: RssiFeatures, result: SensingResult) -> str:
        """Xây dựng thông điệp JSON để phát sóng."""
        # Lấy dữ liệu CSI cụ thể nếu có
        csi_data = None
        if isinstance(self.collector, Esp32UdpCollector):
            csi_data = self.collector.last_csi

        signal_field = generate_signal_field(features, result, csi_data=csi_data)

        node_info = {
            "node_id": 1,
            "rssi_dbm": features.mean,
            "position": [2.0, 0.0, 1.5],
            "amplitude": [],
            "subcarrier_count": 0,
        }

        # Bổ sung dữ liệu CSI thực
        if csi_data:
            node_info["node_id"] = csi_data.get("node_id", 1)
            node_info["rssi_dbm"] = csi_data.get("rssi_dbm", features.mean)
            node_info["amplitude"] = csi_data.get("amplitude", [])
            node_info["subcarrier_count"] = csi_data.get("n_subcarriers", 0)
            node_info["mean_amplitude"] = csi_data.get("mean_amplitude", 0)
            node_info["freq_mhz"] = csi_data.get("freq_mhz", 0)
            node_info["sequence"] = csi_data.get("sequence", 0)
            node_info["source_addr"] = csi_data.get("source_addr", "")

        msg = {
            "type": "sensing_update",
            "timestamp": time.time(),
            "source": self.source,
            "nodes": [node_info],
            "features": {
                "mean_rssi": features.mean,
                "variance": features.variance,
                "std": features.std,
                "motion_band_power": features.motion_band_power,
                "breathing_band_power": features.breathing_band_power,
                "dominant_freq_hz": features.dominant_freq_hz,
                "change_points": features.n_change_points,
                "spectral_power": features.total_spectral_power,
                "range": features.range,
                "iqr": features.iqr,
                "skewness": features.skewness,
                "kurtosis": features.kurtosis,
            },
            "classification": {
                "motion_level": result.motion_level.value,
                "presence": result.presence_detected,
                "confidence": round(result.confidence, 3),
            },
            "signal_field": signal_field,
        }
        return json.dumps(msg)

    async def _handler(self, websocket):
        """Xử lý một kết nối máy khách WebSocket đơn lẻ."""
        self.clients.add(websocket)
        remote = websocket.remote_address
        logger.info("Máy khách đã kết nối: %s", remote)
        try:
            async for _ in websocket:
                pass
        finally:
            self.clients.discard(websocket)
            logger.info("Máy khách đã ngắt kết nối: %s", remote)

    async def _broadcast(self, message: str) -> None:
        """Gửi thông điệp đến tất cả máy khách đã kết nối."""
        if not self.clients:
            return
        disconnected = set()
        for ws in self.clients:
            try:
                await ws.send(message)
            except Exception:
                disconnected.add(ws)
        self.clients -= disconnected

    async def _tick_loop(self) -> None:
        """Vòng lặp cảm biến chính."""
        while self._running:
            try:
                window = self.extractor.window_seconds
                sample_rate = self.collector.sample_rate_hz
                n_needed = int(window * sample_rate)
                samples = self.collector.get_samples(n=n_needed)

                if len(samples) >= 4:
                    features = self.extractor.extract(samples)
                    result = self.classifier.classify(features)
                    message = self._build_message(features, result)
                    await self._broadcast(message)

                    # In trạng thái mỗi vài nhịp
                    if isinstance(self.collector, Esp32UdpCollector):
                        csi = self.collector.last_csi
                        if csi and self.collector.frames_received % 20 == 0:
                            print(
                                f"  [{csi['source_addr']}] nút:{csi['node_id']} "
                                f"seq:{csi['sequence']} sc:{csi['n_subcarriers']} "
                                f"rssi:{csi['rssi_dbm']}dBm amp:{csi['mean_amplitude']:.1f} "
                                f"=> {result.motion_level.value} ({result.confidence:.0%})"
                            )
                else:
                    logger.debug("Đang chờ mẫu (%d/%d)", len(samples), n_needed)
            except Exception:
                logger.exception("Lỗi trong nhịp cảm biến")

            await asyncio.sleep(TICK_INTERVAL)

    async def run(self) -> None:
        """Khởi động máy chủ và chạy cho đến khi bị gián đoạn."""
        try:
            import websockets
        except ImportError:
            print("LỖI: Không tìm thấy gói 'websockets'.")
            print("Cài đặt bằng:  pip install websockets")
            sys.exit(1)

        self.collector = self._create_collector()
        self.collector.start()
        self._running = True

        print(f"\n  Máy chủ WebSocket cảm biến trên ws://{HOST}:{PORT}")
        print(f"  Nguồn: {self.source}")
        print(f"  Nhịp: {TICK_INTERVAL}s | Cửa sổ: {self.extractor.window_seconds}s")
        print("  Nhấn Ctrl+C để dừng\n")

        async with websockets.serve(self._handler, HOST, PORT):
            await self._tick_loop()

    def stop(self) -> None:
        """Dừng máy chủ nhẹ nhàng."""
        self._running = False
        if self.collector:
            self.collector.stop()
        logger.info("Máy chủ cảm biến đã dừng")


# ---------------------------------------------------------------------------
# Điểm vào
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = SensingWebSocketServer()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig, frame):
        print("\nĐang tắt...")
        server.stop()
        loop.stop()

    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(server.run())
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        loop.close()


if __name__ == "__main__":
    main()
