"""Trích xuất dữ liệu CSI từ phần cứng WiFi sử dụng phương pháp Phát triển Hướng Kiểm thử."""

import asyncio
import struct
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, Protocol
from dataclasses import dataclass
import logging


class CSIParseError(Exception):
    """Ngoại lệ phát sinh khi phân tích CSI gặp lỗi."""
    pass


class CSIValidationError(Exception):
    """Ngoại lệ phát sinh khi xác thực CSI gặp lỗi."""
    pass


class CSIExtractionError(Exception):
    """Ngoại lệ phát sinh khi trích xuất dữ liệu CSI thất bại.

    Lỗi này được phát sinh thay vì trả về dữ liệu ngẫu nhiên/giữ chỗ một cách âm thầm.
    Người gọi nên xử lý lỗi này để thông báo rằng cần dữ liệu phần cứng thực.
    """
    pass


@dataclass
class CSIData:
    """Cấu trúc dữ liệu cho các phép đo CSI."""
    timestamp: datetime
    amplitude: np.ndarray
    phase: np.ndarray
    frequency: float
    bandwidth: float
    num_subcarriers: int
    num_antennas: int
    snr: float
    metadata: Dict[str, Any]


class CSIParser(Protocol):
    """Giao thức cho các bộ phân tích dữ liệu CSI."""

    def parse(self, raw_data: bytes) -> CSIData:
        """Phân tích dữ liệu CSI thô thành định dạng có cấu trúc."""
        ...


class ESP32CSIParser:
    """Bộ phân tích cho định dạng dữ liệu CSI ESP32."""

    def parse(self, raw_data: bytes) -> CSIData:
        """Phân tích định dạng dữ liệu CSI ESP32.

        Args:
            raw_data: Bytes thô từ ESP32

        Returns:
            Dữ liệu CSI đã phân tích

        Raises:
            CSIParseError: Nếu định dạng dữ liệu không hợp lệ
        """
        if not raw_data:
            raise CSIParseError("Nhận được dữ liệu rỗng")

        try:
            data_str = raw_data.decode('utf-8')
            if not data_str.startswith('CSI_DATA:'):
                raise CSIParseError("Định dạng dữ liệu CSI ESP32 không hợp lệ")

            # Phân tích định dạng ESP32: CSI_DATA:timestamp,antennas,subcarriers,freq,bw,snr,[amp],[phase]
            parts = data_str[9:].split(',')  # Loại bỏ tiền tố 'CSI_DATA:'

            timestamp_ms = int(parts[0])
            num_antennas = int(parts[1])
            num_subcarriers = int(parts[2])
            frequency_mhz = float(parts[3])
            bandwidth_mhz = float(parts[4])
            snr = float(parts[5])

            # Chuyển đổi sang đơn vị phù hợp
            frequency = frequency_mhz * 1e6  # MHz sang Hz
            bandwidth = bandwidth_mhz * 1e6  # MHz sang Hz

            # Phân tích mảng biên độ và pha từ các trường CSV còn lại.
            # Định dạng dự kiến sau các trường tiêu đề: giá trị float phân cách bằng dấu phẩy
            # đại diện cho biên độ và pha xen kẽ theo ăng-ten theo sóng mang con.
            data_values = parts[6:]
            expected_values = num_antennas * num_subcarriers * 2  # biên độ + pha

            if len(data_values) < expected_values:
                raise CSIExtractionError(
                    f"Dữ liệu CSI ESP32 không đầy đủ: cần {expected_values} giá trị "
                    f"(biên độ + pha cho {num_antennas} ăng-ten x {num_subcarriers} sóng mang con), "
                    f"nhưng nhận được {len(data_values)} giá trị. "
                    "Đảm bảo firmware ESP32 được cấu hình để xuất dữ liệu ma trận CSI đầy đủ. "
                    "Xem docs/hardware-setup.md để biết cấu hình CSI ESP32."
                )

            try:
                float_values = [float(v) for v in data_values[:expected_values]]
            except ValueError as ve:
                raise CSIExtractionError(
                    f"Dữ liệu CSI ESP32 chứa giá trị không phải số: {ve}. "
                    "Các trường CSI thô phải là giá trị float số."
                )

            all_values = np.array(float_values)
            amplitude = all_values[:num_antennas * num_subcarriers].reshape(num_antennas, num_subcarriers)
            phase = all_values[num_antennas * num_subcarriers:].reshape(num_antennas, num_subcarriers)

            return CSIData(
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
                amplitude=amplitude,
                phase=phase,
                frequency=frequency,
                bandwidth=bandwidth,
                num_subcarriers=num_subcarriers,
                num_antennas=num_antennas,
                snr=snr,
                metadata={'source': 'esp32', 'raw_length': len(raw_data)}
            )

        except (ValueError, IndexError) as e:
            raise CSIParseError(f"Phân tích dữ liệu ESP32 thất bại: {e}")


class ESP32BinaryParser:
    """Bộ phân tích cho khung CSI nhị phân ADR-018 từ các nút ESP32.

    Định dạng khung nhị phân:
        Offset  Kích thước  Trường
        0       4           Magic: 0xC5110001 (LE)
        4       1           ID nút
        5       1           Số ăng-ten
        6       2           Số sóng mang con (LE u16)
        8       4           Tần số MHz (LE u32)
        12      4           Số thứ tự (LE u32)
        16      1           RSSI (i8)
        17      1           Mức nhiễu nền (i8)
        18      2           Dự phòng
        20      N*2         Cặp I/Q (n_antennas * n_subcarriers * 2 bytes, i8 có dấu)
    """

    MAGIC = 0xC5110001
    HEADER_SIZE = 20
    HEADER_FMT = '<IBBHIIBB2x'  # magic, node_id, n_ant, n_sc, freq, seq, rssi, noise

    def parse(self, raw_data: bytes) -> CSIData:
        """Phân tích khung nhị phân ADR-018 thành CSIData.

        Args:
            raw_data: Bytes khung nhị phân thô.

        Returns:
            Dữ liệu CSI đã phân tích với mảng biên độ/pha có hình dạng (n_antennas, n_subcarriers).

        Raises:
            CSIParseError: Nếu khung quá ngắn, có magic không hợp lệ, hoặc dữ liệu I/Q bị lỗi.
        """
        if len(raw_data) < self.HEADER_SIZE:
            raise CSIParseError(
                f"Khung quá ngắn: cần {self.HEADER_SIZE} bytes, nhận được {len(raw_data)}"
            )

        magic, node_id, n_antennas, n_subcarriers, freq_mhz, sequence, rssi_u8, noise_u8 = \
            struct.unpack_from(self.HEADER_FMT, raw_data, 0)

        if magic != self.MAGIC:
            raise CSIParseError(
                f"Magic không hợp lệ: cần 0x{self.MAGIC:08X}, nhận được 0x{magic:08X}"
            )

        # Chuyển đổi bytes không dấu sang i8 có dấu
        rssi = rssi_u8 if rssi_u8 < 128 else rssi_u8 - 256
        noise_floor = noise_u8 if noise_u8 < 128 else noise_u8 - 256

        iq_count = n_antennas * n_subcarriers
        iq_bytes = iq_count * 2
        expected_len = self.HEADER_SIZE + iq_bytes

        if len(raw_data) < expected_len:
            raise CSIParseError(
                f"Khung quá ngắn cho dữ liệu I/Q: cần {expected_len} bytes, nhận được {len(raw_data)}"
            )

        # Phân tích cặp I/Q dưới dạng bytes có dấu
        iq_raw = struct.unpack_from(f'<{iq_count * 2}b', raw_data, self.HEADER_SIZE)
        i_vals = np.array(iq_raw[0::2], dtype=np.float64).reshape(n_antennas, n_subcarriers)
        q_vals = np.array(iq_raw[1::2], dtype=np.float64).reshape(n_antennas, n_subcarriers)

        amplitude = np.sqrt(i_vals ** 2 + q_vals ** 2)
        phase = np.arctan2(q_vals, i_vals)

        snr = float(rssi - noise_floor)
        frequency = float(freq_mhz) * 1e6
        bandwidth = 20e6  # mặc định; có thể suy ra từ n_subcarriers

        if n_subcarriers <= 56:
            bandwidth = 20e6
        elif n_subcarriers <= 114:
            bandwidth = 40e6
        elif n_subcarriers <= 242:
            bandwidth = 80e6
        else:
            bandwidth = 160e6

        return CSIData(
            timestamp=datetime.now(tz=timezone.utc),
            amplitude=amplitude,
            phase=phase,
            frequency=frequency,
            bandwidth=bandwidth,
            num_subcarriers=n_subcarriers,
            num_antennas=n_antennas,
            snr=snr,
            metadata={
                'source': 'esp32_binary',
                'node_id': node_id,
                'sequence': sequence,
                'rssi_dbm': rssi,
                'noise_floor_dbm': noise_floor,
                'channel_freq_mhz': freq_mhz,
            }
        )


class RouterCSIParser:
    """Bộ phân tích cho định dạng dữ liệu CSI router."""

    def parse(self, raw_data: bytes) -> CSIData:
        """Phân tích định dạng dữ liệu CSI router.

        Args:
            raw_data: Bytes thô từ router

        Returns:
            Dữ liệu CSI đã phân tích

        Raises:
            CSIParseError: Nếu định dạng dữ liệu không hợp lệ
        """
        if not raw_data:
            raise CSIParseError("Nhận được dữ liệu rỗng")

        # Xử lý các định dạng router khác nhau
        data_str = raw_data.decode('utf-8')

        if data_str.startswith('ATHEROS_CSI:'):
            return self._parse_atheros_format(raw_data)
        else:
            raise CSIParseError("Định dạng CSI router không xác định")

    def _parse_atheros_format(self, raw_data: bytes) -> CSIData:
        """Phân tích định dạng CSI Atheros.

        Raises:
            CSIExtractionError: Luôn luôn, vì việc phân tích CSI Atheros yêu cầu
                bộ phân tích định dạng nhị phân Atheros CSI Tool chưa được
                triển khai. Sử dụng bộ phân tích ESP32 hoặc đóng góp triển khai
                Atheros.
        """
        raise CSIExtractionError(
            "Phân tích định dạng CSI Atheros chưa được triển khai. "
            "Atheros CSI Tool xuất định dạng nhị phân yêu cầu bộ phân tích chuyên dụng. "
            "Để thu thập dữ liệu CSI thực từ router dựa trên Atheros, bạn phải triển khai "
            "bộ phân tích định dạng nhị phân theo đặc tả Atheros CSI Tool. "
            "Xem docs/hardware-setup.md để biết phần cứng và định dạng dữ liệu được hỗ trợ."
        )


class CSIExtractor:
    """Bộ trích xuất dữ liệu CSI chính hỗ trợ nhiều loại phần cứng."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Khởi tạo bộ trích xuất CSI.

        Args:
            config: Từ điển cấu hình
            logger: Thể hiện logger tùy chọn

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        self._validate_config(config)

        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.hardware_type = config['hardware_type']
        self.sampling_rate = config['sampling_rate']
        self.buffer_size = config['buffer_size']
        self.timeout = config['timeout']
        self.validation_enabled = config.get('validation_enabled', True)
        self.retry_attempts = config.get('retry_attempts', 3)

        # Quản lý trạng thái
        self.is_connected = False
        self.is_streaming = False

        # Tạo bộ phân tích phù hợp
        if self.hardware_type == 'esp32':
            if config.get('parser_format') == 'binary':
                self.parser = ESP32BinaryParser()
            else:
                self.parser = ESP32CSIParser()
        elif self.hardware_type == 'router':
            self.parser = RouterCSIParser()
        else:
            raise ValueError(f"Loại phần cứng không được hỗ trợ: {self.hardware_type}")

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Xác thực tham số cấu hình.

        Args:
            config: Cấu hình cần xác thực

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        required_fields = ['hardware_type', 'sampling_rate', 'buffer_size', 'timeout']
        missing_fields = [field for field in required_fields if field not in config]

        if missing_fields:
            raise ValueError(f"Thiếu cấu hình bắt buộc: {missing_fields}")

        if config['sampling_rate'] <= 0:
            raise ValueError("sampling_rate phải là số dương")

        if config['buffer_size'] <= 0:
            raise ValueError("buffer_size phải là số dương")

        if config['timeout'] <= 0:
            raise ValueError("timeout phải là số dương")

    async def connect(self) -> bool:
        """Thiết lập kết nối đến phần cứng CSI.

        Returns:
            True nếu kết nối thành công, False nếu không
        """
        try:
            success = await self._establish_hardware_connection()
            self.is_connected = success
            return success
        except Exception as e:
            self.logger.error(f"Kết nối đến phần cứng thất bại: {e}")
            self.is_connected = False
            return False

    async def disconnect(self) -> None:
        """Ngắt kết nối khỏi phần cứng CSI."""
        if self.is_connected:
            await self._close_hardware_connection()
            self.is_connected = False

    async def extract_csi(self) -> CSIData:
        """Trích xuất dữ liệu CSI từ phần cứng.

        Returns:
            Dữ liệu CSI đã trích xuất

        Raises:
            CSIParseError: Nếu chưa kết nối hoặc trích xuất thất bại
        """
        if not self.is_connected:
            raise CSIParseError("Chưa kết nối đến phần cứng")

        # Cơ chế thử lại cho lỗi tạm thời
        for attempt in range(self.retry_attempts):
            try:
                raw_data = await self._read_raw_data()
                csi_data = self.parser.parse(raw_data)

                if self.validation_enabled:
                    self.validate_csi_data(csi_data)

                return csi_data

            except ConnectionError as e:
                if attempt < self.retry_attempts - 1:
                    self.logger.warning(f"Lần trích xuất {attempt + 1} thất bại, đang thử lại: {e}")
                    await asyncio.sleep(0.1)  # Chờ ngắn trước khi thử lại
                else:
                    raise CSIParseError(f"Trích xuất thất bại sau {self.retry_attempts} lần thử: {e}")

    def validate_csi_data(self, csi_data: CSIData) -> bool:
        """Xác thực cấu trúc và giá trị dữ liệu CSI.

        Args:
            csi_data: Dữ liệu CSI cần xác thực

        Returns:
            True nếu hợp lệ

        Raises:
            CSIValidationError: Nếu dữ liệu không hợp lệ
        """
        if csi_data.amplitude.size == 0:
            raise CSIValidationError("Dữ liệu biên độ rỗng")

        if csi_data.phase.size == 0:
            raise CSIValidationError("Dữ liệu pha rỗng")

        if csi_data.frequency <= 0:
            raise CSIValidationError("Tần số không hợp lệ")

        if csi_data.bandwidth <= 0:
            raise CSIValidationError("Băng thông không hợp lệ")

        if csi_data.num_subcarriers <= 0:
            raise CSIValidationError("Số sóng mang con không hợp lệ")

        if csi_data.num_antennas <= 0:
            raise CSIValidationError("Số ăng-ten không hợp lệ")

        if csi_data.snr < -50 or csi_data.snr > 50:  # Phạm vi SNR hợp lý
            raise CSIValidationError("Giá trị SNR không hợp lệ")

        return True

    async def start_streaming(self, callback: Callable[[CSIData], None]) -> None:
        """Bắt đầu truyền phát dữ liệu CSI.

        Args:
            callback: Hàm gọi lại với mỗi mẫu CSI
        """
        self.is_streaming = True

        try:
            while self.is_streaming:
                csi_data = await self.extract_csi()
                callback(csi_data)
                await asyncio.sleep(1.0 / self.sampling_rate)
        except Exception as e:
            self.logger.error(f"Lỗi truyền phát: {e}")
        finally:
            self.is_streaming = False

    def stop_streaming(self) -> None:
        """Dừng truyền phát dữ liệu CSI."""
        self.is_streaming = False

    async def _establish_hardware_connection(self) -> bool:
        """Thiết lập kết nối đến phần cứng (sẽ được triển khai bởi lớp con)."""
        # Triển khai giữ chỗ cho kiểm thử
        return True

    async def _close_hardware_connection(self) -> None:
        """Đóng kết nối phần cứng (sẽ được triển khai bởi lớp con)."""
        # Triển khai giữ chỗ cho kiểm thử
        pass

    async def _read_raw_data(self) -> bytes:
        """Đọc dữ liệu thô từ phần cứng.

        Khi parser_format='binary', đọc từ socket UDP đã cấu hình.
        Nếu không, trả về dữ liệu văn bản giữ chỗ cho tương thích ngược.

        Raises:
            CSIExtractionError: Nếu đọc UDP hết thời gian chờ hoặc thất bại.
        """
        if self.config.get('parser_format') == 'binary':
            return await self._read_udp_data()
        # Triển khai giữ chỗ cho kiểm thử chế độ văn bản kế thừa
        return b"CSI_DATA:1234567890,3,56,2400,20,15.5,[1.0,2.0,3.0],[0.5,1.5,2.5]"

    async def _read_udp_data(self) -> bytes:
        """Đọc một gói UDP từ bộ tổng hợp.

        Raises:
            CSIExtractionError: Nếu đọc hết thời gian chờ hoặc kết nối thất bại.
        """
        host = self.config.get('aggregator_host', '0.0.0.0')
        port = self.config.get('aggregator_port', 5005)

        loop = asyncio.get_event_loop()

        # Tạo endpoint UDP nếu chưa được cache
        if not hasattr(self, '_udp_transport'):
            self._udp_future: asyncio.Future = loop.create_future()

            class _UdpProtocol(asyncio.DatagramProtocol):
                def __init__(self, future):
                    self._future = future

                def datagram_received(self, data, addr):
                    if not self._future.done():
                        self._future.set_result(data)

                def error_received(self, exc):
                    if not self._future.done():
                        self._future.set_exception(exc)

            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(self._udp_future),
                local_addr=(host, port),
            )
            self._udp_transport = transport
            self._udp_protocol = protocol

        try:
            data = await asyncio.wait_for(self._udp_future, timeout=self.timeout)
            # Đặt lại future cho lần đọc tiếp theo
            self._udp_future = loop.create_future()
            self._udp_protocol._future = self._udp_future
            return data
        except asyncio.TimeoutError:
            raise CSIExtractionError(
                f"Đọc UDP hết thời gian chờ sau {self.timeout}s. "
                f"Đảm bảo bộ tổng hợp đang chạy và gửi đến {host}:{port}."
            )
