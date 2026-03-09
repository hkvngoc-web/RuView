#!/usr/bin/env python3
"""
Bộ Tạo Tín Hiệu CSI Tham Chiếu Xác Định cho Gói Bằng Chứng WiFi-DensePose.

Script này tạo một tín hiệu CSI (Thông tin Trạng thái Kênh) tham chiếu
TỔ HỢP, XÁC ĐỊNH để xác minh đường ống. Đây KHÔNG phải bản ghi WiFi thực.

Tín hiệu mô phỏng hệ thống WiFi 3 ăng-ten, 56 sóng mang con với:
  - Điều chế hơi thở con người tại 0.3 Hz
  - Điều chế chuyển động đi bộ tại 1.2 Hz
  - Truyền đa đường xác định (có cấu trúc) với độ trễ đã biết
  - 10 giây dữ liệu ở tần số lấy mẫu 100 Hz (tổng cộng 1000 khung hình)

Công Thức Tạo Tín Hiệu
========================

Cho mỗi khung hình t (t = 0..999) tại thời điểm s = t / 100.0:

  CSI[ăng_ten_a, sóng_mang_con_k] = tổng trên P đường dẫn của:
      A_p * exp(j * (2*pi*f_k*tau_p + phi_p,a))
      * (1 + alpha_hơi_thở * sin(2*pi * 0.3 * s + psi_hơi_thở_a))
      * (1 + alpha_đi_bộ   * sin(2*pi * 1.2 * s + psi_đi_bộ_a))

Trong đó:
  - f_k = tần_số_trung_tâm + (k - 28) * khoảng_cách_sóng_mang_con  [tần số sóng mang con]
  - tau_p = độ trễ đường dẫn xác định cho đường dẫn p
  - A_p = biên độ đường dẫn xác định cho đường dẫn p
  - phi_p,a = độ lệch pha xác định theo đường dẫn theo ăng-ten
  - alpha_hơi_thở = 0.02 (độ sâu điều chế hơi thở)
  - alpha_đi_bộ = 0.08 (độ sâu điều chế đi bộ)
  - psi_hơi_thở_a, psi_đi_bộ_a = độ lệch pha xác định theo ăng-ten

Tất cả tham số được tính từ numpy với seed=42. Không sử dụng tính ngẫu nhiên
tại thời điểm tạo -- seed CHỈ được dùng để chọn giá trị tham số cố định
một lần, sau đó được ghi lại trong tệp siêu dữ liệu.

Đầu ra:
  - sample_csi_data.json: Tất cả 1000 khung hình CSI với mảng biên độ và pha
  - sample_csi_meta.json: Tài liệu tham số đầy đủ

Tác giả: Dự án WiFi-DensePose (dữ liệu kiểm thử tổ hợp)
"""

import json
import os
import sys

import numpy as np


def generate_deterministic_parameters():
    """Tạo tất cả tham số cố định sử dụng seed=42.

    Các tham số này xác định mô hình kênh đa đường và điều chế
    chuyển động con người. Sau khi tạo, chúng là hằng số -- không
    sử dụng thêm tính ngẫu nhiên nào.

    Returns:
        dict: Tất cả tham số kênh và chuyển động.
    """
    rng = np.random.RandomState(42)

    # Tham số hệ thống (cố định theo thiết kế, không ngẫu nhiên)
    num_antennas = 3
    num_subcarriers = 56
    sampling_rate_hz = 100
    duration_s = 10.0
    center_freq_hz = 5.21e9  # Kênh WiFi 5 GHz số 42
    subcarrier_spacing_hz = 312.5e3  # Chuẩn 802.11n/ac

    # Kênh đa đường: 5 đường dẫn xác định
    num_paths = 5
    # Độ trễ đường dẫn tính bằng nano giây (điển hình trong nhà)
    path_delays_ns = np.array([0.0, 15.0, 42.0, 78.0, 120.0])
    # Biên độ đường dẫn (thang tuyến tính, giảm theo độ trễ)
    path_amplitudes = np.array([1.0, 0.6, 0.35, 0.18, 0.08])
    # Độ lệch pha theo đường dẫn theo ăng-ten (từ seed=42, sau đó cố định)
    path_phase_offsets = rng.uniform(-np.pi, np.pi, size=(num_paths, num_antennas))

    # Tham số điều chế chuyển động con người
    breathing_freq_hz = 0.3
    walking_freq_hz = 1.2
    breathing_depth = 0.02  # Điều chế biên độ 2%
    walking_depth = 0.08    # Điều chế biên độ 8%

    # Độ lệch pha theo ăng-ten cho tín hiệu chuyển động (từ seed=42, sau đó cố định)
    breathing_phase_offsets = rng.uniform(0, 2 * np.pi, size=num_antennas)
    walking_phase_offsets = rng.uniform(0, 2 * np.pi, size=num_antennas)

    return {
        "num_antennas": num_antennas,
        "num_subcarriers": num_subcarriers,
        "sampling_rate_hz": sampling_rate_hz,
        "duration_s": duration_s,
        "center_freq_hz": center_freq_hz,
        "subcarrier_spacing_hz": subcarrier_spacing_hz,
        "num_paths": num_paths,
        "path_delays_ns": path_delays_ns,
        "path_amplitudes": path_amplitudes,
        "path_phase_offsets": path_phase_offsets,
        "breathing_freq_hz": breathing_freq_hz,
        "walking_freq_hz": walking_freq_hz,
        "breathing_depth": breathing_depth,
        "walking_depth": walking_depth,
        "breathing_phase_offsets": breathing_phase_offsets,
        "walking_phase_offsets": walking_phase_offsets,
    }


def generate_csi_frames(params):
    """Tạo tất cả khung hình CSI một cách xác định từ các tham số đã cho.

    Args:
        params: Dict các tham số kênh/chuyển động.

    Returns:
        list: Danh sách các dict, mỗi dict chứa mảng biên độ và pha
              cho một khung hình, cùng dấu thời gian.
    """
    num_antennas = params["num_antennas"]
    num_subcarriers = params["num_subcarriers"]
    sampling_rate = params["sampling_rate_hz"]
    duration = params["duration_s"]
    center_freq = params["center_freq_hz"]
    subcarrier_spacing = params["subcarrier_spacing_hz"]
    num_paths = params["num_paths"]
    path_delays_ns = params["path_delays_ns"]
    path_amplitudes = params["path_amplitudes"]
    path_phase_offsets = params["path_phase_offsets"]
    breathing_freq = params["breathing_freq_hz"]
    walking_freq = params["walking_freq_hz"]
    breathing_depth = params["breathing_depth"]
    walking_depth = params["walking_depth"]
    breathing_phase = params["breathing_phase_offsets"]
    walking_phase = params["walking_phase_offsets"]

    num_frames = int(duration * sampling_rate)

    # Tính trước tần số sóng mang con so với trung tâm
    k_indices = np.arange(num_subcarriers) - num_subcarriers // 2
    subcarrier_freqs = center_freq + k_indices * subcarrier_spacing

    # Chuyển đổi độ trễ đường dẫn sang giây
    path_delays_s = path_delays_ns * 1e-9

    frames = []
    for frame_idx in range(num_frames):
        t = frame_idx / sampling_rate

        # Xây dựng ma trận CSI phức: (num_antennas, num_subcarriers)
        csi_complex = np.zeros((num_antennas, num_subcarriers), dtype=complex)

        for a in range(num_antennas):
            # Điều chế chuyển động con người cho ăng-ten này tại thời điểm này
            breathing_mod = 1.0 + breathing_depth * np.sin(
                2.0 * np.pi * breathing_freq * t + breathing_phase[a]
            )
            walking_mod = 1.0 + walking_depth * np.sin(
                2.0 * np.pi * walking_freq * t + walking_phase[a]
            )
            motion_factor = breathing_mod * walking_mod

            for p in range(num_paths):
                # Dịch pha từ độ trễ đường dẫn qua các sóng mang con
                phase_from_delay = 2.0 * np.pi * subcarrier_freqs * path_delays_s[p]
                # Cộng thêm độ lệch theo đường dẫn theo ăng-ten
                total_phase = phase_from_delay + path_phase_offsets[p, a]
                # Tích lũy đóng góp đường dẫn
                csi_complex[a, :] += (
                    path_amplitudes[p] * motion_factor * np.exp(1j * total_phase)
                )

        amplitude = np.abs(csi_complex)
        phase = np.angle(csi_complex)  # trong [-pi, pi]

        frames.append({
            "frame_index": frame_idx,
            "timestamp_s": round(t, 4),
            "amplitude": amplitude.tolist(),
            "phase": phase.tolist(),
        })

    return frames


def save_data(frames, params, output_dir):
    """Lưu các khung hình CSI và siêu dữ liệu vào tệp JSON.

    Args:
        frames: Danh sách các dict khung hình CSI.
        params: Tham số tạo tín hiệu.
        output_dir: Thư mục ghi tệp đầu ra.
    """
    # Lưu dữ liệu CSI
    csi_data = {
        "description": (
            "Tín hiệu CSI tham chiếu xác định TỔ HỢP để xác minh đường ống. "
            "Đây KHÔNG phải bản ghi WiFi thực. Được tạo toán học với các tham số "
            "đã biết cho mục đích kiểm thử tính tái tạo."
        ),
        "generator": "generate_reference_signal.py",
        "generator_version": "1.0.0",
        "numpy_seed": 42,
        "num_frames": len(frames),
        "num_antennas": params["num_antennas"],
        "num_subcarriers": params["num_subcarriers"],
        "sampling_rate_hz": params["sampling_rate_hz"],
        "frequency_hz": params["center_freq_hz"],
        "bandwidth_hz": params["subcarrier_spacing_hz"] * params["num_subcarriers"],
        "frames": frames,
    }

    data_path = os.path.join(output_dir, "sample_csi_data.json")
    with open(data_path, "w") as f:
        json.dump(csi_data, f, indent=2)
    print(f"Đã ghi {len(frames)} khung hình vào {data_path}")

    # Lưu siêu dữ liệu
    meta = {
        "description": (
            "Siêu dữ liệu cho tín hiệu CSI tham chiếu xác định TỔ HỢP. "
            "Ghi lại tất cả tham số tạo tín hiệu để có thể tái tạo "
            "và xác minh độc lập."
        ),
        "is_synthetic": True,
        "is_real_capture": False,
        "generator_script": "generate_reference_signal.py",
        "numpy_seed": 42,
        "system_parameters": {
            "num_antennas": params["num_antennas"],
            "num_subcarriers": params["num_subcarriers"],
            "sampling_rate_hz": params["sampling_rate_hz"],
            "duration_s": params["duration_s"],
            "center_frequency_hz": params["center_freq_hz"],
            "subcarrier_spacing_hz": params["subcarrier_spacing_hz"],
            "total_frames": int(params["duration_s"] * params["sampling_rate_hz"]),
        },
        "multipath_channel": {
            "num_paths": params["num_paths"],
            "path_delays_ns": params["path_delays_ns"].tolist(),
            "path_amplitudes": params["path_amplitudes"].tolist(),
            "path_phase_offsets_rad": params["path_phase_offsets"].tolist(),
            "description": (
                "Mô hình đa đường trong nhà 5 đường dẫn với độ trễ và "
                "biên độ xác định. Biên độ đường dẫn giảm theo độ trễ (điển hình trong nhà)."
            ),
        },
        "human_motion_signals": {
            "breathing": {
                "frequency_hz": params["breathing_freq_hz"],
                "modulation_depth": params["breathing_depth"],
                "per_antenna_phase_offsets_rad": params["breathing_phase_offsets"].tolist(),
                "description": (
                    "Điều chế biên độ hình sin tại 0.3 Hz mô phỏng hơi thở "
                    "con người (nhịp thở người lớn nghỉ ngơi: 12-20 lần/phút = 0.2-0.33 Hz)."
                ),
            },
            "walking": {
                "frequency_hz": params["walking_freq_hz"],
                "modulation_depth": params["walking_depth"],
                "per_antenna_phase_offsets_rad": params["walking_phase_offsets"].tolist(),
                "description": (
                    "Điều chế biên độ hình sin tại 1.2 Hz mô phỏng chuyển động "
                    "đi bộ con người (nhịp bước chân điển hình: ~1.0-1.4 Hz)."
                ),
            },
        },
        "generation_formula": (
            "CSI[a,k,t] = sum_p { A_p * exp(j*(2*pi*f_k*tau_p + phi_{p,a})) "
            "* (1 + d_hơi_thở * sin(2*pi*0.3*t + psi_hơi_thở_a)) "
            "* (1 + d_đi_bộ * sin(2*pi*1.2*t + psi_đi_bộ_a)) }"
        ),
        "determinism_guarantee": (
            "Tất cả tham số được dẫn xuất từ numpy.random.RandomState(42) tại "
            "thời điểm khởi tạo script. Vòng lặp tạo tín hiệu KHÔNG sử dụng "
            "tính ngẫu nhiên. Chạy script này trên bất kỳ nền tảng nào với cùng "
            "phiên bản numpy sẽ tạo ra đầu ra giống hệt bit."
        ),
    }

    meta_path = os.path.join(output_dir, "sample_csi_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Đã ghi siêu dữ liệu vào {meta_path}")


def main():
    """Điểm vào chính."""
    # Xác định thư mục đầu ra
    output_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 70)
    print("WiFi-DensePose: Bộ Tạo Tín Hiệu CSI Tham Chiếu Xác Định")
    print("=" * 70)
    print(f"Thư mục đầu ra: {output_dir}")
    print()

    # Bước 1: Tạo tham số xác định
    print("[1/3] Đang tạo tham số kênh xác định (seed=42)...")
    params = generate_deterministic_parameters()
    print(f"  - {params['num_paths']} đường dẫn đa đường")
    print(f"  - {params['num_antennas']} ăng-ten, {params['num_subcarriers']} sóng mang con")
    print(f"  - Hơi thở: {params['breathing_freq_hz']} Hz, độ sâu={params['breathing_depth']}")
    print(f"  - Đi bộ: {params['walking_freq_hz']} Hz, độ sâu={params['walking_depth']}")
    print()

    # Bước 2: Tạo tất cả khung hình
    num_frames = int(params["duration_s"] * params["sampling_rate_hz"])
    print(f"[2/3] Đang tạo {num_frames} khung hình CSI...")
    print(f"  - Thời lượng: {params['duration_s']}s ở {params['sampling_rate_hz']} Hz")
    frames = generate_csi_frames(params)
    print(f"  - Đã tạo {len(frames)} khung hình")
    print()

    # Bước 3: Lưu đầu ra
    print("[3/3] Đang lưu tệp đầu ra...")
    save_data(frames, params, output_dir)
    print()
    print("Hoàn tất. Tín hiệu tham chiếu đã được tạo thành công.")
    print("=" * 70)


if __name__ == "__main__":
    main()
