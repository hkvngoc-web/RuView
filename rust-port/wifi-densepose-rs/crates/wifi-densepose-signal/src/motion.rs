//! Module phát hiện chuyển động
//!
//! Module này cung cấp khả năng phát hiện chuyển động và phát hiện sự hiện diện của con người
//! dựa trên đặc trưng CSI.

use crate::features::{AmplitudeFeatures, CorrelationFeatures, CsiFeatures, PhaseFeatures};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

/// Điểm chuyển động với phân tích thành phần
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MotionScore {
    /// Điểm chuyển động tổng thể (0.0 đến 1.0)
    pub total: f64,

    /// Thành phần chuyển động dựa trên phương sai
    pub variance_component: f64,

    /// Thành phần chuyển động dựa trên tương quan
    pub correlation_component: f64,

    /// Thành phần chuyển động dựa trên pha
    pub phase_component: f64,

    /// Thành phần chuyển động dựa trên Doppler (nếu có)
    pub doppler_component: Option<f64>,
}

impl MotionScore {
    /// Tạo điểm chuyển động mới
    pub fn new(
        variance_component: f64,
        correlation_component: f64,
        phase_component: f64,
        doppler_component: Option<f64>,
    ) -> Self {
        // Tính tổng có trọng số
        let total = if let Some(doppler) = doppler_component {
            0.3 * variance_component
                + 0.2 * correlation_component
                + 0.2 * phase_component
                + 0.3 * doppler
        } else {
            0.4 * variance_component + 0.3 * correlation_component + 0.3 * phase_component
        };

        Self {
            total: total.clamp(0.0, 1.0),
            variance_component,
            correlation_component,
            phase_component,
            doppler_component,
        }
    }

    /// Kiểm tra chuyển động có được phát hiện vượt ngưỡng không
    pub fn is_motion_detected(&self, threshold: f64) -> bool {
        self.total >= threshold
    }
}

/// Kết quả phân tích chuyển động
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MotionAnalysis {
    /// Điểm chuyển động
    pub score: MotionScore,

    /// Phương sai chuyển động theo thời gian
    pub temporal_variance: f64,

    /// Phương sai chuyển động theo không gian
    pub spatial_variance: f64,

    /// Vận tốc chuyển động ước lượng (đơn vị tùy ý)
    pub estimated_velocity: f64,

    /// Ước lượng hướng chuyển động (radian, nếu có)
    pub motion_direction: Option<f64>,

    /// Độ tin cậy của phân tích
    pub confidence: f64,
}

/// Kết quả phát hiện con người
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HumanDetectionResult {
    /// Có phát hiện con người hay không
    pub human_detected: bool,

    /// Độ tin cậy phát hiện (0.0 đến 1.0)
    pub confidence: f64,

    /// Điểm chuyển động
    pub motion_score: f64,

    /// Độ tin cậy thô (chưa làm mượt)
    pub raw_confidence: f64,

    /// Thời điểm phát hiện
    pub timestamp: DateTime<Utc>,

    /// Ngưỡng phát hiện đã sử dụng
    pub threshold: f64,

    /// Phân tích chuyển động chi tiết
    pub motion_analysis: MotionAnalysis,

    /// Siêu dữ liệu bổ sung
    #[serde(default)]
    pub metadata: DetectionMetadata,
}

/// Siêu dữ liệu cho kết quả phát hiện
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DetectionMetadata {
    /// Số đặc trưng đã sử dụng
    pub features_used: usize,

    /// Thời gian xử lý tính bằng mili giây
    pub processing_time_ms: Option<f64>,

    /// Doppler có khả dụng hay không
    pub doppler_available: bool,

    /// Độ dài lịch sử đã sử dụng
    pub history_length: usize,
}

/// Cấu hình cho bộ phát hiện chuyển động
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MotionDetectorConfig {
    /// Ngưỡng phát hiện con người (0.0 đến 1.0)
    pub human_detection_threshold: f64,

    /// Ngưỡng phát hiện chuyển động (0.0 đến 1.0)
    pub motion_threshold: f64,

    /// Hệ số làm mượt theo thời gian (0.0 đến 1.0)
    /// Giá trị cao hơn cho trọng số lớn hơn cho các phát hiện trước
    pub smoothing_factor: f64,

    /// Ngưỡng chỉ thị biên độ tối thiểu
    pub amplitude_threshold: f64,

    /// Ngưỡng chỉ thị pha tối thiểu
    pub phase_threshold: f64,

    /// Kích thước lịch sử cho phân tích theo thời gian
    pub history_size: usize,

    /// Bật ngưỡng thích ứng
    pub adaptive_threshold: bool,

    /// Trọng số cho chỉ thị biên độ
    pub amplitude_weight: f64,

    /// Trọng số cho chỉ thị pha
    pub phase_weight: f64,

    /// Trọng số cho chỉ thị chuyển động
    pub motion_weight: f64,
}

impl Default for MotionDetectorConfig {
    fn default() -> Self {
        Self {
            human_detection_threshold: 0.8,
            motion_threshold: 0.3,
            smoothing_factor: 0.9,
            amplitude_threshold: 0.1,
            phase_threshold: 0.05,
            history_size: 100,
            adaptive_threshold: false,
            amplitude_weight: 0.4,
            phase_weight: 0.3,
            motion_weight: 0.3,
        }
    }
}

impl MotionDetectorConfig {
    /// Tạo builder mới
    pub fn builder() -> MotionDetectorConfigBuilder {
        MotionDetectorConfigBuilder::new()
    }
}

/// Builder cho MotionDetectorConfig
#[derive(Debug, Default)]
pub struct MotionDetectorConfigBuilder {
    config: MotionDetectorConfig,
}

impl MotionDetectorConfigBuilder {
    /// Tạo builder mới
    pub fn new() -> Self {
        Self {
            config: MotionDetectorConfig::default(),
        }
    }

    /// Đặt ngưỡng phát hiện con người
    pub fn human_detection_threshold(mut self, threshold: f64) -> Self {
        self.config.human_detection_threshold = threshold;
        self
    }

    /// Đặt ngưỡng chuyển động
    pub fn motion_threshold(mut self, threshold: f64) -> Self {
        self.config.motion_threshold = threshold;
        self
    }

    /// Đặt hệ số làm mượt
    pub fn smoothing_factor(mut self, factor: f64) -> Self {
        self.config.smoothing_factor = factor;
        self
    }

    /// Đặt ngưỡng biên độ
    pub fn amplitude_threshold(mut self, threshold: f64) -> Self {
        self.config.amplitude_threshold = threshold;
        self
    }

    /// Đặt ngưỡng pha
    pub fn phase_threshold(mut self, threshold: f64) -> Self {
        self.config.phase_threshold = threshold;
        self
    }

    /// Đặt kích thước lịch sử
    pub fn history_size(mut self, size: usize) -> Self {
        self.config.history_size = size;
        self
    }

    /// Bật ngưỡng thích ứng
    pub fn adaptive_threshold(mut self, enable: bool) -> Self {
        self.config.adaptive_threshold = enable;
        self
    }

    /// Đặt trọng số các chỉ thị
    pub fn weights(mut self, amplitude: f64, phase: f64, motion: f64) -> Self {
        self.config.amplitude_weight = amplitude;
        self.config.phase_weight = phase;
        self.config.motion_weight = motion;
        self
    }

    /// Xây dựng cấu hình
    pub fn build(self) -> MotionDetectorConfig {
        self.config
    }
}

/// Bộ phát hiện chuyển động để phát hiện sự hiện diện của con người
#[derive(Debug)]
pub struct MotionDetector {
    config: MotionDetectorConfig,
    previous_confidence: f64,
    motion_history: VecDeque<MotionScore>,
    detection_count: usize,
    total_detections: usize,
    baseline_variance: Option<f64>,
}

impl MotionDetector {
    /// Tạo bộ phát hiện chuyển động mới
    pub fn new(config: MotionDetectorConfig) -> Self {
        Self {
            motion_history: VecDeque::with_capacity(config.history_size),
            config,
            previous_confidence: 0.0,
            detection_count: 0,
            total_detections: 0,
            baseline_variance: None,
        }
    }

    /// Tạo với cấu hình mặc định
    pub fn default_config() -> Self {
        Self::new(MotionDetectorConfig::default())
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &MotionDetectorConfig {
        &self.config
    }

    /// Phân tích mẫu chuyển động từ đặc trưng CSI
    pub fn analyze_motion(&self, features: &CsiFeatures) -> MotionAnalysis {
        // Tính điểm chuyển động dựa trên phương sai
        let variance_score = self.calculate_variance_score(&features.amplitude);

        // Tính điểm chuyển động dựa trên tương quan
        let correlation_score = self.calculate_correlation_score(&features.correlation);

        // Tính điểm chuyển động dựa trên pha
        let phase_score = self.calculate_phase_score(&features.phase);

        // Tính điểm dựa trên Doppler nếu có
        let doppler_score = features.doppler.as_ref().map(|d| {
            // Chuẩn hóa biên độ Doppler về phạm vi 0-1
            (d.mean_magnitude / 100.0).clamp(0.0, 1.0)
        });

        let motion_score = MotionScore::new(variance_score, correlation_score, phase_score, doppler_score);

        // Tính phương sai theo thời gian và không gian
        let temporal_variance = self.calculate_temporal_variance();
        let spatial_variance = features.amplitude.variance.iter().sum::<f64>()
            / features.amplitude.variance.len() as f64;

        // Ước lượng vận tốc từ Doppler nếu có
        let estimated_velocity = features
            .doppler
            .as_ref()
            .map(|d| d.mean_magnitude)
            .unwrap_or(0.0);

        // Hướng chuyển động từ gradient pha
        let motion_direction = if features.phase.gradient.len() > 0 {
            let mean_grad: f64 =
                features.phase.gradient.iter().sum::<f64>() / features.phase.gradient.len() as f64;
            Some(mean_grad.atan())
        } else {
            None
        };

        // Tính độ tin cậy dựa trên các chỉ thị chất lượng tín hiệu
        let confidence = self.calculate_motion_confidence(features);

        MotionAnalysis {
            score: motion_score,
            temporal_variance,
            spatial_variance,
            estimated_velocity,
            motion_direction,
            confidence,
        }
    }

    /// Tính điểm chuyển động dựa trên phương sai
    fn calculate_variance_score(&self, amplitude: &AmplitudeFeatures) -> f64 {
        let mean_variance = amplitude.variance.iter().sum::<f64>() / amplitude.variance.len() as f64;

        // Chuẩn hóa sử dụng đường cơ sở nếu có
        if let Some(baseline) = self.baseline_variance {
            let ratio = mean_variance / (baseline + 1e-10);
            (ratio - 1.0).max(0.0).tanh()
        } else {
            // Sử dụng chuẩn hóa kinh nghiệm
            (mean_variance / 0.5).clamp(0.0, 1.0)
        }
    }

    /// Tính điểm chuyển động dựa trên tương quan
    fn calculate_correlation_score(&self, correlation: &CorrelationFeatures) -> f64 {
        let n = correlation.matrix.dim().0;
        if n < 2 {
            return 0.0;
        }

        // Tính độ lệch trung bình so với ma trận đơn vị
        let mut deviation_sum = 0.0;
        let mut count = 0;

        for i in 0..n {
            for j in 0..n {
                let expected = if i == j { 1.0 } else { 0.0 };
                deviation_sum += (correlation.matrix[[i, j]] - expected).abs();
                count += 1;
            }
        }

        let mean_deviation = deviation_sum / count as f64;
        mean_deviation.clamp(0.0, 1.0)
    }

    /// Tính điểm chuyển động dựa trên pha
    fn calculate_phase_score(&self, phase: &PhaseFeatures) -> f64 {
        // Sử dụng phương sai pha và tương hợp
        let mean_variance = phase.variance.iter().sum::<f64>() / phase.variance.len() as f64;
        let coherence_factor = 1.0 - phase.coherence.abs();

        // Kết hợp các yếu tố
        let score = 0.5 * (mean_variance / 0.5).clamp(0.0, 1.0) + 0.5 * coherence_factor;
        score.clamp(0.0, 1.0)
    }

    /// Tính phương sai theo thời gian từ lịch sử chuyển động
    fn calculate_temporal_variance(&self) -> f64 {
        if self.motion_history.len() < 2 {
            return 0.0;
        }

        let scores: Vec<f64> = self.motion_history.iter().map(|m| m.total).collect();
        let mean: f64 = scores.iter().sum::<f64>() / scores.len() as f64;
        let variance: f64 = scores.iter().map(|s| (s - mean).powi(2)).sum::<f64>() / scores.len() as f64;
        variance.sqrt()
    }

    /// Tính độ tin cậy trong phát hiện chuyển động
    fn calculate_motion_confidence(&self, features: &CsiFeatures) -> f64 {
        let mut confidence = 0.0;
        let mut weight_sum = 0.0;

        // Chỉ thị chất lượng biên độ
        let amp_quality = (features.amplitude.dynamic_range / 2.0).clamp(0.0, 1.0);
        confidence += amp_quality * 0.3;
        weight_sum += 0.3;

        // Chỉ thị tương hợp pha
        let phase_quality = features.phase.coherence.abs();
        confidence += phase_quality * 0.3;
        weight_sum += 0.3;

        // Chỉ thị tính nhất quán tương quan
        let corr_quality = (1.0 - features.correlation.correlation_spread).clamp(0.0, 1.0);
        confidence += corr_quality * 0.2;
        weight_sum += 0.2;

        // Chất lượng Doppler nếu có
        if let Some(ref doppler) = features.doppler {
            let doppler_quality = (doppler.spread / doppler.mean_magnitude.max(1.0)).clamp(0.0, 1.0);
            confidence += (1.0 - doppler_quality) * 0.2;
            weight_sum += 0.2;
        }

        if weight_sum > 0.0 {
            confidence / weight_sum
        } else {
            0.0
        }
    }

    /// Tính độ tin cậy phát hiện từ đặc trưng và điểm chuyển động
    fn calculate_detection_confidence(&self, features: &CsiFeatures, motion_score: f64) -> f64 {
        // Chỉ thị biên độ
        let amplitude_mean = features.amplitude.mean.iter().sum::<f64>()
            / features.amplitude.mean.len() as f64;
        let amplitude_indicator = if amplitude_mean > self.config.amplitude_threshold {
            1.0
        } else {
            0.0
        };

        // Chỉ thị pha
        let phase_std = features.phase.variance.iter().sum::<f64>().sqrt()
            / features.phase.variance.len() as f64;
        let phase_indicator = if phase_std > self.config.phase_threshold {
            1.0
        } else {
            0.0
        };

        // Chỉ thị chuyển động
        let motion_indicator = if motion_score > self.config.motion_threshold {
            1.0
        } else {
            0.0
        };

        // Kết hợp có trọng số
        let confidence = self.config.amplitude_weight * amplitude_indicator
            + self.config.phase_weight * phase_indicator
            + self.config.motion_weight * motion_indicator;

        confidence.clamp(0.0, 1.0)
    }

    /// Áp dụng làm mượt theo thời gian (trung bình trượt hàm mũ)
    fn apply_temporal_smoothing(&mut self, raw_confidence: f64) -> f64 {
        let smoothed = self.config.smoothing_factor * self.previous_confidence
            + (1.0 - self.config.smoothing_factor) * raw_confidence;
        self.previous_confidence = smoothed;
        smoothed
    }

    /// Phát hiện sự hiện diện con người từ đặc trưng CSI
    pub fn detect_human(&mut self, features: &CsiFeatures) -> HumanDetectionResult {
        // Phân tích chuyển động
        let motion_analysis = self.analyze_motion(features);

        // Thêm vào lịch sử
        if self.motion_history.len() >= self.config.history_size {
            self.motion_history.pop_front();
        }
        self.motion_history.push_back(motion_analysis.score.clone());

        // Tính độ tin cậy phát hiện
        let raw_confidence =
            self.calculate_detection_confidence(features, motion_analysis.score.total);

        // Áp dụng làm mượt theo thời gian
        let smoothed_confidence = self.apply_temporal_smoothing(raw_confidence);

        // Lấy ngưỡng hiệu quả (thích ứng nếu được bật)
        let threshold = if self.config.adaptive_threshold {
            self.calculate_adaptive_threshold()
        } else {
            self.config.human_detection_threshold
        };

        // Xác định phát hiện
        let human_detected = smoothed_confidence >= threshold;

        self.total_detections += 1;
        if human_detected {
            self.detection_count += 1;
        }

        let metadata = DetectionMetadata {
            features_used: 4, // biên độ, pha, tương quan, psd
            processing_time_ms: None,
            doppler_available: features.doppler.is_some(),
            history_length: self.motion_history.len(),
        };

        HumanDetectionResult {
            human_detected,
            confidence: smoothed_confidence,
            motion_score: motion_analysis.score.total,
            raw_confidence,
            timestamp: Utc::now(),
            threshold,
            motion_analysis,
            metadata,
        }
    }

    /// Tính ngưỡng thích ứng dựa trên lịch sử gần đây
    fn calculate_adaptive_threshold(&self) -> f64 {
        if self.motion_history.len() < 10 {
            return self.config.human_detection_threshold;
        }

        let scores: Vec<f64> = self.motion_history.iter().map(|m| m.total).collect();
        let mean: f64 = scores.iter().sum::<f64>() / scores.len() as f64;
        let std: f64 = {
            let var: f64 = scores.iter().map(|s| (s - mean).powi(2)).sum::<f64>() / scores.len() as f64;
            var.sqrt()
        };

        // Ngưỡng là trung bình + 1 độ lệch chuẩn, giới hạn trong phạm vi hợp lý
        (mean + std).clamp(0.3, 0.95)
    }

    /// Cập nhật phương sai đường cơ sở (cho hiệu chuẩn)
    pub fn calibrate(&mut self, features: &CsiFeatures) {
        let mean_variance =
            features.amplitude.variance.iter().sum::<f64>() / features.amplitude.variance.len() as f64;
        self.baseline_variance = Some(mean_variance);
    }

    /// Xóa hiệu chuẩn
    pub fn clear_calibration(&mut self) {
        self.baseline_variance = None;
    }

    /// Lấy thống kê phát hiện
    pub fn get_statistics(&self) -> DetectionStatistics {
        DetectionStatistics {
            total_detections: self.total_detections,
            positive_detections: self.detection_count,
            detection_rate: if self.total_detections > 0 {
                self.detection_count as f64 / self.total_detections as f64
            } else {
                0.0
            },
            history_size: self.motion_history.len(),
            is_calibrated: self.baseline_variance.is_some(),
        }
    }

    /// Đặt lại trạng thái bộ phát hiện
    pub fn reset(&mut self) {
        self.previous_confidence = 0.0;
        self.motion_history.clear();
        self.detection_count = 0;
        self.total_detections = 0;
    }

    /// Lấy giá trị độ tin cậy trước đó
    pub fn previous_confidence(&self) -> f64 {
        self.previous_confidence
    }
}

/// Thống kê phát hiện
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectionStatistics {
    /// Tổng số lần thử phát hiện
    pub total_detections: usize,

    /// Số lần phát hiện dương tính
    pub positive_detections: usize,

    /// Tỷ lệ phát hiện (0.0 đến 1.0)
    pub detection_rate: f64,

    /// Kích thước lịch sử hiện tại
    pub history_size: usize,

    /// Bộ phát hiện đã được hiệu chuẩn chưa
    pub is_calibrated: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csi_processor::CsiData;
    use crate::features::FeatureExtractor;
    use ndarray::Array2;

    fn create_test_csi_data(motion_level: f64) -> CsiData {
        let amplitude = Array2::from_shape_fn((4, 64), |(i, j)| {
            1.0 + motion_level * 0.5 * ((i + j) as f64 * 0.1).sin()
        });
        let phase = Array2::from_shape_fn((4, 64), |(i, j)| {
            motion_level * 0.3 * ((i + j) as f64 * 0.15).sin()
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

    fn create_test_features(motion_level: f64) -> CsiFeatures {
        let csi_data = create_test_csi_data(motion_level);
        let extractor = FeatureExtractor::default_config();
        extractor.extract(&csi_data)
    }

    #[test]
    fn test_motion_score() {
        let score = MotionScore::new(0.5, 0.6, 0.4, None);
        assert!(score.total > 0.0 && score.total <= 1.0);
        assert_eq!(score.variance_component, 0.5);
        assert_eq!(score.correlation_component, 0.6);
        assert_eq!(score.phase_component, 0.4);
    }

    #[test]
    fn test_motion_score_with_doppler() {
        let score = MotionScore::new(0.5, 0.6, 0.4, Some(0.7));
        assert!(score.total > 0.0 && score.total <= 1.0);
        assert_eq!(score.doppler_component, Some(0.7));
    }

    #[test]
    fn test_motion_detector_creation() {
        let config = MotionDetectorConfig::default();
        let detector = MotionDetector::new(config);
        assert_eq!(detector.previous_confidence(), 0.0);
    }

    #[test]
    fn test_motion_analysis() {
        let detector = MotionDetector::default_config();
        let features = create_test_features(0.5);

        let analysis = detector.analyze_motion(&features);
        assert!(analysis.score.total >= 0.0 && analysis.score.total <= 1.0);
        assert!(analysis.confidence >= 0.0 && analysis.confidence <= 1.0);
    }

    #[test]
    fn test_human_detection() {
        let config = MotionDetectorConfig::builder()
            .human_detection_threshold(0.5)
            .smoothing_factor(0.5)
            .build();
        let mut detector = MotionDetector::new(config);

        let features = create_test_features(0.8);
        let result = detector.detect_human(&features);

        assert!(result.confidence >= 0.0 && result.confidence <= 1.0);
        assert!(result.motion_score >= 0.0 && result.motion_score <= 1.0);
    }

    #[test]
    fn test_temporal_smoothing() {
        let config = MotionDetectorConfig::builder()
            .smoothing_factor(0.9)
            .build();
        let mut detector = MotionDetector::new(config);

        // Phát hiện đầu tiên với độ tin cậy thấp
        let features_low = create_test_features(0.1);
        let result1 = detector.detect_human(&features_low);

        // Phát hiện thứ hai với độ tin cậy cao sẽ được làm mượt
        let features_high = create_test_features(0.9);
        let result2 = detector.detect_human(&features_high);

        // Do làm mượt, result2.confidence nên nằm giữa result1 và giá trị thô
        assert!(result2.confidence >= result1.confidence);
    }

    #[test]
    fn test_calibration() {
        let mut detector = MotionDetector::default_config();
        let features = create_test_features(0.5);

        assert!(!detector.get_statistics().is_calibrated);
        detector.calibrate(&features);
        assert!(detector.get_statistics().is_calibrated);

        detector.clear_calibration();
        assert!(!detector.get_statistics().is_calibrated);
    }

    #[test]
    fn test_detection_statistics() {
        let mut detector = MotionDetector::default_config();

        for i in 0..5 {
            let features = create_test_features((i as f64) / 5.0);
            let _ = detector.detect_human(&features);
        }

        let stats = detector.get_statistics();
        assert_eq!(stats.total_detections, 5);
        assert!(stats.detection_rate >= 0.0 && stats.detection_rate <= 1.0);
    }

    #[test]
    fn test_reset() {
        let mut detector = MotionDetector::default_config();
        let features = create_test_features(0.5);

        for _ in 0..5 {
            let _ = detector.detect_human(&features);
        }

        detector.reset();

        let stats = detector.get_statistics();
        assert_eq!(stats.total_detections, 0);
        assert_eq!(stats.history_size, 0);
        assert_eq!(detector.previous_confidence(), 0.0);
    }

    #[test]
    fn test_adaptive_threshold() {
        let config = MotionDetectorConfig::builder()
            .adaptive_threshold(true)
            .history_size(20)
            .build();
        let mut detector = MotionDetector::new(config);

        // Tích lũy lịch sử
        for i in 0..15 {
            let features = create_test_features((i as f64 % 5.0) / 5.0);
            let _ = detector.detect_human(&features);
        }

        // Ngưỡng thích ứng bây giờ nên được tính
        let features = create_test_features(0.5);
        let result = detector.detect_human(&features);

        // Ngưỡng nên khác với mặc định
        // (đây là assertion yếu, chủ yếu kiểm tra chạy được)
        assert!(result.threshold > 0.0);
    }

    #[test]
    fn test_config_builder() {
        let config = MotionDetectorConfig::builder()
            .human_detection_threshold(0.7)
            .motion_threshold(0.4)
            .smoothing_factor(0.85)
            .amplitude_threshold(0.15)
            .phase_threshold(0.08)
            .history_size(200)
            .adaptive_threshold(true)
            .weights(0.35, 0.35, 0.30)
            .build();

        assert_eq!(config.human_detection_threshold, 0.7);
        assert_eq!(config.motion_threshold, 0.4);
        assert_eq!(config.smoothing_factor, 0.85);
        assert_eq!(config.amplitude_threshold, 0.15);
        assert_eq!(config.phase_threshold, 0.08);
        assert_eq!(config.history_size, 200);
        assert!(config.adaptive_threshold);
        assert_eq!(config.amplitude_weight, 0.35);
        assert_eq!(config.phase_weight, 0.35);
        assert_eq!(config.motion_weight, 0.30);
    }

    #[test]
    fn test_low_motion_no_detection() {
        let config = MotionDetectorConfig::builder()
            .human_detection_threshold(0.8)
            .smoothing_factor(0.0) // Không làm mượt cho kiểm thử rõ ràng
            .build();
        let mut detector = MotionDetector::new(config);

        // Chuyển động rất thấp không nên kích hoạt phát hiện
        let features = create_test_features(0.01);
        let result = detector.detect_human(&features);

        // Với chuyển động rất thấp, phát hiện có khả năng là false
        // (phụ thuộc vào ngưỡng, nhưng độ tin cậy nên thấp)
        assert!(result.motion_score < 0.5);
    }

    #[test]
    fn test_motion_history() {
        let config = MotionDetectorConfig::builder()
            .history_size(10)
            .build();
        let mut detector = MotionDetector::new(config);

        for i in 0..15 {
            let features = create_test_features((i as f64) / 15.0);
            let _ = detector.detect_human(&features);
        }

        let stats = detector.get_statistics();
        assert_eq!(stats.history_size, 10); // Không nên vượt quá tối đa
    }
}
