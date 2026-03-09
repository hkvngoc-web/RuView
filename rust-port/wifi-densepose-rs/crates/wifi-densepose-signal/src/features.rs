//! Module trích xuất đặc trưng
//!
//! Module này cung cấp khả năng trích xuất đặc trưng cho dữ liệu CSI,
//! bao gồm đặc trưng biên độ, pha, tương quan, Doppler, và mật độ phổ công suất.

use crate::csi_processor::CsiData;
use chrono::{DateTime, Utc};
use ndarray::{Array1, Array2};
use num_complex::Complex64;
use rustfft::FftPlanner;
use serde::{Deserialize, Serialize};

/// Đặc trưng dựa trên biên độ
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AmplitudeFeatures {
    /// Biên độ trung bình qua các anten cho mỗi sóng mang con
    pub mean: Array1<f64>,

    /// Phương sai biên độ qua các anten cho mỗi sóng mang con
    pub variance: Array1<f64>,

    /// Giá trị biên độ đỉnh
    pub peak: f64,

    /// Biên độ hiệu dụng (RMS)
    pub rms: f64,

    /// Dải động (max - min)
    pub dynamic_range: f64,
}

impl AmplitudeFeatures {
    /// Trích xuất đặc trưng biên độ từ dữ liệu CSI
    pub fn from_csi_data(csi_data: &CsiData) -> Self {
        let amplitude = &csi_data.amplitude;
        let (nrows, ncols) = amplitude.dim();

        // Tính trung bình qua các anten (trục 0)
        let mut mean = Array1::zeros(ncols);
        for j in 0..ncols {
            let mut sum = 0.0;
            for i in 0..nrows {
                sum += amplitude[[i, j]];
            }
            mean[j] = sum / nrows as f64;
        }

        // Tính phương sai qua các anten
        let mut variance = Array1::zeros(ncols);
        for j in 0..ncols {
            let mut var_sum = 0.0;
            for i in 0..nrows {
                var_sum += (amplitude[[i, j]] - mean[j]).powi(2);
            }
            variance[j] = var_sum / nrows as f64;
        }

        // Tính thống kê toàn cục
        let flat: Vec<f64> = amplitude.iter().copied().collect();
        let peak = flat.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let min_val = flat.iter().cloned().fold(f64::INFINITY, f64::min);
        let dynamic_range = peak - min_val;

        let rms = (flat.iter().map(|x| x * x).sum::<f64>() / flat.len() as f64).sqrt();

        Self {
            mean,
            variance,
            peak,
            rms,
            dynamic_range,
        }
    }
}

/// Đặc trưng dựa trên pha
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhaseFeatures {
    /// Hiệu pha giữa các sóng mang con liền kề (trung bình qua các anten)
    pub difference: Array1<f64>,

    /// Phương sai pha qua các sóng mang con
    pub variance: Array1<f64>,

    /// Gradient pha (tốc độ thay đổi)
    pub gradient: Array1<f64>,

    /// Thước đo tương hợp pha
    pub coherence: f64,
}

impl PhaseFeatures {
    /// Trích xuất đặc trưng pha từ dữ liệu CSI
    pub fn from_csi_data(csi_data: &CsiData) -> Self {
        let phase = &csi_data.phase;
        let (nrows, ncols) = phase.dim();

        // Tính hiệu pha giữa các sóng mang con liền kề
        let mut diff_matrix = Array2::zeros((nrows, ncols.saturating_sub(1)));
        for i in 0..nrows {
            for j in 0..ncols.saturating_sub(1) {
                diff_matrix[[i, j]] = phase[[i, j + 1]] - phase[[i, j]];
            }
        }

        // Hiệu pha trung bình qua các anten
        let mut difference = Array1::zeros(ncols.saturating_sub(1));
        for j in 0..ncols.saturating_sub(1) {
            let mut sum = 0.0;
            for i in 0..nrows {
                sum += diff_matrix[[i, j]];
            }
            difference[j] = sum / nrows as f64;
        }

        // Phương sai pha trên từng sóng mang con
        let mut variance = Array1::zeros(ncols);
        for j in 0..ncols {
            let mut col_sum = 0.0;
            for i in 0..nrows {
                col_sum += phase[[i, j]];
            }
            let mean = col_sum / nrows as f64;

            let mut var_sum = 0.0;
            for i in 0..nrows {
                var_sum += (phase[[i, j]] - mean).powi(2);
            }
            variance[j] = var_sum / nrows as f64;
        }

        // Tính gradient (hiệu bậc hai)
        let gradient = if ncols >= 3 {
            let mut grad = Array1::zeros(ncols.saturating_sub(2));
            for j in 0..ncols.saturating_sub(2) {
                grad[j] = difference[j + 1] - difference[j];
            }
            grad
        } else {
            Array1::zeros(1)
        };

        // Tương hợp pha (thước đo độ ổn định pha)
        let coherence = Self::calculate_coherence(phase);

        Self {
            difference,
            variance,
            gradient,
            coherence,
        }
    }

    /// Tính tương hợp pha
    fn calculate_coherence(phase: &Array2<f64>) -> f64 {
        let (nrows, ncols) = phase.dim();
        if nrows < 2 || ncols == 0 {
            return 0.0;
        }

        // Tính tương hợp bằng trung bình tương quan pha chéo anten
        let mut coherence_sum = 0.0;
        let mut count = 0;

        for i in 0..nrows {
            for k in (i + 1)..nrows {
                // Tính tương quan giữa các cặp anten
                let row_i: Vec<f64> = phase.row(i).to_vec();
                let row_k: Vec<f64> = phase.row(k).to_vec();

                let mean_i: f64 = row_i.iter().sum::<f64>() / ncols as f64;
                let mean_k: f64 = row_k.iter().sum::<f64>() / ncols as f64;

                let mut cov = 0.0;
                let mut var_i = 0.0;
                let mut var_k = 0.0;

                for j in 0..ncols {
                    let diff_i = row_i[j] - mean_i;
                    let diff_k = row_k[j] - mean_k;
                    cov += diff_i * diff_k;
                    var_i += diff_i * diff_i;
                    var_k += diff_k * diff_k;
                }

                let std_prod = (var_i * var_k).sqrt();
                if std_prod > 1e-10 {
                    coherence_sum += cov / std_prod;
                    count += 1;
                }
            }
        }

        if count > 0 {
            coherence_sum / count as f64
        } else {
            0.0
        }
    }
}

/// Đặc trưng tương quan giữa các anten
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorrelationFeatures {
    /// Ma trận tương quan giữa các anten
    pub matrix: Array2<f64>,

    /// Tương quan trung bình ngoài đường chéo
    pub mean_correlation: f64,

    /// Hệ số tương quan lớn nhất
    pub max_correlation: f64,

    /// Độ phân tán tương quan (độ lệch chuẩn các phần tử ngoài đường chéo)
    pub correlation_spread: f64,
}

impl CorrelationFeatures {
    /// Trích xuất đặc trưng tương quan từ dữ liệu CSI
    pub fn from_csi_data(csi_data: &CsiData) -> Self {
        let amplitude = &csi_data.amplitude;
        let matrix = Self::correlation_matrix(amplitude);

        let (n, _) = matrix.dim();
        let mut off_diagonal: Vec<f64> = Vec::new();

        for i in 0..n {
            for j in 0..n {
                if i != j {
                    off_diagonal.push(matrix[[i, j]]);
                }
            }
        }

        let mean_correlation = if !off_diagonal.is_empty() {
            off_diagonal.iter().sum::<f64>() / off_diagonal.len() as f64
        } else {
            0.0
        };

        let max_correlation = off_diagonal
            .iter()
            .cloned()
            .fold(f64::NEG_INFINITY, f64::max);

        let correlation_spread = if !off_diagonal.is_empty() {
            let var: f64 = off_diagonal
                .iter()
                .map(|x| (x - mean_correlation).powi(2))
                .sum::<f64>()
                / off_diagonal.len() as f64;
            var.sqrt()
        } else {
            0.0
        };

        Self {
            matrix,
            mean_correlation,
            max_correlation: if max_correlation.is_finite() { max_correlation } else { 0.0 },
            correlation_spread,
        }
    }

    /// Tính ma trận tương quan giữa các hàng (anten)
    fn correlation_matrix(data: &Array2<f64>) -> Array2<f64> {
        let (nrows, ncols) = data.dim();
        let mut corr = Array2::zeros((nrows, nrows));

        // Tính trung bình
        let means: Vec<f64> = (0..nrows)
            .map(|i| data.row(i).sum() / ncols as f64)
            .collect();

        // Tính độ lệch chuẩn
        let stds: Vec<f64> = (0..nrows)
            .map(|i| {
                let mean = means[i];
                let var: f64 = data.row(i).iter().map(|x| (x - mean).powi(2)).sum::<f64>() / ncols as f64;
                var.sqrt()
            })
            .collect();

        // Tính hệ số tương quan
        for i in 0..nrows {
            for j in 0..nrows {
                if i == j {
                    corr[[i, j]] = 1.0;
                } else {
                    let mut cov = 0.0;
                    for k in 0..ncols {
                        cov += (data[[i, k]] - means[i]) * (data[[j, k]] - means[j]);
                    }
                    cov /= ncols as f64;

                    let std_prod = stds[i] * stds[j];
                    corr[[i, j]] = if std_prod > 1e-10 { cov / std_prod } else { 0.0 };
                }
            }
        }

        corr
    }
}

/// Đặc trưng dịch chuyển Doppler
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DopplerFeatures {
    /// Dịch chuyển Doppler ước lượng cho mỗi sóng mang con
    pub shifts: Array1<f64>,

    /// Tần số Doppler đỉnh
    pub peak_frequency: f64,

    /// Biên độ dịch chuyển Doppler trung bình
    pub mean_magnitude: f64,

    /// Độ trải Doppler (độ lệch chuẩn)
    pub spread: f64,
}

impl DopplerFeatures {
    /// Trích xuất đặc trưng Doppler từ dữ liệu CSI theo thời gian
    pub fn from_csi_history(history: &[CsiData], sampling_rate: f64) -> Self {
        if history.is_empty() {
            return Self::empty();
        }

        let num_subcarriers = history[0].num_subcarriers;
        let num_samples = history.len();

        if num_samples < 2 {
            return Self::empty_with_size(num_subcarriers);
        }

        // Xếp chồng dữ liệu biên độ cho mỗi sóng mang con theo thời gian
        let mut shifts = Array1::zeros(num_subcarriers);
        let mut fft_planner = FftPlanner::new();
        let fft = fft_planner.plan_fft_forward(num_samples);

        for j in 0..num_subcarriers {
            // Trích xuất chuỗi thời gian cho sóng mang con này (dùng anten đầu tiên)
            let mut buffer: Vec<Complex64> = history
                .iter()
                .map(|csi| Complex64::new(csi.amplitude[[0, j]], 0.0))
                .collect();

            // Áp dụng FFT
            fft.process(&mut buffer);

            // Tìm tần số đỉnh (dịch chuyển Doppler)
            let mut max_mag = 0.0;
            let mut max_idx = 0;

            for (idx, val) in buffer.iter().enumerate() {
                let mag = val.norm();
                if mag > max_mag && idx != 0 {
                    // Bỏ qua thành phần DC
                    max_mag = mag;
                    max_idx = idx;
                }
            }

            // Chuyển đổi chỉ số bin sang tần số
            let freq_resolution = sampling_rate / num_samples as f64;
            let doppler_freq = if max_idx <= num_samples / 2 {
                max_idx as f64 * freq_resolution
            } else {
                (max_idx as i64 - num_samples as i64) as f64 * freq_resolution
            };

            shifts[j] = doppler_freq;
        }

        let magnitudes: Vec<f64> = shifts.iter().map(|x| x.abs()).collect();
        let peak_frequency = magnitudes.iter().cloned().fold(0.0, f64::max);
        let mean_magnitude = magnitudes.iter().sum::<f64>() / magnitudes.len() as f64;

        let spread = {
            let var: f64 = magnitudes
                .iter()
                .map(|x| (x - mean_magnitude).powi(2))
                .sum::<f64>()
                / magnitudes.len() as f64;
            var.sqrt()
        };

        Self {
            shifts,
            peak_frequency,
            mean_magnitude,
            spread,
        }
    }

    /// Tạo đặc trưng Doppler rỗng
    fn empty() -> Self {
        Self {
            shifts: Array1::zeros(1),
            peak_frequency: 0.0,
            mean_magnitude: 0.0,
            spread: 0.0,
        }
    }

    /// Tạo đặc trưng Doppler rỗng với kích thước chỉ định
    fn empty_with_size(size: usize) -> Self {
        Self {
            shifts: Array1::zeros(size),
            peak_frequency: 0.0,
            mean_magnitude: 0.0,
            spread: 0.0,
        }
    }
}

/// Đặc trưng mật độ phổ công suất
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PowerSpectralDensity {
    /// Giá trị PSD (các bin tần số)
    pub values: Array1<f64>,

    /// Các bin tần số tính bằng Hz
    pub frequencies: Array1<f64>,

    /// Tổng công suất
    pub total_power: f64,

    /// Công suất đỉnh
    pub peak_power: f64,

    /// Tần số đỉnh
    pub peak_frequency: f64,

    /// Trọng tâm phổ
    pub centroid: f64,

    /// Băng thông phổ
    pub bandwidth: f64,
}

impl PowerSpectralDensity {
    /// Tính PSD từ dữ liệu biên độ CSI
    pub fn from_csi_data(csi_data: &CsiData, fft_size: usize) -> Self {
        let amplitude = &csi_data.amplitude;
        let flat: Vec<f64> = amplitude.iter().copied().collect();

        // Đệm hoặc cắt đến kích thước FFT
        let mut input: Vec<Complex64> = flat
            .iter()
            .take(fft_size)
            .map(|&x| Complex64::new(x, 0.0))
            .collect();

        while input.len() < fft_size {
            input.push(Complex64::new(0.0, 0.0));
        }

        // Áp dụng FFT
        let mut fft_planner = FftPlanner::new();
        let fft = fft_planner.plan_fft_forward(fft_size);
        fft.process(&mut input);

        // Tính phổ công suất
        let mut psd = Array1::zeros(fft_size);
        for (i, val) in input.iter().enumerate() {
            psd[i] = val.norm_sqr() / fft_size as f64;
        }

        // Tính các bin tần số
        let freq_resolution = csi_data.bandwidth / fft_size as f64;
        let frequencies: Array1<f64> = (0..fft_size)
            .map(|i| {
                if i <= fft_size / 2 {
                    i as f64 * freq_resolution
                } else {
                    (i as i64 - fft_size as i64) as f64 * freq_resolution
                }
            })
            .collect();

        // Tính thống kê (dùng nửa đầu cho tần số dương)
        let half = fft_size / 2;
        let positive_psd: Vec<f64> = psd.iter().take(half).copied().collect();
        let positive_freq: Vec<f64> = frequencies.iter().take(half).copied().collect();

        let total_power: f64 = positive_psd.iter().sum();
        let peak_power = positive_psd.iter().cloned().fold(0.0, f64::max);

        let peak_idx = positive_psd
            .iter()
            .enumerate()
            .max_by(|(_, a): &(usize, &f64), (_, b): &(usize, &f64)| {
                a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(i, _)| i)
            .unwrap_or(0);
        let peak_frequency = positive_freq[peak_idx];

        // Trọng tâm phổ
        let centroid = if total_power > 1e-10 {
            let weighted_sum: f64 = positive_psd
                .iter()
                .zip(positive_freq.iter())
                .map(|(p, f)| p * f)
                .sum();
            weighted_sum / total_power
        } else {
            0.0
        };

        // Băng thông phổ (độ lệch chuẩn quanh trọng tâm)
        let bandwidth = if total_power > 1e-10 {
            let weighted_var: f64 = positive_psd
                .iter()
                .zip(positive_freq.iter())
                .map(|(p, f)| p * (f - centroid).powi(2))
                .sum();
            (weighted_var / total_power).sqrt()
        } else {
            0.0
        };

        Self {
            values: psd,
            frequencies,
            total_power,
            peak_power,
            peak_frequency,
            centroid,
            bandwidth,
        }
    }
}

/// Bộ sưu tập đặc trưng CSI hoàn chỉnh
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CsiFeatures {
    /// Đặc trưng dựa trên biên độ
    pub amplitude: AmplitudeFeatures,

    /// Đặc trưng dựa trên pha
    pub phase: PhaseFeatures,

    /// Đặc trưng tương quan
    pub correlation: CorrelationFeatures,

    /// Đặc trưng Doppler (tùy chọn, cần lịch sử)
    pub doppler: Option<DopplerFeatures>,

    /// Mật độ phổ công suất
    pub psd: PowerSpectralDensity,

    /// Thời điểm trích xuất đặc trưng
    pub timestamp: DateTime<Utc>,

    /// Siêu dữ liệu CSI nguồn
    pub metadata: FeatureMetadata,
}

/// Siêu dữ liệu cho đặc trưng đã trích xuất
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FeatureMetadata {
    /// Số anten trong dữ liệu nguồn
    pub num_antennas: usize,

    /// Số sóng mang con trong dữ liệu nguồn
    pub num_subcarriers: usize,

    /// Kích thước FFT dùng cho PSD
    pub fft_size: usize,

    /// Tần số lấy mẫu dùng cho Doppler
    pub sampling_rate: Option<f64>,

    /// Số mẫu dùng cho Doppler
    pub doppler_samples: Option<usize>,
}

/// Cấu hình trích xuất đặc trưng
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeatureExtractorConfig {
    /// Kích thước FFT cho tính PSD
    pub fft_size: usize,

    /// Tần số lấy mẫu cho tính Doppler
    pub sampling_rate: f64,

    /// Độ dài lịch sử tối thiểu cho đặc trưng Doppler
    pub min_doppler_history: usize,

    /// Bật trích xuất đặc trưng Doppler
    pub enable_doppler: bool,
}

impl Default for FeatureExtractorConfig {
    fn default() -> Self {
        Self {
            fft_size: 128,
            sampling_rate: 1000.0,
            min_doppler_history: 10,
            enable_doppler: true,
        }
    }
}

/// Bộ trích xuất đặc trưng cho dữ liệu CSI
#[derive(Debug)]
pub struct FeatureExtractor {
    config: FeatureExtractorConfig,
}

impl FeatureExtractor {
    /// Tạo bộ trích xuất đặc trưng mới
    pub fn new(config: FeatureExtractorConfig) -> Self {
        Self { config }
    }

    /// Tạo với cấu hình mặc định
    pub fn default_config() -> Self {
        Self::new(FeatureExtractorConfig::default())
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &FeatureExtractorConfig {
        &self.config
    }

    /// Trích xuất đặc trưng từ một mẫu CSI đơn
    pub fn extract(&self, csi_data: &CsiData) -> CsiFeatures {
        let amplitude = AmplitudeFeatures::from_csi_data(csi_data);
        let phase = PhaseFeatures::from_csi_data(csi_data);
        let correlation = CorrelationFeatures::from_csi_data(csi_data);
        let psd = PowerSpectralDensity::from_csi_data(csi_data, self.config.fft_size);

        let metadata = FeatureMetadata {
            num_antennas: csi_data.num_antennas,
            num_subcarriers: csi_data.num_subcarriers,
            fft_size: self.config.fft_size,
            sampling_rate: None,
            doppler_samples: None,
        };

        CsiFeatures {
            amplitude,
            phase,
            correlation,
            doppler: None,
            psd,
            timestamp: Utc::now(),
            metadata,
        }
    }

    /// Trích xuất đặc trưng bao gồm Doppler từ lịch sử CSI
    pub fn extract_with_history(&self, csi_data: &CsiData, history: &[CsiData]) -> CsiFeatures {
        let mut features = self.extract(csi_data);

        if self.config.enable_doppler && history.len() >= self.config.min_doppler_history {
            let doppler = DopplerFeatures::from_csi_history(history, self.config.sampling_rate);
            features.doppler = Some(doppler);
            features.metadata.sampling_rate = Some(self.config.sampling_rate);
            features.metadata.doppler_samples = Some(history.len());
        }

        features
    }

    /// Chỉ trích xuất đặc trưng biên độ
    pub fn extract_amplitude(&self, csi_data: &CsiData) -> AmplitudeFeatures {
        AmplitudeFeatures::from_csi_data(csi_data)
    }

    /// Chỉ trích xuất đặc trưng pha
    pub fn extract_phase(&self, csi_data: &CsiData) -> PhaseFeatures {
        PhaseFeatures::from_csi_data(csi_data)
    }

    /// Chỉ trích xuất đặc trưng tương quan
    pub fn extract_correlation(&self, csi_data: &CsiData) -> CorrelationFeatures {
        CorrelationFeatures::from_csi_data(csi_data)
    }

    /// Chỉ trích xuất đặc trưng PSD
    pub fn extract_psd(&self, csi_data: &CsiData) -> PowerSpectralDensity {
        PowerSpectralDensity::from_csi_data(csi_data, self.config.fft_size)
    }

    /// Trích xuất đặc trưng Doppler từ lịch sử
    pub fn extract_doppler(&self, history: &[CsiData]) -> Option<DopplerFeatures> {
        if history.len() >= self.config.min_doppler_history {
            Some(DopplerFeatures::from_csi_history(
                history,
                self.config.sampling_rate,
            ))
        } else {
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::Array2;

    fn create_test_csi_data() -> CsiData {
        let amplitude = Array2::from_shape_fn((4, 64), |(i, j)| {
            1.0 + 0.5 * ((i + j) as f64 * 0.1).sin()
        });
        let phase = Array2::from_shape_fn((4, 64), |(i, j)| {
            0.5 * ((i + j) as f64 * 0.15).sin()
        });

        CsiData::builder()
            .amplitude(amplitude)
            .phase(phase)
            .frequency(5.0e9)
            .bandwidth(20.0e6)
            .snr(25.0)
            .build()
            .unwrap()
    }

    fn create_test_history(n: usize) -> Vec<CsiData> {
        (0..n)
            .map(|t| {
                let amplitude = Array2::from_shape_fn((4, 64), |(i, j)| {
                    1.0 + 0.3 * ((i + j + t) as f64 * 0.1).sin()
                });
                let phase = Array2::from_shape_fn((4, 64), |(i, j)| {
                    0.4 * ((i + j + t) as f64 * 0.12).sin()
                });

                CsiData::builder()
                    .amplitude(amplitude)
                    .phase(phase)
                    .frequency(5.0e9)
                    .bandwidth(20.0e6)
                    .build()
                    .unwrap()
            })
            .collect()
    }

    #[test]
    fn test_amplitude_features() {
        let csi_data = create_test_csi_data();
        let features = AmplitudeFeatures::from_csi_data(&csi_data);

        assert_eq!(features.mean.len(), 64);
        assert_eq!(features.variance.len(), 64);
        assert!(features.peak > 0.0);
        assert!(features.rms > 0.0);
        assert!(features.dynamic_range >= 0.0);
    }

    #[test]
    fn test_phase_features() {
        let csi_data = create_test_csi_data();
        let features = PhaseFeatures::from_csi_data(&csi_data);

        assert_eq!(features.difference.len(), 63);
        assert_eq!(features.variance.len(), 64);
        assert!(features.coherence.abs() <= 1.0);
    }

    #[test]
    fn test_correlation_features() {
        let csi_data = create_test_csi_data();
        let features = CorrelationFeatures::from_csi_data(&csi_data);

        assert_eq!(features.matrix.dim(), (4, 4));

        // Đường chéo phải là 1
        for i in 0..4 {
            assert!((features.matrix[[i, i]] - 1.0).abs() < 1e-10);
        }

        // Ma trận phải đối xứng
        for i in 0..4 {
            for j in 0..4 {
                assert!((features.matrix[[i, j]] - features.matrix[[j, i]]).abs() < 1e-10);
            }
        }
    }

    #[test]
    fn test_psd_features() {
        let csi_data = create_test_csi_data();
        let psd = PowerSpectralDensity::from_csi_data(&csi_data, 128);

        assert_eq!(psd.values.len(), 128);
        assert_eq!(psd.frequencies.len(), 128);
        assert!(psd.total_power >= 0.0);
        assert!(psd.peak_power >= 0.0);
    }

    #[test]
    fn test_doppler_features() {
        let history = create_test_history(20);
        let features = DopplerFeatures::from_csi_history(&history, 1000.0);

        assert_eq!(features.shifts.len(), 64);
    }

    #[test]
    fn test_feature_extractor() {
        let config = FeatureExtractorConfig::default();
        let extractor = FeatureExtractor::new(config);
        let csi_data = create_test_csi_data();

        let features = extractor.extract(&csi_data);

        assert_eq!(features.amplitude.mean.len(), 64);
        assert_eq!(features.phase.difference.len(), 63);
        assert_eq!(features.correlation.matrix.dim(), (4, 4));
        assert!(features.doppler.is_none());
    }

    #[test]
    fn test_feature_extractor_with_history() {
        let config = FeatureExtractorConfig {
            min_doppler_history: 10,
            enable_doppler: true,
            ..Default::default()
        };
        let extractor = FeatureExtractor::new(config);
        let csi_data = create_test_csi_data();
        let history = create_test_history(15);

        let features = extractor.extract_with_history(&csi_data, &history);

        assert!(features.doppler.is_some());
        assert_eq!(features.metadata.doppler_samples, Some(15));
    }

    #[test]
    fn test_individual_extraction() {
        let extractor = FeatureExtractor::default_config();
        let csi_data = create_test_csi_data();

        let amp = extractor.extract_amplitude(&csi_data);
        assert!(!amp.mean.is_empty());

        let phase = extractor.extract_phase(&csi_data);
        assert!(!phase.difference.is_empty());

        let corr = extractor.extract_correlation(&csi_data);
        assert_eq!(corr.matrix.dim(), (4, 4));

        let psd = extractor.extract_psd(&csi_data);
        assert!(!psd.values.is_empty());
    }

    #[test]
    fn test_empty_doppler_history() {
        let extractor = FeatureExtractor::default_config();
        let history: Vec<CsiData> = vec![];

        let doppler = extractor.extract_doppler(&history);
        assert!(doppler.is_none());
    }

    #[test]
    fn test_insufficient_doppler_history() {
        let config = FeatureExtractorConfig {
            min_doppler_history: 10,
            ..Default::default()
        };
        let extractor = FeatureExtractor::new(config);
        let history = create_test_history(5);

        let doppler = extractor.extract_doppler(&history);
        assert!(doppler.is_none());
    }
}
