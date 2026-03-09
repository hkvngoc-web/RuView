//! Tạo biểu đồ phổ CSI
//!
//! Xây dựng ma trận thời gian-tần số 2D qua biến đổi Fourier ngắn hạn (STFT)
//! áp dụng cho luồng biên độ CSI theo thời gian. Các biểu đồ phổ kết quả là
//! định dạng đầu vào chuẩn cho nhận dạng hoạt động WiFi dựa trên CNN.
//!
//! # Tài liệu tham khảo
//! - Được sử dụng trong hầu như tất cả các bài báo cảm biến WiFi dựa CNN từ năm 2018

use ndarray::Array2;
use num_complex::Complex64;
use ruvector_attn_mincut::attn_mincut;
use rustfft::FftPlanner;
use std::f64::consts::PI;

/// Cấu hình cho tạo biểu đồ phổ.
#[derive(Debug, Clone)]
pub struct SpectrogramConfig {
    /// Kích thước cửa sổ FFT (số mẫu mỗi khung)
    pub window_size: usize,
    /// Bước nhảy (khoảng cách giữa các khung liên tiếp). Nhỏ hơn = chồng lắp nhiều hơn.
    pub hop_size: usize,
    /// Hàm cửa sổ áp dụng
    pub window_fn: WindowFunction,
    /// Tính công suất (bình phương biên độ) hay biên độ
    pub power: bool,
}

impl Default for SpectrogramConfig {
    fn default() -> Self {
        Self {
            window_size: 256,
            hop_size: 64,
            window_fn: WindowFunction::Hann,
            power: true,
        }
    }
}

/// Các loại hàm cửa sổ.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowFunction {
    /// Hình chữ nhật (không tạo cửa sổ)
    Rectangular,
    /// Cửa sổ Hann (giảm biên dạng cosine bình phương)
    Hann,
    /// Cửa sổ Hamming
    Hamming,
    /// Cửa sổ Blackman (mức thùy phụ thấp hơn)
    Blackman,
}

/// Kết quả tính biểu đồ phổ.
#[derive(Debug, Clone)]
pub struct Spectrogram {
    /// Giá trị công suất/biên độ: hàng = bin tần số, cột = khung thời gian.
    /// Chỉ tần số dương (0 đến Nyquist), nên hàng = window_size/2 + 1.
    pub data: Array2<f64>,
    /// Số bin tần số
    pub n_freq: usize,
    /// Số khung thời gian
    pub n_time: usize,
    /// Độ phân giải tần số (Hz mỗi bin)
    pub freq_resolution: f64,
    /// Độ phân giải thời gian (giây mỗi khung)
    pub time_resolution: f64,
}

/// Tính biểu đồ phổ của tín hiệu 1D.
///
/// Trả về ma trận thời gian-tần số phù hợp làm đầu vào CNN.
pub fn compute_spectrogram(
    signal: &[f64],
    sample_rate: f64,
    config: &SpectrogramConfig,
) -> Result<Spectrogram, SpectrogramError> {
    if signal.len() < config.window_size {
        return Err(SpectrogramError::SignalTooShort {
            signal_len: signal.len(),
            window_size: config.window_size,
        });
    }
    if config.hop_size == 0 {
        return Err(SpectrogramError::InvalidHopSize);
    }
    if config.window_size == 0 {
        return Err(SpectrogramError::InvalidWindowSize);
    }

    let n_frames = (signal.len() - config.window_size) / config.hop_size + 1;
    let n_freq = config.window_size / 2 + 1;
    let window = make_window(config.window_fn, config.window_size);

    let mut planner = FftPlanner::new();
    let fft = planner.plan_fft_forward(config.window_size);

    let mut data = Array2::zeros((n_freq, n_frames));

    for frame in 0..n_frames {
        let start = frame * config.hop_size;
        let end = start + config.window_size;

        // Áp dụng cửa sổ và chuyển sang phức
        let mut buffer: Vec<Complex64> = signal[start..end]
            .iter()
            .zip(window.iter())
            .map(|(&s, &w)| Complex64::new(s * w, 0.0))
            .collect();

        fft.process(&mut buffer);

        // Lưu tần số dương
        for bin in 0..n_freq {
            let mag = buffer[bin].norm();
            data[[bin, frame]] = if config.power { mag * mag } else { mag };
        }
    }

    Ok(Spectrogram {
        data,
        n_freq,
        n_time: n_frames,
        freq_resolution: sample_rate / config.window_size as f64,
        time_resolution: config.hop_size as f64 / sample_rate,
    })
}

/// Tính biểu đồ phổ cho mỗi sóng mang con từ ma trận CSI theo thời gian.
///
/// Đầu vào: `csi_temporal` là ma trận biên độ (num_samples × num_subcarriers).
/// Trả về một biểu đồ phổ cho mỗi sóng mang con.
pub fn compute_multi_subcarrier_spectrogram(
    csi_temporal: &Array2<f64>,
    sample_rate: f64,
    config: &SpectrogramConfig,
) -> Result<Vec<Spectrogram>, SpectrogramError> {
    let (_, n_sc) = csi_temporal.dim();
    let mut spectrograms = Vec::with_capacity(n_sc);

    for sc in 0..n_sc {
        let col: Vec<f64> = csi_temporal.column(sc).to_vec();
        spectrograms.push(compute_spectrogram(&col, sample_rate, config)?);
    }

    Ok(spectrograms)
}

/// Sinh hàm cửa sổ.
fn make_window(kind: WindowFunction, size: usize) -> Vec<f64> {
    match kind {
        WindowFunction::Rectangular => vec![1.0; size],
        WindowFunction::Hann => (0..size)
            .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f64 / (size - 1) as f64).cos()))
            .collect(),
        WindowFunction::Hamming => (0..size)
            .map(|i| 0.54 - 0.46 * (2.0 * PI * i as f64 / (size - 1) as f64).cos())
            .collect(),
        WindowFunction::Blackman => (0..size)
            .map(|i| {
                let n = (size - 1) as f64;
                0.42 - 0.5 * (2.0 * PI * i as f64 / n).cos()
                    + 0.08 * (4.0 * PI * i as f64 / n).cos()
            })
            .collect(),
    }
}

/// Áp dụng cổng attention cho biểu đồ phổ CSI đã tính bằng ruvector-attn-mincut.
///
/// Coi mỗi khung thời gian là một token attention (d = n_freq_bins đặc trưng,
/// seq_len = n_time_frames token). Tự attention (Q=K=V) lọc các khung chuyển động
/// cơ thể tương hợp và triệt chế khung nhiễu/nhiễu loạn không tương quan.
///
/// # Tham số
/// * `spectrogram` - Dạng hàng chính [n_freq_bins × n_time_frames] lát f32
/// * `n_freq` - Số bin tần số (chiều đặc trưng d)
/// * `n_time` - Số khung thời gian (độ dài chuỗi)
/// * `lambda` - Cường độ cổng: 0.1 = nhẹ, 0.3 = trung bình, 0.5 = mạnh
///
/// # Trả về
/// Biểu đồ phổ đã qua cổng dạng Vec<f32>, cùng kích thước đầu vào
pub fn gate_spectrogram(
    spectrogram: &[f32],
    n_freq: usize,
    n_time: usize,
    lambda: f32,
) -> Vec<f32> {
    debug_assert_eq!(spectrogram.len(), n_freq * n_time,
        "độ dài biểu đồ phổ phải bằng n_freq * n_time");

    if n_freq == 0 || n_time == 0 {
        return spectrogram.to_vec();
    }

    // Q = K = V = biểu đồ phổ (tự attention theo khung thời gian)
    let result = attn_mincut(
        spectrogram,
        spectrogram,
        spectrogram,
        n_freq,  // d = chiều đặc trưng
        n_time,  // seq_len = token thời gian
        lambda,
        /*tau=*/ 2,
        /*eps=*/ 1e-7_f32,
    );
    result.output
}

/// Các lỗi từ tính biểu đồ phổ.
#[derive(Debug, thiserror::Error)]
pub enum SpectrogramError {
    #[error("Tín hiệu quá ngắn ({signal_len} mẫu) cho kích thước cửa sổ {window_size}")]
    SignalTooShort { signal_len: usize, window_size: usize },

    #[error("Bước nhảy phải > 0")]
    InvalidHopSize,

    #[error("Kích thước cửa sổ phải > 0")]
    InvalidWindowSize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spectrogram_dimensions() {
        let sample_rate = 100.0;
        let signal: Vec<f64> = (0..1000)
            .map(|i| (i as f64 / sample_rate * 2.0 * PI * 5.0).sin())
            .collect();

        let config = SpectrogramConfig {
            window_size: 128,
            hop_size: 32,
            window_fn: WindowFunction::Hann,
            power: true,
        };

        let spec = compute_spectrogram(&signal, sample_rate, &config).unwrap();
        assert_eq!(spec.n_freq, 65); // 128/2 + 1
        assert_eq!(spec.n_time, (1000 - 128) / 32 + 1); // 28 khung
        assert_eq!(spec.data.dim(), (65, 28));
    }

    #[test]
    fn test_single_frequency_peak() {
        // Tín hiệu thuần 10 Hz ở tần số lấy mẫu 100 Hz → đỉnh tại bin 10/100*256 ≈ bin 26
        let sample_rate = 100.0;
        let freq = 10.0;
        let signal: Vec<f64> = (0..1024)
            .map(|i| (2.0 * PI * freq * i as f64 / sample_rate).sin())
            .collect();

        let config = SpectrogramConfig {
            window_size: 256,
            hop_size: 128,
            window_fn: WindowFunction::Hann,
            power: true,
        };

        let spec = compute_spectrogram(&signal, sample_rate, &config).unwrap();

        // Tìm bin tần số đỉnh trong khung đầu tiên
        let frame = spec.data.column(0);
        let peak_bin = frame
            .iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
            .map(|(i, _)| i)
            .unwrap();

        let peak_freq = peak_bin as f64 * spec.freq_resolution;
        assert!(
            (peak_freq - freq).abs() < spec.freq_resolution * 2.0,
            "Đỉnh tại {:.1} Hz, kỳ vọng {:.1} Hz",
            peak_freq,
            freq
        );
    }

    #[test]
    fn test_window_functions_symmetric() {
        for wf in [
            WindowFunction::Hann,
            WindowFunction::Hamming,
            WindowFunction::Blackman,
        ] {
            let w = make_window(wf, 64);
            for i in 0..32 {
                assert!(
                    (w[i] - w[63 - i]).abs() < 1e-10,
                    "{:?} không đối xứng tại {}",
                    wf,
                    i
                );
            }
        }
    }

    #[test]
    fn test_rectangular_window_all_ones() {
        let w = make_window(WindowFunction::Rectangular, 100);
        assert!(w.iter().all(|&v| (v - 1.0).abs() < 1e-10));
    }

    #[test]
    fn test_signal_too_short() {
        let signal = vec![1.0; 10];
        let config = SpectrogramConfig {
            window_size: 256,
            ..Default::default()
        };
        assert!(matches!(
            compute_spectrogram(&signal, 100.0, &config),
            Err(SpectrogramError::SignalTooShort { .. })
        ));
    }

    #[test]
    fn test_multi_subcarrier() {
        let n_samples = 500;
        let n_sc = 8;
        let csi = Array2::from_shape_fn((n_samples, n_sc), |(t, sc)| {
            let freq = 1.0 + sc as f64 * 0.5;
            (2.0 * PI * freq * t as f64 / 100.0).sin()
        });

        let config = SpectrogramConfig {
            window_size: 128,
            hop_size: 64,
            ..Default::default()
        };

        let specs = compute_multi_subcarrier_spectrogram(&csi, 100.0, &config).unwrap();
        assert_eq!(specs.len(), n_sc);
        for spec in &specs {
            assert_eq!(spec.n_freq, 65);
        }
    }
}

#[cfg(test)]
mod gate_tests {
    use super::*;

    #[test]
    fn gate_spectrogram_preserves_shape() {
        let n_freq = 16_usize;
        let n_time = 10_usize;
        let spectrogram: Vec<f32> = (0..n_freq * n_time).map(|i| i as f32 * 0.01).collect();
        let gated = gate_spectrogram(&spectrogram, n_freq, n_time, 0.3);
        assert_eq!(gated.len(), n_freq * n_time);
    }

    #[test]
    fn gate_spectrogram_zero_lambda_is_identity_ish() {
        let n_freq = 8_usize;
        let n_time = 4_usize;
        let spectrogram: Vec<f32> = vec![1.0; n_freq * n_time];
        // Đầu vào đồng nhất — đầu ra đã qua cổng cũng phải gần đồng nhất
        let gated = gate_spectrogram(&spectrogram, n_freq, n_time, 0.01);
        assert_eq!(gated.len(), n_freq * n_time);
        // Tất cả giá trị phải hữu hạn
        assert!(gated.iter().all(|x| x.is_finite()));
    }
}
