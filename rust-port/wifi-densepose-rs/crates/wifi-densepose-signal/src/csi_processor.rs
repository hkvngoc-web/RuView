//! Bộ xử lý CSI (Thông tin trạng thái kênh)
//!
//! Module này cung cấp chức năng tiền xử lý và xử lý dữ liệu CSI
//! từ tín hiệu WiFi cho ước lượng tư thế con người.

use chrono::{DateTime, Utc};
use ndarray::Array2;
use num_complex::Complex64;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::f64::consts::PI;
use thiserror::Error;

/// Các lỗi có thể xảy ra trong quá trình xử lý CSI
#[derive(Debug, Error)]
pub enum CsiProcessorError {
    /// Tham số cấu hình không hợp lệ
    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),

    /// Tiền xử lý thất bại
    #[error("Tiền xử lý thất bại: {0}")]
    PreprocessingFailed(String),

    /// Trích xuất đặc trưng thất bại
    #[error("Trích xuất đặc trưng thất bại: {0}")]
    FeatureExtractionFailed(String),

    /// Dữ liệu đầu vào không hợp lệ
    #[error("Dữ liệu đầu vào không hợp lệ: {0}")]
    InvalidData(String),

    /// Lỗi đường ống xử lý
    #[error("Lỗi đường ống: {0}")]
    PipelineError(String),
}

/// Cấu trúc dữ liệu CSI chứa các phép đo kênh thô
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CsiData {
    /// Dấu thời gian của phép đo
    pub timestamp: DateTime<Utc>,

    /// Giá trị biên độ (số_anten x số_sóng_mang_con)
    pub amplitude: Array2<f64>,

    /// Giá trị pha tính bằng radian (số_anten x số_sóng_mang_con)
    pub phase: Array2<f64>,

    /// Tần số trung tâm tính bằng Hz
    pub frequency: f64,

    /// Băng thông tính bằng Hz
    pub bandwidth: f64,

    /// Số sóng mang con
    pub num_subcarriers: usize,

    /// Số anten
    pub num_antennas: usize,

    /// Tỉ số tín hiệu trên nhiễu tính bằng dB
    pub snr: f64,

    /// Siêu dữ liệu bổ sung
    #[serde(default)]
    pub metadata: CsiMetadata,
}

/// Siêu dữ liệu liên quan đến dữ liệu CSI
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CsiMetadata {
    /// Đã áp dụng lọc nhiễu hay chưa
    pub noise_filtered: bool,

    /// Đã áp dụng cửa sổ hay chưa
    pub windowed: bool,

    /// Đã áp dụng chuẩn hóa hay chưa
    pub normalized: bool,

    /// Siêu dữ liệu tùy chỉnh bổ sung
    #[serde(flatten)]
    pub custom: std::collections::HashMap<String, serde_json::Value>,
}

/// Bộ xây dựng cho CsiData
#[derive(Debug, Default)]
pub struct CsiDataBuilder {
    timestamp: Option<DateTime<Utc>>,
    amplitude: Option<Array2<f64>>,
    phase: Option<Array2<f64>>,
    frequency: Option<f64>,
    bandwidth: Option<f64>,
    snr: Option<f64>,
    metadata: CsiMetadata,
}

impl CsiDataBuilder {
    /// Tạo bộ xây dựng mới
    pub fn new() -> Self {
        Self::default()
    }

    /// Đặt dấu thời gian
    pub fn timestamp(mut self, timestamp: DateTime<Utc>) -> Self {
        self.timestamp = Some(timestamp);
        self
    }

    /// Đặt dữ liệu biên độ
    pub fn amplitude(mut self, amplitude: Array2<f64>) -> Self {
        self.amplitude = Some(amplitude);
        self
    }

    /// Đặt dữ liệu pha
    pub fn phase(mut self, phase: Array2<f64>) -> Self {
        self.phase = Some(phase);
        self
    }

    /// Đặt tần số trung tâm
    pub fn frequency(mut self, frequency: f64) -> Self {
        self.frequency = Some(frequency);
        self
    }

    /// Đặt băng thông
    pub fn bandwidth(mut self, bandwidth: f64) -> Self {
        self.bandwidth = Some(bandwidth);
        self
    }

    /// Đặt SNR
    pub fn snr(mut self, snr: f64) -> Self {
        self.snr = Some(snr);
        self
    }

    /// Đặt siêu dữ liệu
    pub fn metadata(mut self, metadata: CsiMetadata) -> Self {
        self.metadata = metadata;
        self
    }

    /// Xây dựng CsiData
    pub fn build(self) -> Result<CsiData, CsiProcessorError> {
        let amplitude = self
            .amplitude
            .ok_or_else(|| CsiProcessorError::InvalidData("Dữ liệu biên độ là bắt buộc".into()))?;
        let phase = self
            .phase
            .ok_or_else(|| CsiProcessorError::InvalidData("Dữ liệu pha là bắt buộc".into()))?;

        if amplitude.shape() != phase.shape() {
            return Err(CsiProcessorError::InvalidData(
                "Biên độ và pha phải có cùng kích thước".into(),
            ));
        }

        let (num_antennas, num_subcarriers) = amplitude.dim();

        Ok(CsiData {
            timestamp: self.timestamp.unwrap_or_else(Utc::now),
            amplitude,
            phase,
            frequency: self.frequency.unwrap_or(5.0e9), // Mặc định 5 GHz
            bandwidth: self.bandwidth.unwrap_or(20.0e6), // Mặc định 20 MHz
            num_subcarriers,
            num_antennas,
            snr: self.snr.unwrap_or(20.0),
            metadata: self.metadata,
        })
    }
}

impl CsiData {
    /// Tạo bộ xây dựng CsiData mới
    pub fn builder() -> CsiDataBuilder {
        CsiDataBuilder::new()
    }

    /// Lấy giá trị CSI dạng số phức
    pub fn to_complex(&self) -> Array2<Complex64> {
        let mut complex = Array2::zeros(self.amplitude.dim());
        for ((i, j), amp) in self.amplitude.indexed_iter() {
            let phase = self.phase[[i, j]];
            complex[[i, j]] = Complex64::from_polar(*amp, phase);
        }
        complex
    }

    /// Tạo từ giá trị số phức
    pub fn from_complex(
        complex: &Array2<Complex64>,
        frequency: f64,
        bandwidth: f64,
    ) -> Result<Self, CsiProcessorError> {
        let (num_antennas, num_subcarriers) = complex.dim();
        let mut amplitude = Array2::zeros(complex.dim());
        let mut phase = Array2::zeros(complex.dim());

        for ((i, j), c) in complex.indexed_iter() {
            amplitude[[i, j]] = c.norm();
            phase[[i, j]] = c.arg();
        }

        Ok(Self {
            timestamp: Utc::now(),
            amplitude,
            phase,
            frequency,
            bandwidth,
            num_subcarriers,
            num_antennas,
            snr: 20.0,
            metadata: CsiMetadata::default(),
        })
    }
}

/// Cấu hình cho bộ xử lý CSI
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CsiProcessorConfig {
    /// Tần số lấy mẫu tính bằng Hz
    pub sampling_rate: f64,

    /// Kích thước cửa sổ cho xử lý
    pub window_size: usize,

    /// Tỉ lệ chồng lấp (0.0 đến 1.0)
    pub overlap: f64,

    /// Ngưỡng nhiễu tính bằng dB
    pub noise_threshold: f64,

    /// Ngưỡng phát hiện con người (0.0 đến 1.0)
    pub human_detection_threshold: f64,

    /// Hệ số làm mịn thời gian (0.0 đến 1.0)
    pub smoothing_factor: f64,

    /// Kích thước lịch sử tối đa
    pub max_history_size: usize,

    /// Bật tiền xử lý
    pub enable_preprocessing: bool,

    /// Bật trích xuất đặc trưng
    pub enable_feature_extraction: bool,

    /// Bật phát hiện con người
    pub enable_human_detection: bool,
}

impl Default for CsiProcessorConfig {
    fn default() -> Self {
        Self {
            sampling_rate: 1000.0,
            window_size: 256,
            overlap: 0.5,
            noise_threshold: -30.0,
            human_detection_threshold: 0.8,
            smoothing_factor: 0.9,
            max_history_size: 500,
            enable_preprocessing: true,
            enable_feature_extraction: true,
            enable_human_detection: true,
        }
    }
}

/// Bộ xây dựng cho CsiProcessorConfig
#[derive(Debug, Default)]
pub struct CsiProcessorConfigBuilder {
    config: CsiProcessorConfig,
}

impl CsiProcessorConfigBuilder {
    /// Tạo bộ xây dựng mới
    pub fn new() -> Self {
        Self {
            config: CsiProcessorConfig::default(),
        }
    }

    /// Đặt tần số lấy mẫu
    pub fn sampling_rate(mut self, rate: f64) -> Self {
        self.config.sampling_rate = rate;
        self
    }

    /// Đặt kích thước cửa sổ
    pub fn window_size(mut self, size: usize) -> Self {
        self.config.window_size = size;
        self
    }

    /// Đặt tỉ lệ chồng lấp
    pub fn overlap(mut self, overlap: f64) -> Self {
        self.config.overlap = overlap;
        self
    }

    /// Đặt ngưỡng nhiễu
    pub fn noise_threshold(mut self, threshold: f64) -> Self {
        self.config.noise_threshold = threshold;
        self
    }

    /// Đặt ngưỡng phát hiện con người
    pub fn human_detection_threshold(mut self, threshold: f64) -> Self {
        self.config.human_detection_threshold = threshold;
        self
    }

    /// Đặt hệ số làm mịn
    pub fn smoothing_factor(mut self, factor: f64) -> Self {
        self.config.smoothing_factor = factor;
        self
    }

    /// Đặt kích thước lịch sử tối đa
    pub fn max_history_size(mut self, size: usize) -> Self {
        self.config.max_history_size = size;
        self
    }

    /// Bật/tắt tiền xử lý
    pub fn enable_preprocessing(mut self, enable: bool) -> Self {
        self.config.enable_preprocessing = enable;
        self
    }

    /// Bật/tắt trích xuất đặc trưng
    pub fn enable_feature_extraction(mut self, enable: bool) -> Self {
        self.config.enable_feature_extraction = enable;
        self
    }

    /// Bật/tắt phát hiện con người
    pub fn enable_human_detection(mut self, enable: bool) -> Self {
        self.config.enable_human_detection = enable;
        self
    }

    /// Xây dựng cấu hình
    pub fn build(self) -> CsiProcessorConfig {
        self.config
    }
}

impl CsiProcessorConfig {
    /// Tạo bộ xây dựng cấu hình mới
    pub fn builder() -> CsiProcessorConfigBuilder {
        CsiProcessorConfigBuilder::new()
    }

    /// Kiểm tra tính hợp lệ của cấu hình
    pub fn validate(&self) -> Result<(), CsiProcessorError> {
        if self.sampling_rate <= 0.0 {
            return Err(CsiProcessorError::InvalidConfig(
                "sampling_rate phải dương".into(),
            ));
        }

        if self.window_size == 0 {
            return Err(CsiProcessorError::InvalidConfig(
                "window_size phải dương".into(),
            ));
        }

        if !(0.0..1.0).contains(&self.overlap) {
            return Err(CsiProcessorError::InvalidConfig(
                "overlap phải nằm trong khoảng 0 đến 1".into(),
            ));
        }

        Ok(())
    }
}

/// Bộ tiền xử lý CSI để làm sạch và chuẩn bị dữ liệu CSI thô
#[derive(Debug)]
pub struct CsiPreprocessor {
    noise_threshold: f64,
}

impl CsiPreprocessor {
    /// Tạo bộ tiền xử lý mới
    pub fn new(noise_threshold: f64) -> Self {
        Self { noise_threshold }
    }

    /// Loại bỏ nhiễu khỏi dữ liệu CSI dựa trên ngưỡng biên độ
    pub fn remove_noise(&self, csi_data: &CsiData) -> Result<CsiData, CsiProcessorError> {
        // Chuyển biên độ sang dB
        let amplitude_db = csi_data.amplitude.mapv(|a| 20.0 * (a + 1e-12).log10());

        // Tạo mặt nạ nhiễu
        let noise_mask = amplitude_db.mapv(|db| db > self.noise_threshold);

        // Áp dụng mặt nạ lên biên độ
        let mut filtered_amplitude = csi_data.amplitude.clone();
        for ((i, j), &mask) in noise_mask.indexed_iter() {
            if !mask {
                filtered_amplitude[[i, j]] = 0.0;
            }
        }

        let mut metadata = csi_data.metadata.clone();
        metadata.noise_filtered = true;

        Ok(CsiData {
            timestamp: csi_data.timestamp,
            amplitude: filtered_amplitude,
            phase: csi_data.phase.clone(),
            frequency: csi_data.frequency,
            bandwidth: csi_data.bandwidth,
            num_subcarriers: csi_data.num_subcarriers,
            num_antennas: csi_data.num_antennas,
            snr: csi_data.snr,
            metadata,
        })
    }

    /// Áp dụng cửa sổ Hamming để giảm rò rỉ phổ
    pub fn apply_windowing(&self, csi_data: &CsiData) -> Result<CsiData, CsiProcessorError> {
        let n = csi_data.num_subcarriers;
        let window = Self::hamming_window(n);

        // Áp dụng cửa sổ lên biên độ của mỗi anten
        let mut windowed_amplitude = csi_data.amplitude.clone();
        for mut row in windowed_amplitude.rows_mut() {
            for (i, val) in row.iter_mut().enumerate() {
                *val *= window[i];
            }
        }

        let mut metadata = csi_data.metadata.clone();
        metadata.windowed = true;

        Ok(CsiData {
            timestamp: csi_data.timestamp,
            amplitude: windowed_amplitude,
            phase: csi_data.phase.clone(),
            frequency: csi_data.frequency,
            bandwidth: csi_data.bandwidth,
            num_subcarriers: csi_data.num_subcarriers,
            num_antennas: csi_data.num_antennas,
            snr: csi_data.snr,
            metadata,
        })
    }

    /// Chuẩn hóa giá trị biên độ về phương sai đơn vị
    pub fn normalize_amplitude(&self, csi_data: &CsiData) -> Result<CsiData, CsiProcessorError> {
        let std_dev = self.calculate_std(&csi_data.amplitude);
        let normalized_amplitude = csi_data.amplitude.mapv(|a| a / (std_dev + 1e-12));

        let mut metadata = csi_data.metadata.clone();
        metadata.normalized = true;

        Ok(CsiData {
            timestamp: csi_data.timestamp,
            amplitude: normalized_amplitude,
            phase: csi_data.phase.clone(),
            frequency: csi_data.frequency,
            bandwidth: csi_data.bandwidth,
            num_subcarriers: csi_data.num_subcarriers,
            num_antennas: csi_data.num_antennas,
            snr: csi_data.snr,
            metadata,
        })
    }

    /// Tạo cửa sổ Hamming
    fn hamming_window(n: usize) -> Vec<f64> {
        (0..n)
            .map(|i| 0.54 - 0.46 * (2.0 * PI * i as f64 / (n - 1) as f64).cos())
            .collect()
    }

    /// Tính độ lệch chuẩn
    fn calculate_std(&self, arr: &Array2<f64>) -> f64 {
        let mean = arr.mean().unwrap_or(0.0);
        let variance = arr.mapv(|x| (x - mean).powi(2)).mean().unwrap_or(0.0);
        variance.sqrt()
    }
}

/// Thống kê cho xử lý CSI
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProcessingStatistics {
    /// Tổng số mẫu đã xử lý
    pub total_processed: usize,

    /// Số lỗi xử lý
    pub processing_errors: usize,

    /// Số lần phát hiện con người
    pub human_detections: usize,

    /// Kích thước lịch sử hiện tại
    pub history_size: usize,
}

impl ProcessingStatistics {
    /// Tính tỉ lệ lỗi
    pub fn error_rate(&self) -> f64 {
        if self.total_processed > 0 {
            self.processing_errors as f64 / self.total_processed as f64
        } else {
            0.0
        }
    }

    /// Tính tỉ lệ phát hiện
    pub fn detection_rate(&self) -> f64 {
        if self.total_processed > 0 {
            self.human_detections as f64 / self.total_processed as f64
        } else {
            0.0
        }
    }
}

/// Bộ xử lý CSI chính cho WiFi-DensePose
#[derive(Debug)]
pub struct CsiProcessor {
    config: CsiProcessorConfig,
    preprocessor: CsiPreprocessor,
    history: VecDeque<CsiData>,
    previous_detection_confidence: f64,
    statistics: ProcessingStatistics,
}

impl CsiProcessor {
    /// Tạo bộ xử lý CSI mới
    pub fn new(config: CsiProcessorConfig) -> Result<Self, CsiProcessorError> {
        config.validate()?;

        let preprocessor = CsiPreprocessor::new(config.noise_threshold);

        Ok(Self {
            history: VecDeque::with_capacity(config.max_history_size),
            config,
            preprocessor,
            previous_detection_confidence: 0.0,
            statistics: ProcessingStatistics::default(),
        })
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &CsiProcessorConfig {
        &self.config
    }

    /// Tiền xử lý dữ liệu CSI
    pub fn preprocess(&self, csi_data: &CsiData) -> Result<CsiData, CsiProcessorError> {
        if !self.config.enable_preprocessing {
            return Ok(csi_data.clone());
        }

        // Loại bỏ nhiễu
        let cleaned = self.preprocessor.remove_noise(csi_data)?;

        // Áp dụng cửa sổ
        let windowed = self.preprocessor.apply_windowing(&cleaned)?;

        // Chuẩn hóa biên độ
        let normalized = self.preprocessor.normalize_amplitude(&windowed)?;

        Ok(normalized)
    }

    /// Thêm dữ liệu CSI vào lịch sử
    pub fn add_to_history(&mut self, csi_data: CsiData) {
        if self.history.len() >= self.config.max_history_size {
            self.history.pop_front();
        }
        self.history.push_back(csi_data);
        self.statistics.history_size = self.history.len();
    }

    /// Xóa lịch sử
    pub fn clear_history(&mut self) {
        self.history.clear();
        self.statistics.history_size = 0;
    }

    /// Lấy lịch sử gần đây
    pub fn get_recent_history(&self, count: usize) -> Vec<&CsiData> {
        let len = self.history.len();
        if count >= len {
            self.history.iter().collect()
        } else {
            self.history.iter().skip(len - count).collect()
        }
    }

    /// Lấy chiều dài lịch sử
    pub fn history_len(&self) -> usize {
        self.history.len()
    }

    /// Áp dụng làm mịn thời gian (trung bình động hàm mũ)
    pub fn apply_temporal_smoothing(&mut self, raw_confidence: f64) -> f64 {
        let smoothed = self.config.smoothing_factor * self.previous_detection_confidence
            + (1.0 - self.config.smoothing_factor) * raw_confidence;
        self.previous_detection_confidence = smoothed;
        smoothed
    }

    /// Lấy thống kê xử lý
    pub fn get_statistics(&self) -> &ProcessingStatistics {
        &self.statistics
    }

    /// Đặt lại thống kê
    pub fn reset_statistics(&mut self) {
        self.statistics = ProcessingStatistics::default();
    }

    /// Tăng bộ đếm đã xử lý
    pub fn increment_processed(&mut self) {
        self.statistics.total_processed += 1;
    }

    /// Tăng bộ đếm lỗi
    pub fn increment_errors(&mut self) {
        self.statistics.processing_errors += 1;
    }

    /// Tăng bộ đếm phát hiện con người
    pub fn increment_detections(&mut self) {
        self.statistics.human_detections += 1;
    }

    /// Lấy độ tin cậy phát hiện trước đó
    pub fn previous_confidence(&self) -> f64 {
        self.previous_detection_confidence
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::Array2;

    fn create_test_csi_data() -> CsiData {
        let amplitude = Array2::from_shape_fn((4, 64), |(i, j)| {
            1.0 + 0.1 * ((i + j) as f64).sin()
        });
        let phase = Array2::from_shape_fn((4, 64), |(i, j)| {
            0.5 * ((i + j) as f64 * 0.1).sin()
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

    #[test]
    fn test_config_validation() {
        let config = CsiProcessorConfig::builder()
            .sampling_rate(1000.0)
            .window_size(256)
            .overlap(0.5)
            .build();

        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_invalid_config() {
        let config = CsiProcessorConfig::builder()
            .sampling_rate(-100.0)
            .build();

        assert!(config.validate().is_err());
    }

    #[test]
    fn test_csi_processor_creation() {
        let config = CsiProcessorConfig::default();
        let processor = CsiProcessor::new(config);
        assert!(processor.is_ok());
    }

    #[test]
    fn test_preprocessing() {
        let config = CsiProcessorConfig::default();
        let processor = CsiProcessor::new(config).unwrap();
        let csi_data = create_test_csi_data();

        let result = processor.preprocess(&csi_data);
        assert!(result.is_ok());

        let preprocessed = result.unwrap();
        assert!(preprocessed.metadata.noise_filtered);
        assert!(preprocessed.metadata.windowed);
        assert!(preprocessed.metadata.normalized);
    }

    #[test]
    fn test_history_management() {
        let config = CsiProcessorConfig::builder()
            .max_history_size(5)
            .build();
        let mut processor = CsiProcessor::new(config).unwrap();

        for _ in 0..10 {
            let csi_data = create_test_csi_data();
            processor.add_to_history(csi_data);
        }

        assert_eq!(processor.history_len(), 5);
    }

    #[test]
    fn test_temporal_smoothing() {
        let config = CsiProcessorConfig::builder()
            .smoothing_factor(0.9)
            .build();
        let mut processor = CsiProcessor::new(config).unwrap();

        let smoothed1 = processor.apply_temporal_smoothing(1.0);
        assert!((smoothed1 - 0.1).abs() < 1e-6);

        let smoothed2 = processor.apply_temporal_smoothing(1.0);
        assert!(smoothed2 > smoothed1);
    }

    #[test]
    fn test_csi_data_builder() {
        let amplitude = Array2::ones((4, 64));
        let phase = Array2::zeros((4, 64));

        let csi_data = CsiData::builder()
            .amplitude(amplitude)
            .phase(phase)
            .frequency(2.4e9)
            .bandwidth(40.0e6)
            .snr(30.0)
            .build();

        assert!(csi_data.is_ok());
        let data = csi_data.unwrap();
        assert_eq!(data.num_antennas, 4);
        assert_eq!(data.num_subcarriers, 64);
    }

    #[test]
    fn test_complex_conversion() {
        let csi_data = create_test_csi_data();
        let complex = csi_data.to_complex();

        assert_eq!(complex.dim(), (4, 64));

        for ((i, j), c) in complex.indexed_iter() {
            let expected_amp = csi_data.amplitude[[i, j]];
            let expected_phase = csi_data.phase[[i, j]];
            let c_val: num_complex::Complex64 = *c;
            assert!((c_val.norm() - expected_amp).abs() < 1e-10);
            assert!((c_val.arg() - expected_phase).abs() < 1e-10);
        }
    }

    #[test]
    fn test_hamming_window() {
        let window = CsiPreprocessor::hamming_window(64);
        assert_eq!(window.len(), 64);

        // Cửa sổ Hamming phải đối xứng
        for i in 0..32 {
            assert!((window[i] - window[63 - i]).abs() < 1e-10);
        }

        // Giá trị đầu và cuối xấp xỉ 0.08
        assert!((window[0] - 0.08).abs() < 0.01);
    }
}
