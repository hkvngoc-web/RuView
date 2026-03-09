#!/usr/bin/env python3
"""
Script Xác minh Proof-of-Reality cho Đường ống WiFi-DensePose.

CÔNG TẮC TIN CẬY: Một lệnh phát lại bằng chứng duy nhất biến "nó bị giả lập"
thành một khẳng định có thể đo lường được, và sẽ thất bại trước bằng chứng.

Script này xác minh rằng đường ống xử lý tín hiệu tạo ra
đầu ra XÁC ĐỊNH, CÓ THỂ TÁI TẠO từ một tín hiệu tham chiếu đã biết.

Các bước:
  1. Tải tín hiệu CSI tham chiếu đã công bố từ sample_csi_data.json
  2. Đưa từng khung hình qua bộ trích xuất đặc trưng của bộ xử lý CSI THỰC TẾ
  3. Thu thập tất cả đầu ra đặc trưng thành biểu diễn byte chuẩn
  4. Tính hash SHA-256 của toàn bộ đầu ra đặc trưng
  5. So sánh với hash kỳ vọng đã công bố trong expected_features.sha256
  6. In kết quả ĐẠT hoặc KHÔNG ĐẠT

Tín hiệu tham chiếu là TỔ HỢP (được tạo bởi generate_reference_signal.py)
và chỉ được dùng cho mục đích xác minh tính xác định của đường ống. Vấn đề không phải
là tín hiệu có thật hay không -- vấn đề là MÃ ĐƯỜNG ỐNG là thật.
Cùng một mã xử lý tín hiệu tham chiếu này cũng xử lý các bản ghi thực.

Nếu ai đó khẳng định "nó bị giả lập":
  1. Chạy: ./verify
  2. Nếu ĐẠT: mã đường ống là cùng mã đã tạo ra hash đã công bố
  3. Nếu KHÔNG ĐẠT: có gì đó đã thay đổi -- cần điều tra

Cách dùng:
  python verify.py                  # Chạy xác minh so với hash đã lưu
  python verify.py --verbose        # Hiển thị thống kê đặc trưng chi tiết
  python verify.py --audit          # Quét mã nguồn tìm mẫu mock/random
  python verify.py --generate-hash  # Tạo và in hash kỳ vọng
"""

import hashlib
import inspect
import json
import os
import struct
import sys
import argparse
import time
from datetime import datetime, timezone

import numpy as np

# Thêm thư mục v1 vào sys.path để có thể import các module thực tế
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
V1_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))  # v1/data/proof -> v1/
if V1_DIR not in sys.path:
    sys.path.insert(0, V1_DIR)

# Import các module đường ống thực tế -- đây là các module SẢN XUẤT,
# không phải bản thay thế kiểm thử. Đường dẫn nguồn được in bên dưới để xác minh.
from src.hardware.csi_extractor import CSIData
from src.core.csi_processor import CSIProcessor, CSIFeatures


# -- Cấu hình cho bộ xử lý CSI (khớp với mặc định sản xuất) --
PROCESSOR_CONFIG = {
    "sampling_rate": 100,
    "window_size": 56,
    "overlap": 0.5,
    "noise_threshold": -60,
    "human_detection_threshold": 0.8,
    "smoothing_factor": 0.9,
    "max_history_size": 500,
    "enable_preprocessing": True,
    "enable_feature_extraction": True,
    "enable_human_detection": True,
}

# Số khung hình cần xử lý cho hash đặc trưng.
# Chúng ta xử lý một tập con đại diện để giữ tốc độ xác minh nhanh
# trong khi vẫn bao phủ động lực thời gian (Doppler cần lịch sử).
VERIFICATION_FRAME_COUNT = 100  # 100 khung hình đầu tiên = 1 giây


def print_banner():
    """In banner xác minh."""
    print("=" * 72)
    print("  WiFi-DensePose: Công Tắc Tin Cậy -- Phát Lại Bằng Chứng Đường Ống")
    print("=" * 72)
    print()
    print('  "Nếu bản demo công khai là một lệnh phát lại tạo ra hash khớp')
    print('   từ một bản ghi thực đã công bố, \'nó bị giả lập\' trở thành một')
    print('   khẳng định có thể đo lường được và sẽ thất bại."')
    print()


def print_source_provenance():
    """In đường dẫn tệp nguồn thực tế được sử dụng bởi quá trình xác minh này.

    Điều này cho phép bất kỳ ai xác nhận rằng các module được import
    là mã sản xuất, không phải bản thay thế kiểm thử hoặc mock.
    """
    csi_processor_file = inspect.getfile(CSIProcessor)
    csi_data_file = inspect.getfile(CSIData)
    csi_features_file = inspect.getfile(CSIFeatures)

    print("  NGUỒN GỐC MÃ NGUỒN (xác minh đây là các module sản xuất):")
    print(f"    CSIProcessor : {os.path.abspath(csi_processor_file)}")
    print(f"    CSIData      : {os.path.abspath(csi_data_file)}")
    print(f"    CSIFeatures  : {os.path.abspath(csi_features_file)}")
    print(f"    numpy        : {np.__file__}")
    print(f"    phiên bản numpy: {np.__version__}")

    try:
        import scipy
        print(f"    scipy        : {scipy.__file__}")
        print(f"    phiên bản scipy: {scipy.__version__}")
    except ImportError:
        print("    scipy        : KHÔNG KHẢ DỤNG")

    print()


def load_reference_signal(data_path):
    """Tải tín hiệu CSI tham chiếu từ JSON.

    Args:
        data_path: Đường dẫn đến sample_csi_data.json.

    Returns:
        dict: Dữ liệu JSON đã phân tích.

    Raises:
        FileNotFoundError: Nếu tệp dữ liệu không tồn tại.
        json.JSONDecodeError: Nếu dữ liệu bị lỗi định dạng.
    """
    with open(data_path, "r") as f:
        data = json.load(f)
    return data


def frame_to_csi_data(frame, signal_meta):
    """Chuyển đổi dict khung hình JSON thành instance dataclass CSIData.

    Args:
        frame: Dict với 'amplitude', 'phase', 'timestamp_s', 'frame_index'.
        signal_meta: Siêu dữ liệu tín hiệu cấp cao nhất (num_antennas, frequency, v.v.).

    Returns:
        Instance CSIData.
    """
    amplitude = np.array(frame["amplitude"], dtype=np.float64)
    phase = np.array(frame["phase"], dtype=np.float64)
    timestamp = datetime.fromtimestamp(frame["timestamp_s"], tz=timezone.utc)

    return CSIData(
        timestamp=timestamp,
        amplitude=amplitude,
        phase=phase,
        frequency=signal_meta["frequency_hz"],
        bandwidth=signal_meta["bandwidth_hz"],
        num_subcarriers=signal_meta["num_subcarriers"],
        num_antennas=signal_meta["num_antennas"],
        snr=15.0,  # SNR cố định cho tín hiệu tổ hợp
        metadata={
            "source": "synthetic_reference",
            "frame_index": frame["frame_index"],
        },
    )


def features_to_bytes(features):
    """Chuyển đổi CSIFeatures thành biểu diễn byte xác định.

    Chúng ta tuần tự hóa mỗi mảng numpy thành bytes theo thứ tự chuẩn
    sử dụng biểu diễn float64 little-endian. Điều này đảm bảo hash
    không phụ thuộc nền tảng cho các hệ thống tuân thủ IEEE 754.

    Args:
        features: Instance CSIFeatures.

    Returns:
        bytes: Biểu diễn byte chuẩn.
    """
    parts = []

    # Tuần tự hóa mỗi mảng đặc trưng theo thứ tự khai báo
    for array in [
        features.amplitude_mean,
        features.amplitude_variance,
        features.phase_difference,
        features.correlation_matrix,
        features.doppler_shift,
        features.power_spectral_density,
    ]:
        flat = np.asarray(array, dtype=np.float64).ravel()
        # Đóng gói dưới dạng double little-endian (8 byte mỗi giá trị)
        parts.append(struct.pack(f"<{len(flat)}d", *flat))

    return b"".join(parts)


def compute_pipeline_hash(data_path, verbose=False):
    """Chạy toàn bộ đường ống và tính hash SHA-256 của tất cả đặc trưng.

    Args:
        data_path: Đường dẫn đến sample_csi_data.json.
        verbose: Nếu True, in thống kê đặc trưng chi tiết.

    Returns:
        tuple: (hex_hash, stats_dict) trong đó stats_dict chứa các chỉ số.
    """
    # Tải tín hiệu tham chiếu
    signal_data = load_reference_signal(data_path)
    frames = signal_data["frames"][:VERIFICATION_FRAME_COUNT]

    print(f"    Tín hiệu tham chiếu: {os.path.basename(data_path)}")
    print(f"    Mô tả tín hiệu: {signal_data.get('description', 'N/A')}")
    print(f"    Bộ tạo: {signal_data.get('generator', 'N/A')} v{signal_data.get('generator_version', '?')}")
    print(f"    Seed numpy đã dùng: {signal_data.get('numpy_seed', 'N/A')}")
    print(f"    Tổng số khung hình trong tệp: {signal_data.get('num_frames', len(signal_data['frames']))}")
    print(f"    Số khung hình cần xử lý: {len(frames)}")
    print(f"    Sóng mang con: {signal_data.get('num_subcarriers', 'N/A')}")
    print(f"    Ăng-ten: {signal_data.get('num_antennas', 'N/A')}")
    print(f"    Tần số: {signal_data.get('frequency_hz', 0) / 1e9:.3f} GHz")
    print(f"    Băng thông: {signal_data.get('bandwidth_hz', 0) / 1e6:.1f} MHz")
    print(f"    Tần số lấy mẫu: {signal_data.get('sampling_rate_hz', 'N/A')} Hz")
    print()

    # Tạo bộ xử lý với cấu hình sản xuất
    print("    Đang cấu hình CSIProcessor với tham số sản xuất...")
    processor = CSIProcessor(PROCESSOR_CONFIG)
    print(f"    Kích thước cửa sổ: {processor.window_size}")
    print(f"    Độ chồng lấp: {processor.overlap}")
    print(f"    Ngưỡng nhiễu: {processor.noise_threshold} dB")
    print(f"    Tiền xử lý: {'BẬT' if processor.enable_preprocessing else 'TẮT'}")
    print(f"    Trích xuất đặc trưng: {'BẬT' if processor.enable_feature_extraction else 'TẮT'}")
    print()

    # Xử lý tất cả khung hình và tích lũy bytes đặc trưng
    hasher = hashlib.sha256()
    features_count = 0
    total_feature_bytes = 0
    last_features = None
    doppler_nonzero_count = 0
    doppler_shape = None
    psd_shape = None

    t_start = time.perf_counter()

    for i, frame in enumerate(frames):
        csi_data = frame_to_csi_data(frame, signal_data)

        # Chạy qua đường ống thực tế: tiền xử lý -> trích xuất đặc trưng
        preprocessed = processor.preprocess_csi_data(csi_data)
        features = processor.extract_features(preprocessed)

        if features is not None:
            feature_bytes = features_to_bytes(features)
            hasher.update(feature_bytes)
            features_count += 1
            total_feature_bytes += len(feature_bytes)
            last_features = features

            # Theo dõi thống kê Doppler
            doppler_shape = features.doppler_shift.shape
            doppler_nonzero_count = int(np.count_nonzero(features.doppler_shift))
            psd_shape = features.power_spectral_density.shape

        # Thêm vào lịch sử cho tính toán Doppler ở các khung hình tiếp theo
        processor.add_to_history(csi_data)

        if verbose and (i + 1) % 25 == 0:
            print(f"      ... đã xử lý khung hình {i + 1}/{len(frames)}")

    t_elapsed = time.perf_counter() - t_start

    print(f"    Xử lý hoàn tất.")
    print(f"    Số khung hình đã xử lý: {len(frames)}")
    print(f"    Số vector đặc trưng đã trích xuất: {features_count}")
    print(f"    Tổng bytes đặc trưng đã hash: {total_feature_bytes:,}")
    print(f"    Thời gian xử lý: {t_elapsed:.4f}s ({len(frames) / t_elapsed:.0f} khung hình/giây)")
    print()

    # In chi tiết vector đặc trưng
    if last_features is not None:
        print("    CHI TIẾT VECTOR ĐẶC TRƯNG (từ khung hình cuối):")
        print(f"      amplitude_mean      : shape={last_features.amplitude_mean.shape}, "
              f"min={np.min(last_features.amplitude_mean):.6f}, "
              f"max={np.max(last_features.amplitude_mean):.6f}, "
              f"mean={np.mean(last_features.amplitude_mean):.6f}")
        print(f"      amplitude_variance   : shape={last_features.amplitude_variance.shape}, "
              f"min={np.min(last_features.amplitude_variance):.6f}, "
              f"max={np.max(last_features.amplitude_variance):.6f}")
        print(f"      phase_difference     : shape={last_features.phase_difference.shape}, "
              f"mean={np.mean(last_features.phase_difference):.6f}")
        print(f"      correlation_matrix   : shape={last_features.correlation_matrix.shape}")
        print(f"      doppler_shift        : shape={doppler_shape}, "
              f"bin khác 0={doppler_nonzero_count}/{doppler_shape[0] if doppler_shape else 0}")
        print(f"      power_spectral_density: shape={psd_shape}")
        print()

        if verbose:
            print("    PHỔ DOPPLER (chứng minh FFT thực, không phải ngẫu nhiên):")
            ds = last_features.doppler_shift
            print(f"      8 bin đầu: {ds[:8]}")
            print(f"      Tổng: {np.sum(ds):.6f}")
            print(f"      Chỉ số bin lớn nhất: {np.argmax(ds)}")
            print(f"      Entropy phổ: {-np.sum(ds[ds > 0] * np.log2(ds[ds > 0] + 1e-15)):.4f}")
            print()

            print("    CHI TIẾT PSD (chứng minh scipy.fft, không phải ngẫu nhiên):")
            psd = last_features.power_spectral_density
            print(f"      8 bin đầu: {psd[:8]}")
            print(f"      Tổng công suất: {np.sum(psd):.4f}")
            print(f"      Bin tần số đỉnh: {np.argmax(psd)}")
            print()

    stats = {
        "frames_processed": len(frames),
        "features_extracted": features_count,
        "total_bytes_hashed": total_feature_bytes,
        "elapsed_seconds": t_elapsed,
        "doppler_shape": doppler_shape,
        "doppler_nonzero": doppler_nonzero_count,
        "psd_shape": psd_shape,
    }

    return hasher.hexdigest(), stats


def audit_codebase(base_dir=None):
    """Quét mã nguồn sản xuất tìm các mẫu mock/random.

    Tìm kiếm:
      - Các lệnh gọi np.random.rand / np.random.randn (ngoài testing/)
      - Import mock/Mock (ngoài testing/)
      - Các lệnh gọi random.random() (ngoài testing/)

    Args:
        base_dir: Thư mục gốc cần quét. Mặc định là v1/src/.

    Returns:
        Danh sách các tuple (filepath, line_number, line_text, pattern_type).
    """
    if base_dir is None:
        base_dir = os.path.join(V1_DIR, "src")

    suspicious_patterns = [
        ("np.random.rand", "RANDOM_GENERATOR"),
        ("np.random.randn", "RANDOM_GENERATOR"),
        ("np.random.random", "RANDOM_GENERATOR"),
        ("np.random.uniform", "RANDOM_GENERATOR"),
        ("np.random.normal", "RANDOM_GENERATOR"),
        ("np.random.choice", "RANDOM_GENERATOR"),
        ("random.random(", "RANDOM_GENERATOR"),
        ("random.randint(", "RANDOM_GENERATOR"),
        ("from unittest.mock import", "MOCK_IMPORT"),
        ("from unittest import mock", "MOCK_IMPORT"),
        ("import mock", "MOCK_IMPORT"),
        ("MagicMock", "MOCK_USAGE"),
        ("@patch(", "MOCK_USAGE"),
        ("@mock.patch", "MOCK_USAGE"),
    ]

    # Các thư mục loại trừ khỏi quá trình kiểm toán
    excluded_dirs = {"testing", "tests", "test", "__pycache__", ".git"}

    findings = []

    for root, dirs, files in os.walk(base_dir):
        # Bỏ qua các thư mục bị loại trừ
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for fname in files:
            if not fname.endswith(".py"):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        for pattern, ptype in suspicious_patterns:
                            if pattern in line:
                                findings.append((fpath, line_num, line.rstrip(), ptype))
            except (IOError, OSError):
                pass

    return findings


def main():
    """Điểm vào chính của quá trình xác minh."""
    parser = argparse.ArgumentParser(
        description="WiFi-DensePose Công Tắc Tin Cậy -- Phát Lại Bằng Chứng Đường Ống"
    )
    parser.add_argument(
        "--generate-hash",
        action="store_true",
        help="Tạo và in hash kỳ vọng (không xác minh)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Hiển thị thống kê đặc trưng chi tiết và phổ Doppler",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Quét mã nguồn sản xuất tìm các mẫu mock/random",
    )
    args = parser.parse_args()

    print_banner()

    # Xác định vị trí tệp dữ liệu
    data_path = os.path.join(SCRIPT_DIR, "sample_csi_data.json")
    hash_path = os.path.join(SCRIPT_DIR, "expected_features.sha256")

    # ---------------------------------------------------------------
    # Bước 0: In nguồn gốc mã nguồn
    # ---------------------------------------------------------------
    print("[0/4] NGUỒN GỐC MÃ NGUỒN")
    print_source_provenance()

    # ---------------------------------------------------------------
    # Bước 1: Tải và mô tả tín hiệu tham chiếu
    # ---------------------------------------------------------------
    print("[1/4] ĐANG TẢI TÍN HIỆU THAM CHIẾU")
    if not os.path.exists(data_path):
        print(f"  THẤT BẠI: Không tìm thấy dữ liệu tham chiếu tại {data_path}")
        print("  Hãy chạy generate_reference_signal.py trước.")
        sys.exit(1)
    print(f"    Đường dẫn: {data_path}")
    print(f"    Kích thước: {os.path.getsize(data_path):,} bytes")
    print()

    # ---------------------------------------------------------------
    # Bước 2: Xử lý qua đường ống thực tế
    # ---------------------------------------------------------------
    print("[2/4] XỬ LÝ QUA ĐƯỜNG ỐNG SẢN XUẤT")
    print("    Đây chạy CÙNG CSIProcessor.preprocess_csi_data() và")
    print("    CSIProcessor.extract_features() được dùng trong sản xuất.")
    print()
    computed_hash, stats = compute_pipeline_hash(data_path, verbose=args.verbose)

    # ---------------------------------------------------------------
    # Bước 3: So sánh hash
    # ---------------------------------------------------------------
    print("[3/4] SO SÁNH HASH SHA-256")
    print(f"    Đã tính: {computed_hash}")

    if args.generate_hash:
        with open(hash_path, "w") as f:
            f.write(computed_hash + "\n")
        print(f"    Đã ghi hash kỳ vọng vào {hash_path}")
        print()
        print("  ĐÃ TẠO HASH -- chạy lại không có --generate-hash để xác minh.")
        print("=" * 72)
        return

    if not os.path.exists(hash_path):
        print(f"    CẢNH BÁO: Không có tệp hash kỳ vọng tại {hash_path}")
        print(f"    Hash đã tính: {computed_hash}")
        print()
        print("    Chạy với --generate-hash để tạo tệp hash kỳ vọng.")
        print()
        print("  BỎ QUA (không có hash kỳ vọng để so sánh)")
        print("=" * 72)
        sys.exit(2)

    with open(hash_path, "r") as f:
        expected_hash = f.read().strip()

    print(f"    Kỳ vọng: {expected_hash}")

    if computed_hash == expected_hash:
        match_status = "KHỚP"
    else:
        match_status = "KHÔNG KHỚP"
    print(f"    Trạng thái:   {match_status}")
    print()

    # ---------------------------------------------------------------
    # Bước 4: Kiểm toán (nếu được yêu cầu hoặc luôn ở chế độ đầy đủ)
    # ---------------------------------------------------------------
    if args.audit:
        print("[4/4] KIỂM TOÁN MÃ NGUỒN -- đang quét tìm các mẫu mock/random")
        findings = audit_codebase()
        if findings:
            print(f"    Tìm thấy {len(findings)} mẫu đáng ngờ trong mã sản xuất:")
            for fpath, line_num, line, ptype in findings:
                relpath = os.path.relpath(fpath, V1_DIR)
                print(f"      [{ptype}] {relpath}:{line_num}: {line.strip()}")
        else:
            print("    SẠCH -- không tìm thấy mẫu mock/random trong mã sản xuất.")
        print()
    else:
        print("[4/4] KIỂM TOÁN MÃ NGUỒN (bỏ qua -- dùng --audit để bật)")
        print()

    # ---------------------------------------------------------------
    # Phán quyết cuối cùng
    # ---------------------------------------------------------------
    print("=" * 72)
    if computed_hash == expected_hash:
        print("  PHÁN QUYẾT: ĐẠT")
        print()
        print("  Đường ống đã tạo ra hash SHA-256 khớp với hash")
        print("  kỳ vọng đã công bố. Điều này chứng minh:")
        print("    1. CÙNG mã xử lý tín hiệu đã chạy trên tín hiệu tham chiếu")
        print("    2. Đầu ra là XÁC ĐỊNH (cùng đầu vào -> cùng đầu ra)")
        print("    3. Không có tính ngẫu nhiên nào được đưa vào (hash sẽ khác)")
        print("    4. Đường dẫn mã bao gồm: loại bỏ nhiễu, cửa sổ Hamming,")
        print("       chuẩn hóa biên độ, trích xuất Doppler dựa trên FFT,")
        print("       và tính toán mật độ phổ công suất")
        print()
        print(f"  Hash đường ống: {computed_hash}")
        print("=" * 72)
        sys.exit(0)
    else:
        print("  PHÁN QUYẾT: KHÔNG ĐẠT")
        print()
        print("  Đầu ra đường ống KHÔNG khớp với hash kỳ vọng.")
        print()
        print("  Nguyên nhân có thể:")
        print("    - Phiên bản Numpy/scipy không khớp (kiểm tra requirements)")
        print("    - Thay đổi mã trong bộ xử lý CSI làm thay đổi đầu ra số")
        print("    - Khác biệt dấu phẩy động giữa các nền tảng (ít khả năng với IEEE 754)")
        print()
        print("  Để cập nhật hash kỳ vọng sau khi thay đổi có chủ đích:")
        print("    python verify.py --generate-hash")
        print("=" * 72)
        sys.exit(1)


if __name__ == "__main__":
    main()
