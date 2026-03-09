//! Trích xuất hồ sơ vận tốc cơ thể (BVP).
//!
//! BVP là biểu diễn 2D không phụ thuộc miền (vận tốc × thời gian) mã hóa
//! cách các bộ phận cơ thể khác nhau chuyển động ở các tốc độ khác nhau. Vì BVP nắm bắt
//! phân phối vận tốc thay vì giá trị CSI thô, nó tổng quát hóa qua
//! các môi trường (phòng khác nhau, nội thất, vị trí AP).
//!
//! # Thuật toán
//! 1. Áp dụng STFT cho luồng biên độ theo thời gian của mỗi sóng mang con
//! 2. Ánh xạ bin tần số sang vận tốc qua v = f_doppler * λ / 2
//! 3. Tổng hợp |STFT| qua các sóng mang con để tạo BVP
//!
//! # Tài liệu tham khảo
//! - Widar 3.0: Zero-Effort Cross-Domain Gesture Recognition (MobiSys 2019)

use ndarray::Array2;
use num_complex::Complex64;
use ruvector_attention::ScaledDotProductAttention;
use ruvector_attention::traits::Attention;
use rustfft::FftPlanner;
use std::f64::consts::PI;

/// Cấu hình cho trích xuất BVP.
#[derive(Debug, Clone)]
pub struct BvpConfig {
    /// Kích thước cửa sổ STFT (số mẫu)
    pub window_size: usize,
    /// Bước nhảy STFT (số mẫu)
    pub hop_size: usize,
    /// Tần số sóng mang tính bằng Hz (cho ánh xạ vận tốc)
    pub carrier_frequency: f64,
    /// Số bin vận tốc đầu ra
    pub n_velocity_bins: usize,
    /// Vận tốc tối đa có thể phân giải (m/s)
    pub max_velocity: f64,
}

impl Default for BvpConfig {
    fn default() -> Self {
        Self {
            window_size: 128,
            hop_size: 32,
            carrier_frequency: 5.0e9,
            n_velocity_bins: 64,
            max_velocity: 2.0,
        }
    }
}

/// Kết quả hồ sơ vận tốc cơ thể.
#[derive(Debug, Clone)]
pub struct BodyVelocityProfile {
    /// Ma trận BVP: (n_velocity_bins × n_time_frames)
    /// Mỗi cột là phân phối vận tốc tại một thời điểm.
    pub data: Array2<f64>,
    /// Giá trị vận tốc cho mỗi bin hàng (m/s)
    pub velocity_bins: Vec<f64>,
    /// Số khung thời gian
    pub n_time: usize,
    /// Độ phân giải thời gian (giây mỗi khung)
    pub time_resolution: f64,
    /// Độ phân giải vận tốc (m/s mỗi bin)
    pub velocity_resolution: f64,
}

/// Trích xuất hồ sơ vận tốc cơ thể từ dữ liệu CSI theo thời gian.
///
/// `csi_temporal`: ma trận biên độ (num_samples × num_subcarriers)
/// `sample_rate`: tần số lấy mẫu tính bằng Hz
pub fn extract_bvp(
    csi_temporal: &Array2<f64>,
    sample_rate: f64,
    config: &BvpConfig,
) -> Result<BodyVelocityProfile, BvpError> {
    let (n_samples, n_sc) = csi_temporal.dim();

    if n_samples < config.window_size {
        return Err(BvpError::InsufficientSamples {
            needed: config.window_size,
            got: n_samples,
        });
    }
    if n_sc == 0 {
        return Err(BvpError::NoSubcarriers);
    }
    if config.hop_size == 0 || config.window_size == 0 {
        return Err(BvpError::InvalidConfig("window_size và hop_size phải > 0".into()));
    }

    let wavelength = 2.998e8 / config.carrier_frequency;
    let n_frames = (n_samples - config.window_size) / config.hop_size + 1;
    let n_fft_bins = config.window_size / 2 + 1;

    // Cửa sổ Hann
    let window: Vec<f64> = (0..config.window_size)
        .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f64 / (config.window_size - 1) as f64).cos()))
        .collect();

    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(config.window_size);

    // Tính biên độ STFT cho mỗi sóng mang con, sau đó tổng hợp
    let mut aggregated = Array2::zeros((n_fft_bins, n_frames));

    for sc in 0..n_sc {
        let col: Vec<f64> = csi_temporal.column(sc).to_vec();

        // Loại bỏ DC khỏi sóng mang con này
        let mean: f64 = col.iter().sum::<f64>() / col.len() as f64;

        for frame in 0..n_frames {
            let start = frame * config.hop_size;

            let mut buffer: Vec<Complex64> = col[start..start + config.window_size]
                .iter()
                .zip(window.iter())
                .map(|(&s, &w)| Complex64::new((s - mean) * w, 0.0))
                .collect();

            fft.process(&mut buffer);

            // Tích lũy biên độ qua các sóng mang con
            for bin in 0..n_fft_bins {
                aggregated[[bin, frame]] += buffer[bin].norm();
            }
        }
    }

    // Chuẩn hóa theo số sóng mang con
    aggregated /= n_sc as f64;

    // Ánh xạ bin FFT sang bin vận tốc
    let freq_resolution = sample_rate / config.window_size as f64;
    let velocity_resolution = config.max_velocity * 2.0 / config.n_velocity_bins as f64;

    let velocity_bins: Vec<f64> = (0..config.n_velocity_bins)
        .map(|i| -config.max_velocity + i as f64 * velocity_resolution)
        .collect();

    // Lấy mẫu lại bin FFT sang bin vận tốc sử dụng v = f_doppler * λ / 2
    let mut bvp = Array2::zeros((config.n_velocity_bins, n_frames));

    for (v_idx, &velocity) in velocity_bins.iter().enumerate() {
        // Chuyển đổi vận tốc sang tần số Doppler
        let doppler_freq = 2.0 * velocity / wavelength;
        // Chuyển đổi sang chỉ số bin FFT
        let fft_bin = (doppler_freq.abs() / freq_resolution).round() as usize;

        if fft_bin < n_fft_bins {
            for frame in 0..n_frames {
                bvp[[v_idx, frame]] = aggregated[[fft_bin, frame]];
            }
        }
    }

    Ok(BodyVelocityProfile {
        data: bvp,
        velocity_bins,
        n_time: n_frames,
        time_resolution: config.hop_size as f64 / sample_rate,
        velocity_resolution,
    })
}

/// Các lỗi từ trích xuất BVP.
#[derive(Debug, thiserror::Error)]
pub enum BvpError {
    #[error("Không đủ mẫu: cần {needed}, có {got}")]
    InsufficientSamples { needed: usize, got: usize },

    #[error("Không có sóng mang con trong đầu vào")]
    NoSubcarriers,

    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),
}

/// Tính tổng hợp BVP có trọng số attention qua các sóng mang con.
///
/// Sử dụng ScaledDotProductAttention để đánh trọng số hồ sơ vận tốc
/// của mỗi sóng mang con theo mức liên quan đến truy vấn chuyển động cơ thể tổng thể.
/// Các sóng mang con ở vùng triệt tiêu đa đường nhận trọng số attention thấp tự động.
///
/// # Tham số
/// * `stft_rows` - Biên độ STFT theo từng sóng mang con: Vec các lát `[n_velocity_bins]`
/// * `sensitivity` - Điểm nhạy theo từng sóng mang con (cao hơn = phản hồi chuyển động tốt hơn)
/// * `n_velocity_bins` - Số bin vận tốc (d cho attention)
///
/// # Trả về
/// BVP có trọng số attention dạng Vec<f32> với độ dài n_velocity_bins
pub fn attention_weighted_bvp(
    stft_rows: &[Vec<f32>],
    sensitivity: &[f32],
    n_velocity_bins: usize,
) -> Vec<f32> {
    if stft_rows.is_empty() || n_velocity_bins == 0 {
        return vec![0.0; n_velocity_bins];
    }

    let attn = ScaledDotProductAttention::new(n_velocity_bins);
    let sens_sum: f32 = sensitivity.iter().sum::<f32>().max(1e-9);

    // Truy vấn: trung bình có trọng số nhạy của tất cả hồ sơ sóng mang con
    let query: Vec<f32> = (0..n_velocity_bins)
        .map(|v| {
            stft_rows
                .iter()
                .zip(sensitivity.iter())
                .map(|(row, &s)| {
                    row.get(v).copied().unwrap_or(0.0) * s
                })
                .sum::<f32>()
                / sens_sum
        })
        .collect();

    let keys: Vec<&[f32]> = stft_rows.iter().map(|r| r.as_slice()).collect();
    let values: Vec<&[f32]> = stft_rows.iter().map(|r| r.as_slice()).collect();

    attn.compute(&query, &keys, &values)
        .unwrap_or_else(|_| {
            // Phương án dự phòng: tổng có trọng số đơn giản
            (0..n_velocity_bins)
                .map(|v| {
                    stft_rows
                        .iter()
                        .zip(sensitivity.iter())
                        .map(|(row, &s)| row.get(v).copied().unwrap_or(0.0) * s)
                        .sum::<f32>()
                        / sens_sum
                })
                .collect()
        })
}

#[cfg(test)]
mod attn_bvp_tests {
    use super::*;

    #[test]
    fn attention_bvp_output_shape() {
        let n_sc = 4_usize;
        let n_vbins = 8_usize;
        let stft_rows: Vec<Vec<f32>> = (0..n_sc)
            .map(|i| vec![i as f32 * 0.1; n_vbins])
            .collect();
        let sensitivity = vec![0.9_f32, 0.1, 0.8, 0.2];
        let bvp = attention_weighted_bvp(&stft_rows, &sensitivity, n_vbins);
        assert_eq!(bvp.len(), n_vbins);
        assert!(bvp.iter().all(|x| x.is_finite()));
    }

    #[test]
    fn attention_bvp_empty_input() {
        let bvp = attention_weighted_bvp(&[], &[], 8);
        assert_eq!(bvp.len(), 8);
        assert!(bvp.iter().all(|&x| x == 0.0));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bvp_dimensions() {
        let n_samples = 1000;
        let n_sc = 10;
        let csi = Array2::from_shape_fn((n_samples, n_sc), |(t, sc)| {
            let freq = 1.0 + sc as f64 * 0.3;
            (2.0 * PI * freq * t as f64 / 100.0).sin()
        });

        let config = BvpConfig {
            window_size: 128,
            hop_size: 32,
            n_velocity_bins: 64,
            ..Default::default()
        };

        let bvp = extract_bvp(&csi, 100.0, &config).unwrap();
        assert_eq!(bvp.data.dim().0, 64); // bin vận tốc
        let expected_frames = (1000 - 128) / 32 + 1;
        assert_eq!(bvp.n_time, expected_frames);
        assert_eq!(bvp.velocity_bins.len(), 64);
    }

    #[test]
    fn test_bvp_velocity_range() {
        let csi = Array2::from_shape_fn((500, 5), |(t, _)| (t as f64 * 0.05).sin());

        let config = BvpConfig {
            max_velocity: 3.0,
            n_velocity_bins: 60,
            window_size: 64,
            hop_size: 16,
            ..Default::default()
        };

        let bvp = extract_bvp(&csi, 100.0, &config).unwrap();

        // Bin vận tốc nên trải trong khoảng [-3.0, +3.0)
        assert!(bvp.velocity_bins[0] < 0.0);
        assert!(*bvp.velocity_bins.last().unwrap() > 0.0);
        assert!((bvp.velocity_bins[0] - (-3.0)).abs() < 0.2);
    }

    #[test]
    fn test_static_scene_low_velocity() {
        // Tín hiệu không đổi → không có Doppler → BVP nên đạt đỉnh tại velocity=0
        let csi = Array2::from_elem((500, 10), 1.0);

        let config = BvpConfig {
            window_size: 64,
            hop_size: 32,
            n_velocity_bins: 32,
            max_velocity: 1.0,
            ..Default::default()
        };

        let bvp = extract_bvp(&csi, 100.0, &config).unwrap();

        // Sau khi loại bỏ DC và áp dụng cửa sổ, tín hiệu không đổi có
        // năng lượng gần 0 tại tất cả tần số Doppler
        let total_energy: f64 = bvp.data.iter().sum();
        // Với tín hiệu không đổi có DC đã loại bỏ, tổng năng lượng nên rất nhỏ
        assert!(
            total_energy < 1.0,
            "Cảnh tĩnh nên có năng lượng Doppler thấp, nhận được {}",
            total_energy
        );
    }

    #[test]
    fn test_moving_body_nonzero_velocity() {
        // Điều chế biên độ hình sin mô phỏng chuyển động → năng lượng Doppler
        let n = 1000;
        let motion_freq = 5.0; // Hz
        let csi = Array2::from_shape_fn((n, 8), |(t, _)| {
            1.0 + 0.5 * (2.0 * PI * motion_freq * t as f64 / 100.0).sin()
        });

        let config = BvpConfig {
            window_size: 128,
            hop_size: 32,
            n_velocity_bins: 64,
            max_velocity: 2.0,
            ..Default::default()
        };

        let bvp = extract_bvp(&csi, 100.0, &config).unwrap();
        let total_energy: f64 = bvp.data.iter().sum();
        assert!(total_energy > 0.0, "Cơ thể chuyển động phải tạo năng lượng Doppler");
    }

    #[test]
    fn test_insufficient_samples() {
        let csi = Array2::from_elem((10, 5), 1.0);
        let config = BvpConfig {
            window_size: 128,
            ..Default::default()
        };
        assert!(matches!(
            extract_bvp(&csi, 100.0, &config),
            Err(BvpError::InsufficientSamples { .. })
        ));
    }

    #[test]
    fn test_time_resolution() {
        let csi = Array2::from_elem((500, 5), 1.0);
        let config = BvpConfig {
            window_size: 64,
            hop_size: 32,
            ..Default::default()
        };

        let bvp = extract_bvp(&csi, 100.0, &config).unwrap();
        assert!((bvp.time_resolution - 0.32).abs() < 1e-6); // 32/100
    }
}
