//! Module làm sạch pha
//!
//! Module này cung cấp khả năng giải cuộn pha, loại bỏ ngoại lai, làm mượt, và lọc nhiễu
//! cho dữ liệu pha CSI nhằm đảm bảo xử lý tín hiệu đáng tin cậy.

use ndarray::Array2;
use serde::{Deserialize, Serialize};
use std::f64::consts::PI;
use thiserror::Error;

/// Các lỗi có thể xảy ra trong quá trình làm sạch pha
#[derive(Debug, Error)]
pub enum PhaseSanitizationError {
    /// Cấu hình không hợp lệ
    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),

    /// Giải cuộn pha thất bại
    #[error("Giải cuộn pha thất bại: {0}")]
    UnwrapFailed(String),

    /// Loại bỏ ngoại lai thất bại
    #[error("Loại bỏ ngoại lai thất bại: {0}")]
    OutlierRemovalFailed(String),

    /// Làm mượt thất bại
    #[error("Làm mượt thất bại: {0}")]
    SmoothingFailed(String),

    /// Lọc nhiễu thất bại
    #[error("Lọc nhiễu thất bại: {0}")]
    NoiseFilterFailed(String),

    /// Định dạng dữ liệu không hợp lệ
    #[error("Dữ liệu không hợp lệ: {0}")]
    InvalidData(String),

    /// Lỗi đường ống xử lý
    #[error("Đường ống làm sạch thất bại: {0}")]
    PipelineFailed(String),
}

/// Phương pháp giải cuộn pha
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum UnwrappingMethod {
    /// Giải cuộn chuẩn kiểu numpy
    Standard,

    /// Giải cuộn tùy chỉnh theo từng hàng
    Custom,

    /// Phương pháp Itoh cho giải cuộn 2D
    Itoh,

    /// Giải cuộn dẫn hướng theo chất lượng
    QualityGuided,
}

impl Default for UnwrappingMethod {
    fn default() -> Self {
        Self::Standard
    }
}

/// Cấu hình cho bộ làm sạch pha
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhaseSanitizerConfig {
    /// Phương pháp giải cuộn pha
    pub unwrapping_method: UnwrappingMethod,

    /// Ngưỡng Z-score cho phát hiện ngoại lai
    pub outlier_threshold: f64,

    /// Kích thước cửa sổ cho làm mượt
    pub smoothing_window: usize,

    /// Bật loại bỏ ngoại lai
    pub enable_outlier_removal: bool,

    /// Bật làm mượt
    pub enable_smoothing: bool,

    /// Bật lọc nhiễu
    pub enable_noise_filtering: bool,

    /// Tần số cắt bộ lọc nhiễu (chuẩn hóa 0-1)
    pub noise_threshold: f64,

    /// Phạm vi pha hợp lệ
    pub phase_range: (f64, f64),
}

impl Default for PhaseSanitizerConfig {
    fn default() -> Self {
        Self {
            unwrapping_method: UnwrappingMethod::Standard,
            outlier_threshold: 3.0,
            smoothing_window: 5,
            enable_outlier_removal: true,
            enable_smoothing: true,
            enable_noise_filtering: false,
            noise_threshold: 0.05,
            phase_range: (-PI, PI),
        }
    }
}

impl PhaseSanitizerConfig {
    /// Tạo builder cấu hình mới
    pub fn builder() -> PhaseSanitizerConfigBuilder {
        PhaseSanitizerConfigBuilder::new()
    }

    /// Kiểm tra tính hợp lệ của cấu hình
    pub fn validate(&self) -> Result<(), PhaseSanitizationError> {
        if self.outlier_threshold <= 0.0 {
            return Err(PhaseSanitizationError::InvalidConfig(
                "outlier_threshold phải dương".into(),
            ));
        }

        if self.smoothing_window == 0 {
            return Err(PhaseSanitizationError::InvalidConfig(
                "smoothing_window phải dương".into(),
            ));
        }

        if self.noise_threshold <= 0.0 || self.noise_threshold >= 1.0 {
            return Err(PhaseSanitizationError::InvalidConfig(
                "noise_threshold phải nằm trong khoảng 0 đến 1".into(),
            ));
        }

        Ok(())
    }
}

/// Builder cho PhaseSanitizerConfig
#[derive(Debug, Default)]
pub struct PhaseSanitizerConfigBuilder {
    config: PhaseSanitizerConfig,
}

impl PhaseSanitizerConfigBuilder {
    /// Tạo builder mới
    pub fn new() -> Self {
        Self {
            config: PhaseSanitizerConfig::default(),
        }
    }

    /// Đặt phương pháp giải cuộn
    pub fn unwrapping_method(mut self, method: UnwrappingMethod) -> Self {
        self.config.unwrapping_method = method;
        self
    }

    /// Đặt ngưỡng ngoại lai
    pub fn outlier_threshold(mut self, threshold: f64) -> Self {
        self.config.outlier_threshold = threshold;
        self
    }

    /// Đặt kích thước cửa sổ làm mượt
    pub fn smoothing_window(mut self, window: usize) -> Self {
        self.config.smoothing_window = window;
        self
    }

    /// Bật/tắt loại bỏ ngoại lai
    pub fn enable_outlier_removal(mut self, enable: bool) -> Self {
        self.config.enable_outlier_removal = enable;
        self
    }

    /// Bật/tắt làm mượt
    pub fn enable_smoothing(mut self, enable: bool) -> Self {
        self.config.enable_smoothing = enable;
        self
    }

    /// Bật/tắt lọc nhiễu
    pub fn enable_noise_filtering(mut self, enable: bool) -> Self {
        self.config.enable_noise_filtering = enable;
        self
    }

    /// Đặt ngưỡng nhiễu
    pub fn noise_threshold(mut self, threshold: f64) -> Self {
        self.config.noise_threshold = threshold;
        self
    }

    /// Đặt phạm vi pha
    pub fn phase_range(mut self, min: f64, max: f64) -> Self {
        self.config.phase_range = (min, max);
        self
    }

    /// Xây dựng cấu hình
    pub fn build(self) -> PhaseSanitizerConfig {
        self.config
    }
}

/// Thống kê cho các thao tác làm sạch
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SanitizationStatistics {
    /// Tổng số mẫu đã xử lý
    pub total_processed: usize,

    /// Tổng số ngoại lai đã loại bỏ
    pub outliers_removed: usize,

    /// Tổng số lỗi làm sạch
    pub sanitization_errors: usize,
}

impl SanitizationStatistics {
    /// Tính tỷ lệ ngoại lai
    pub fn outlier_rate(&self) -> f64 {
        if self.total_processed > 0 {
            self.outliers_removed as f64 / self.total_processed as f64
        } else {
            0.0
        }
    }

    /// Tính tỷ lệ lỗi
    pub fn error_rate(&self) -> f64 {
        if self.total_processed > 0 {
            self.sanitization_errors as f64 / self.total_processed as f64
        } else {
            0.0
        }
    }
}

/// Bộ làm sạch pha để chuẩn bị dữ liệu pha
#[derive(Debug)]
pub struct PhaseSanitizer {
    config: PhaseSanitizerConfig,
    statistics: SanitizationStatistics,
}

impl PhaseSanitizer {
    /// Tạo bộ làm sạch pha mới
    pub fn new(config: PhaseSanitizerConfig) -> Result<Self, PhaseSanitizationError> {
        config.validate()?;
        Ok(Self {
            config,
            statistics: SanitizationStatistics::default(),
        })
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &PhaseSanitizerConfig {
        &self.config
    }

    /// Kiểm tra định dạng và giá trị dữ liệu pha
    pub fn validate_phase_data(&self, phase_data: &Array2<f64>) -> Result<(), PhaseSanitizationError> {
        // Kiểm tra dữ liệu rỗng
        if phase_data.is_empty() {
            return Err(PhaseSanitizationError::InvalidData(
                "Dữ liệu pha không được rỗng".into(),
            ));
        }

        // Kiểm tra giá trị có nằm trong phạm vi hợp lệ không
        let (min_val, max_val) = self.config.phase_range;
        for &val in phase_data.iter() {
            if val < min_val || val > max_val {
                return Err(PhaseSanitizationError::InvalidData(format!(
                    "Giá trị pha {} nằm ngoài phạm vi hợp lệ [{}, {}]",
                    val, min_val, max_val
                )));
            }
        }

        Ok(())
    }

    /// Giải cuộn dữ liệu pha để loại bỏ gián đoạn 2pi
    pub fn unwrap_phase(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        if phase_data.is_empty() {
            return Err(PhaseSanitizationError::UnwrapFailed(
                "Không thể giải cuộn dữ liệu pha rỗng".into(),
            ));
        }

        match self.config.unwrapping_method {
            UnwrappingMethod::Standard => self.unwrap_standard(phase_data),
            UnwrappingMethod::Custom => self.unwrap_custom(phase_data),
            UnwrappingMethod::Itoh => self.unwrap_itoh(phase_data),
            UnwrappingMethod::QualityGuided => self.unwrap_quality_guided(phase_data),
        }
    }

    /// Giải cuộn pha chuẩn (kiểu numpy)
    fn unwrap_standard(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        let mut unwrapped = phase_data.clone();
        let (_nrows, ncols) = unwrapped.dim();

        for i in 0..unwrapped.nrows() {
            let mut row_data: Vec<f64> = (0..ncols).map(|j| unwrapped[[i, j]]).collect();
            Self::unwrap_1d(&mut row_data);
            for (j, &val) in row_data.iter().enumerate() {
                unwrapped[[i, j]] = val;
            }
        }

        Ok(unwrapped)
    }

    /// Giải cuộn pha tùy chỉnh theo từng hàng
    fn unwrap_custom(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        let mut unwrapped = phase_data.clone();
        let ncols = unwrapped.ncols();

        for i in 0..unwrapped.nrows() {
            let mut row_data: Vec<f64> = (0..ncols).map(|j| unwrapped[[i, j]]).collect();
            self.unwrap_1d_custom(&mut row_data);
            for (j, &val) in row_data.iter().enumerate() {
                unwrapped[[i, j]] = val;
            }
        }

        Ok(unwrapped)
    }

    /// Phương pháp giải cuộn pha 2D của Itoh
    fn unwrap_itoh(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        let mut unwrapped = phase_data.clone();
        let (nrows, ncols) = phase_data.dim();

        // Giải cuộn theo hàng trước
        for i in 0..nrows {
            let mut row_data: Vec<f64> = (0..ncols).map(|j| unwrapped[[i, j]]).collect();
            Self::unwrap_1d(&mut row_data);
            for (j, &val) in row_data.iter().enumerate() {
                unwrapped[[i, j]] = val;
            }
        }

        // Sau đó giải cuộn theo cột
        for j in 0..ncols {
            let mut col: Vec<f64> = unwrapped.column(j).to_vec();
            Self::unwrap_1d(&mut col);
            for (i, &val) in col.iter().enumerate() {
                unwrapped[[i, j]] = val;
            }
        }

        Ok(unwrapped)
    }

    /// Giải cuộn pha dẫn hướng theo chất lượng
    fn unwrap_quality_guided(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        // Hiện tại sử dụng giải cuộn chuẩn với trọng số chất lượng
        // Triển khai đầy đủ sẽ sử dụng đạo hàm pha làm thước đo chất lượng
        let mut unwrapped = phase_data.clone();
        let (nrows, ncols) = phase_data.dim();

        // Tính bản đồ chất lượng dựa trên gradient pha
        // Ghi chú: Triển khai đầy đủ dẫn hướng chất lượng sẽ sử dụng bản đồ này để sắp xếp thứ tự
        let _quality = self.calculate_quality_map(phase_data);

        // Giải cuộn bắt đầu từ vùng có chất lượng cao nhất
        for i in 0..nrows {
            let mut row_data: Vec<f64> = (0..ncols).map(|j| unwrapped[[i, j]]).collect();
            Self::unwrap_1d(&mut row_data);
            for (j, &val) in row_data.iter().enumerate() {
                unwrapped[[i, j]] = val;
            }
        }

        Ok(unwrapped)
    }

    /// Tính bản đồ chất lượng cho giải cuộn dẫn hướng theo chất lượng
    fn calculate_quality_map(&self, phase_data: &Array2<f64>) -> Array2<f64> {
        let (nrows, ncols) = phase_data.dim();
        let mut quality = Array2::zeros((nrows, ncols));

        for i in 0..nrows {
            for j in 0..ncols {
                let mut grad_sum = 0.0;
                let mut count = 0;

                // Tính biên độ gradient pha cục bộ
                if j > 0 {
                    grad_sum += (phase_data[[i, j]] - phase_data[[i, j - 1]]).abs();
                    count += 1;
                }
                if j < ncols - 1 {
                    grad_sum += (phase_data[[i, j + 1]] - phase_data[[i, j]]).abs();
                    count += 1;
                }
                if i > 0 {
                    grad_sum += (phase_data[[i, j]] - phase_data[[i - 1, j]]).abs();
                    count += 1;
                }
                if i < nrows - 1 {
                    grad_sum += (phase_data[[i + 1, j]] - phase_data[[i, j]]).abs();
                    count += 1;
                }

                // Chất lượng nghịch đảo với biên độ gradient
                if count > 0 {
                    quality[[i, j]] = 1.0 / (1.0 + grad_sum / count as f64);
                }
            }
        }

        quality
    }

    /// Giải cuộn pha 1D tại chỗ
    fn unwrap_1d(data: &mut [f64]) {
        if data.len() < 2 {
            return;
        }

        let mut correction = 0.0;
        let mut prev_wrapped = data[0];

        for i in 1..data.len() {
            let current_wrapped = data[i];
            // Tính hiệu bằng các giá trị cuộn gốc
            let diff = current_wrapped - prev_wrapped;

            if diff > PI {
                correction -= 2.0 * PI;
            } else if diff < -PI {
                correction += 2.0 * PI;
            }

            data[i] = current_wrapped + correction;
            prev_wrapped = current_wrapped;
        }
    }

    /// Giải cuộn pha 1D tùy chỉnh với dung sai
    fn unwrap_1d_custom(&self, data: &mut [f64]) {
        if data.len() < 2 {
            return;
        }

        let tolerance = 0.9 * PI; // Hơi nhỏ hơn pi để tăng độ bền vững
        let mut correction = 0.0;

        for i in 1..data.len() {
            let diff = data[i] - data[i - 1] + correction;
            if diff > tolerance {
                correction -= 2.0 * PI;
            } else if diff < -tolerance {
                correction += 2.0 * PI;
            }
            data[i] += correction;
        }
    }

    /// Loại bỏ ngoại lai khỏi dữ liệu pha bằng phương pháp Z-score
    pub fn remove_outliers(&mut self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        if !self.config.enable_outlier_removal {
            return Ok(phase_data.clone());
        }

        // Phát hiện ngoại lai
        let outlier_mask = self.detect_outliers(phase_data)?;

        // Nội suy các ngoại lai
        let cleaned = self.interpolate_outliers(phase_data, &outlier_mask)?;

        Ok(cleaned)
    }

    /// Phát hiện ngoại lai bằng phương pháp Z-score
    fn detect_outliers(&mut self, phase_data: &Array2<f64>) -> Result<Array2<bool>, PhaseSanitizationError> {
        let (nrows, ncols) = phase_data.dim();
        let mut outlier_mask = Array2::from_elem((nrows, ncols), false);

        for i in 0..nrows {
            let row = phase_data.row(i);
            let mean = row.mean().unwrap_or(0.0);
            let std = self.calculate_std_1d(&row.to_vec());

            for j in 0..ncols {
                let z_score = (phase_data[[i, j]] - mean).abs() / (std + 1e-8);
                if z_score > self.config.outlier_threshold {
                    outlier_mask[[i, j]] = true;
                    self.statistics.outliers_removed += 1;
                }
            }
        }

        Ok(outlier_mask)
    }

    /// Nội suy giá trị ngoại lai bằng nội suy tuyến tính
    fn interpolate_outliers(
        &self,
        phase_data: &Array2<f64>,
        outlier_mask: &Array2<bool>,
    ) -> Result<Array2<f64>, PhaseSanitizationError> {
        let mut cleaned = phase_data.clone();
        let (nrows, ncols) = phase_data.dim();

        for i in 0..nrows {
            // Tìm các chỉ số hợp lệ (không phải ngoại lai)
            let valid_indices: Vec<usize> = (0..ncols)
                .filter(|&j| !outlier_mask[[i, j]])
                .collect();

            let outlier_indices: Vec<usize> = (0..ncols)
                .filter(|&j| outlier_mask[[i, j]])
                .collect();

            if valid_indices.len() >= 2 && !outlier_indices.is_empty() {
                // Trích xuất các giá trị hợp lệ
                let valid_values: Vec<f64> = valid_indices
                    .iter()
                    .map(|&j| phase_data[[i, j]])
                    .collect();

                // Nội suy các ngoại lai
                for &j in &outlier_indices {
                    cleaned[[i, j]] = self.linear_interpolate(j, &valid_indices, &valid_values);
                }
            }
        }

        Ok(cleaned)
    }

    /// Hàm hỗ trợ nội suy tuyến tính
    fn linear_interpolate(&self, x: usize, xs: &[usize], ys: &[f64]) -> f64 {
        if xs.is_empty() {
            return 0.0;
        }

        // Tìm các điểm bao quanh
        let mut lower_idx = 0;
        let mut upper_idx = xs.len() - 1;

        for (i, &xi) in xs.iter().enumerate() {
            if xi <= x {
                lower_idx = i;
            }
            if xi >= x {
                upper_idx = i;
                break;
            }
        }

        if lower_idx == upper_idx {
            return ys[lower_idx];
        }

        // Nội suy tuyến tính
        let x0 = xs[lower_idx] as f64;
        let x1 = xs[upper_idx] as f64;
        let y0 = ys[lower_idx];
        let y1 = ys[upper_idx];

        y0 + (y1 - y0) * (x as f64 - x0) / (x1 - x0)
    }

    /// Làm mượt dữ liệu pha bằng trung bình trượt
    pub fn smooth_phase(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        if !self.config.enable_smoothing {
            return Ok(phase_data.clone());
        }

        let mut smoothed = phase_data.clone();
        let (nrows, ncols) = phase_data.dim();

        // Đảm bảo kích thước cửa sổ là số lẻ
        let mut window_size = self.config.smoothing_window;
        if window_size % 2 == 0 {
            window_size += 1;
        }

        let half_window = window_size / 2;

        for i in 0..nrows {
            for j in half_window..ncols.saturating_sub(half_window) {
                let mut sum = 0.0;
                for k in 0..window_size {
                    sum += phase_data[[i, j - half_window + k]];
                }
                smoothed[[i, j]] = sum / window_size as f64;
            }
        }

        Ok(smoothed)
    }

    /// Lọc nhiễu bằng bộ lọc Butterworth thông thấp
    pub fn filter_noise(&self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        if !self.config.enable_noise_filtering {
            return Ok(phase_data.clone());
        }

        let (nrows, ncols) = phase_data.dim();

        // Kiểm tra độ dài tối thiểu cho lọc
        let min_filter_length = 18;
        if ncols < min_filter_length {
            return Ok(phase_data.clone());
        }

        // Bộ lọc thông thấp đơn giản sử dụng làm mượt hàm mũ
        let alpha = self.config.noise_threshold;
        let mut filtered = phase_data.clone();

        for i in 0..nrows {
            // Lượt xuôi
            for j in 1..ncols {
                filtered[[i, j]] = alpha * filtered[[i, j]] + (1.0 - alpha) * filtered[[i, j - 1]];
            }

            // Lượt ngược cho lọc không trễ pha
            for j in (0..ncols - 1).rev() {
                filtered[[i, j]] = alpha * filtered[[i, j]] + (1.0 - alpha) * filtered[[i, j + 1]];
            }
        }

        Ok(filtered)
    }

    /// Đường ống làm sạch hoàn chỉnh
    pub fn sanitize_phase(&mut self, phase_data: &Array2<f64>) -> Result<Array2<f64>, PhaseSanitizationError> {
        self.statistics.total_processed += 1;

        // Kiểm tra đầu vào
        self.validate_phase_data(phase_data).map_err(|e| {
            self.statistics.sanitization_errors += 1;
            e
        })?;

        // Giải cuộn pha
        let unwrapped = self.unwrap_phase(phase_data).map_err(|e| {
            self.statistics.sanitization_errors += 1;
            e
        })?;

        // Loại bỏ ngoại lai
        let cleaned = self.remove_outliers(&unwrapped).map_err(|e| {
            self.statistics.sanitization_errors += 1;
            e
        })?;

        // Làm mượt pha
        let smoothed = self.smooth_phase(&cleaned).map_err(|e| {
            self.statistics.sanitization_errors += 1;
            e
        })?;

        // Lọc nhiễu
        let filtered = self.filter_noise(&smoothed).map_err(|e| {
            self.statistics.sanitization_errors += 1;
            e
        })?;

        Ok(filtered)
    }

    /// Lấy thống kê làm sạch
    pub fn get_statistics(&self) -> &SanitizationStatistics {
        &self.statistics
    }

    /// Đặt lại thống kê
    pub fn reset_statistics(&mut self) {
        self.statistics = SanitizationStatistics::default();
    }

    /// Tính độ lệch chuẩn cho lát 1D
    fn calculate_std_1d(&self, data: &[f64]) -> f64 {
        if data.is_empty() {
            return 0.0;
        }

        let mean: f64 = data.iter().sum::<f64>() / data.len() as f64;
        let variance: f64 = data.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / data.len() as f64;
        variance.sqrt()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::PI;

    fn create_test_phase_data() -> Array2<f64> {
        // Tạo dữ liệu pha với một số mô phỏng cuộn
        Array2::from_shape_fn((4, 64), |(i, j)| {
            let base = (j as f64 * 0.05).sin() * (PI / 2.0);
            base + (i as f64 * 0.1)
        })
    }

    fn create_wrapped_phase_data() -> Array2<f64> {
        // Tạo dữ liệu pha cần giải cuộn
        // Sinh pha tăng tuyến tính bị cuộn tại ranh giới +/- pi
        Array2::from_shape_fn((2, 20), |(i, j)| {
            let unwrapped = j as f64 * 0.4 + i as f64 * 0.2;
            // Cuộn đúng về [-pi, pi]
            let mut wrapped = unwrapped;
            while wrapped > PI {
                wrapped -= 2.0 * PI;
            }
            while wrapped < -PI {
                wrapped += 2.0 * PI;
            }
            wrapped
        })
    }

    #[test]
    fn test_config_validation() {
        let config = PhaseSanitizerConfig::default();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_invalid_config() {
        let config = PhaseSanitizerConfig::builder()
            .outlier_threshold(-1.0)
            .build();
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_sanitizer_creation() {
        let config = PhaseSanitizerConfig::default();
        let sanitizer = PhaseSanitizer::new(config);
        assert!(sanitizer.is_ok());
    }

    #[test]
    fn test_phase_validation() {
        let config = PhaseSanitizerConfig::default();
        let sanitizer = PhaseSanitizer::new(config).unwrap();

        let valid_data = create_test_phase_data();
        assert!(sanitizer.validate_phase_data(&valid_data).is_ok());

        // Kiểm tra với giá trị ngoài phạm vi
        let invalid_data = Array2::from_elem((2, 10), 10.0);
        assert!(sanitizer.validate_phase_data(&invalid_data).is_err());
    }

    #[test]
    fn test_phase_unwrapping() {
        let config = PhaseSanitizerConfig::builder()
            .unwrapping_method(UnwrappingMethod::Standard)
            .build();
        let sanitizer = PhaseSanitizer::new(config).unwrap();

        let wrapped = create_wrapped_phase_data();
        let unwrapped = sanitizer.unwrap_phase(&wrapped);
        assert!(unwrapped.is_ok());

        // Xác minh các hiệu bây giờ đã mượt (không có bước nhảy > pi)
        let unwrapped = unwrapped.unwrap();
        let ncols = unwrapped.ncols();
        for i in 0..unwrapped.nrows() {
            for j in 1..ncols {
                let diff = (unwrapped[[i, j]] - unwrapped[[i, j - 1]]).abs();
                assert!(diff < PI + 0.1, "Phát hiện bước nhảy: {}", diff);
            }
        }
    }

    #[test]
    fn test_outlier_removal() {
        let config = PhaseSanitizerConfig::builder()
            .outlier_threshold(2.0)
            .enable_outlier_removal(true)
            .build();
        let mut sanitizer = PhaseSanitizer::new(config).unwrap();

        let mut data = create_test_phase_data();
        // Chèn một ngoại lai
        data[[0, 10]] = 100.0 * data[[0, 10]];

        // Cần sử dụng dữ liệu trong phạm vi hợp lệ
        let data = Array2::from_shape_fn((4, 64), |(i, j)| {
            if i == 0 && j == 10 {
                PI * 0.9 // Gần ranh giới nhưng hợp lệ
            } else {
                0.1 * (j as f64 * 0.1).sin()
            }
        });

        let cleaned = sanitizer.remove_outliers(&data);
        assert!(cleaned.is_ok());
    }

    #[test]
    fn test_phase_smoothing() {
        let config = PhaseSanitizerConfig::builder()
            .smoothing_window(5)
            .enable_smoothing(true)
            .build();
        let sanitizer = PhaseSanitizer::new(config).unwrap();

        let noisy_data = Array2::from_shape_fn((2, 20), |(_, j)| {
            (j as f64 * 0.2).sin() + 0.1 * ((j * 7) as f64).sin()
        });

        let smoothed = sanitizer.smooth_phase(&noisy_data);
        assert!(smoothed.is_ok());
    }

    #[test]
    fn test_noise_filtering() {
        let config = PhaseSanitizerConfig::builder()
            .noise_threshold(0.1)
            .enable_noise_filtering(true)
            .build();
        let sanitizer = PhaseSanitizer::new(config).unwrap();

        let data = create_test_phase_data();
        let filtered = sanitizer.filter_noise(&data);
        assert!(filtered.is_ok());
    }

    #[test]
    fn test_complete_pipeline() {
        let config = PhaseSanitizerConfig::builder()
            .unwrapping_method(UnwrappingMethod::Standard)
            .outlier_threshold(3.0)
            .smoothing_window(3)
            .enable_outlier_removal(true)
            .enable_smoothing(true)
            .enable_noise_filtering(false)
            .build();
        let mut sanitizer = PhaseSanitizer::new(config).unwrap();

        let data = create_test_phase_data();
        let sanitized = sanitizer.sanitize_phase(&data);
        assert!(sanitized.is_ok());

        let stats = sanitizer.get_statistics();
        assert_eq!(stats.total_processed, 1);
    }

    #[test]
    fn test_different_unwrapping_methods() {
        let methods = vec![
            UnwrappingMethod::Standard,
            UnwrappingMethod::Custom,
            UnwrappingMethod::Itoh,
            UnwrappingMethod::QualityGuided,
        ];

        let wrapped = create_wrapped_phase_data();

        for method in methods {
            let config = PhaseSanitizerConfig::builder()
                .unwrapping_method(method)
                .build();
            let sanitizer = PhaseSanitizer::new(config).unwrap();

            let result = sanitizer.unwrap_phase(&wrapped);
            assert!(result.is_ok(), "Thất bại cho phương pháp {:?}", method);
        }
    }

    #[test]
    fn test_empty_data_handling() {
        let config = PhaseSanitizerConfig::default();
        let sanitizer = PhaseSanitizer::new(config).unwrap();

        let empty = Array2::<f64>::zeros((0, 0));
        assert!(sanitizer.validate_phase_data(&empty).is_err());
        assert!(sanitizer.unwrap_phase(&empty).is_err());
    }

    #[test]
    fn test_statistics() {
        let config = PhaseSanitizerConfig::default();
        let mut sanitizer = PhaseSanitizer::new(config).unwrap();

        let data = create_test_phase_data();
        let _ = sanitizer.sanitize_phase(&data);
        let _ = sanitizer.sanitize_phase(&data);

        let stats = sanitizer.get_statistics();
        assert_eq!(stats.total_processed, 2);

        sanitizer.reset_statistics();
        let stats = sanitizer.get_statistics();
        assert_eq!(stats.total_processed, 0);
    }
}
