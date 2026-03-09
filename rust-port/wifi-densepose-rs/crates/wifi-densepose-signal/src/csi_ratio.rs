//! Nhân liên hợp (Mô hình tỷ lệ CSI)
//!
//! Triệt tiêu độ lệch tần số sóng mang (CFO), độ lệch tần số lấy mẫu (SFO),
//! và trễ phát hiện gói tin bằng cách tính `H_i[k] * conj(H_j[k])` qua
//! các cặp anten. Pha kết quả chỉ phản ánh thay đổi môi trường
//! (chuyển động con người), không phải tạo tác phần cứng.
//!
//! # Tài liệu tham khảo
//! - SpotFi: Decimeter Level Localization Using WiFi (SIGCOMM 2015)
//! - IndoTrack: Device-Free Indoor Human Tracking (MobiCom 2017)

use ndarray::Array2;
use num_complex::Complex64;

/// Tính tỷ lệ CSI giữa hai luồng anten.
///
/// Với mỗi sóng mang con k: `ratio[k] = H_ref[k] * conj(H_target[k])`
///
/// Điều này triệt tiêu độ lệch pha phần cứng (CFO, SFO, PDD) chung
/// giữa hai anten, chỉ giữ lại pha hiệu đường truyền
/// gây ra bởi lan truyền tín hiệu qua môi trường.
pub fn conjugate_multiply(
    h_ref: &[Complex64],
    h_target: &[Complex64],
) -> Result<Vec<Complex64>, CsiRatioError> {
    if h_ref.len() != h_target.len() {
        return Err(CsiRatioError::LengthMismatch {
            ref_len: h_ref.len(),
            target_len: h_target.len(),
        });
    }
    if h_ref.is_empty() {
        return Err(CsiRatioError::EmptyInput);
    }

    Ok(h_ref
        .iter()
        .zip(h_target.iter())
        .map(|(r, t)| r * t.conj())
        .collect())
}

/// Tính ma trận tỷ lệ CSI cho tất cả cặp anten từ ảnh chụp CSI đa anten.
///
/// Đầu vào: `csi_complex` là CSI phức (num_antennas × num_subcarriers).
/// Đầu ra: Với mỗi cặp (i, j) trong đó j > i, một hàng giá trị nhân liên hợp.
/// Trả về ma trận (num_pairs × num_subcarriers).
pub fn compute_ratio_matrix(csi_complex: &Array2<Complex64>) -> Result<Array2<Complex64>, CsiRatioError> {
    let (n_ant, n_sc) = csi_complex.dim();
    if n_ant < 2 {
        return Err(CsiRatioError::InsufficientAntennas { count: n_ant });
    }

    let n_pairs = n_ant * (n_ant - 1) / 2;
    let mut ratio_matrix = Array2::zeros((n_pairs, n_sc));
    let mut pair_idx = 0;

    for i in 0..n_ant {
        for j in (i + 1)..n_ant {
            let ref_row: Vec<Complex64> = csi_complex.row(i).to_vec();
            let target_row: Vec<Complex64> = csi_complex.row(j).to_vec();
            let ratio = conjugate_multiply(&ref_row, &target_row)?;
            for (k, &val) in ratio.iter().enumerate() {
                ratio_matrix[[pair_idx, k]] = val;
            }
            pair_idx += 1;
        }
    }

    Ok(ratio_matrix)
}

/// Trích xuất biên độ và pha đã làm sạch từ ma trận tỷ lệ CSI.
///
/// Trả về (biên độ, pha) mỗi cái là (num_pairs × num_subcarriers).
pub fn ratio_to_amplitude_phase(ratio: &Array2<Complex64>) -> (Array2<f64>, Array2<f64>) {
    let (nrows, ncols) = ratio.dim();
    let mut amplitude = Array2::zeros((nrows, ncols));
    let mut phase = Array2::zeros((nrows, ncols));

    for ((i, j), val) in ratio.indexed_iter() {
        amplitude[[i, j]] = val.norm();
        phase[[i, j]] = val.arg();
    }

    (amplitude, phase)
}

/// Các lỗi từ tính toán tỷ lệ CSI
#[derive(Debug, thiserror::Error)]
pub enum CsiRatioError {
    #[error("Độ dài luồng anten không khớp: ref={ref_len}, target={target_len}")]
    LengthMismatch { ref_len: usize, target_len: usize },

    #[error("Đầu vào rỗng")]
    EmptyInput,

    #[error("Cần ít nhất 2 anten, có {count}")]
    InsufficientAntennas { count: usize },
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::PI;

    #[test]
    fn test_conjugate_multiply_cancels_common_phase() {
        // Cả hai anten đều thấy cùng độ lệch pha CFO θ.
        // H_1[k] = A1 * exp(j*(φ1 + θ)),  H_2[k] = A2 * exp(j*(φ2 + θ))
        // ratio = H_1 * conj(H_2) = A1*A2 * exp(j*(φ1 - φ2))
        // Độ lệch chung θ bị triệt tiêu.
        let cfo_offset = 1.7; // độ lệch CFO tùy ý
        let phi1 = 0.3;
        let phi2 = 0.8;

        let h1 = vec![Complex64::from_polar(2.0, phi1 + cfo_offset)];
        let h2 = vec![Complex64::from_polar(3.0, phi2 + cfo_offset)];

        let ratio = conjugate_multiply(&h1, &h2).unwrap();
        let result_phase = ratio[0].arg();
        let result_amp = ratio[0].norm();

        // Pha phải là φ1 - φ2, CFO đã triệt tiêu
        assert!((result_phase - (phi1 - phi2)).abs() < 1e-10);
        // Biên độ phải là A1 * A2
        assert!((result_amp - 6.0).abs() < 1e-10);
    }

    #[test]
    fn test_ratio_matrix_pair_count() {
        // 3 anten → 3 cặp, 4 anten → 6 cặp
        let csi = Array2::from_shape_fn((3, 10), |(i, j)| {
            Complex64::from_polar(1.0, (i * 10 + j) as f64 * 0.1)
        });

        let ratio = compute_ratio_matrix(&csi).unwrap();
        assert_eq!(ratio.dim(), (3, 10)); // C(3,2) = 3 cặp

        let csi4 = Array2::from_shape_fn((4, 8), |(i, j)| {
            Complex64::from_polar(1.0, (i * 8 + j) as f64 * 0.1)
        });
        let ratio4 = compute_ratio_matrix(&csi4).unwrap();
        assert_eq!(ratio4.dim(), (6, 8)); // C(4,2) = 6 cặp
    }

    #[test]
    fn test_ratio_preserves_path_difference() {
        // Hai anten cách nhau d, tín hiệu từ góc θ
        // Hiệu pha = 2π * d * sin(θ) / λ
        let wavelength = 0.06; // 5 GHz
        let antenna_spacing = 0.025; // 2.5 cm
        let arrival_angle = PI / 6.0; // 30 độ

        let path_diff_phase = 2.0 * PI * antenna_spacing * arrival_angle.sin() / wavelength;
        let cfo = 2.5; // CFO lớn

        let n_sc = 56;
        let csi = Array2::from_shape_fn((2, n_sc), |(ant, k)| {
            let sc_phase = k as f64 * 0.05; // pha phụ thuộc sóng mang con
            let ant_phase = if ant == 0 { 0.0 } else { path_diff_phase };
            Complex64::from_polar(1.0, sc_phase + ant_phase + cfo)
        });

        let ratio = compute_ratio_matrix(&csi).unwrap();
        let (_, phase) = ratio_to_amplitude_phase(&ratio);

        // Tất cả sóng mang con phải hiển thị cùng pha hiệu đường truyền
        for j in 0..n_sc {
            assert!(
                (phase[[0, j]] - (-path_diff_phase)).abs() < 1e-10,
                "Sóng mang con {} pha={}, kỳ vọng={}",
                j, phase[[0, j]], -path_diff_phase
            );
        }
    }

    #[test]
    fn test_single_antenna_error() {
        let csi = Array2::from_shape_fn((1, 10), |(_, j)| {
            Complex64::new(j as f64, 0.0)
        });
        assert!(matches!(
            compute_ratio_matrix(&csi),
            Err(CsiRatioError::InsufficientAntennas { .. })
        ));
    }

    #[test]
    fn test_length_mismatch() {
        let h1 = vec![Complex64::new(1.0, 0.0); 10];
        let h2 = vec![Complex64::new(1.0, 0.0); 5];
        assert!(matches!(
            conjugate_multiply(&h1, &h2),
            Err(CsiRatioError::LengthMismatch { .. })
        ));
    }
}
