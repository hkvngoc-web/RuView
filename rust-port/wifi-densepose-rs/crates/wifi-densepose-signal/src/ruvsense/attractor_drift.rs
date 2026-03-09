//! Phát hiện trôi theo chiều dọc nâng cao sử dụng `midstreamer-attractor`.
//!
//! Mở rộng phát hiện trôi thống kê Welford từ `longitudinal.rs`
//! với phân tích hút tử không gian pha cung cấp bởi crate
//! `midstreamer-attractor` (ADR-032a Phần 6.4).
//!
//! # Cải tiến so với phát hiện trôi cơ bản
//!
//! - **Nhúng không gian pha**: Phát hiện thay đổi chế độ vô hình với
//!   phân tích điểm z đơn giản (ví dụ: dáng đi chuyển từ chu kỳ giới hạn
//!   sang hút tử lạ = phát triển mất ổn định)
//! - **Số mũ Lyapunov**: Định lượng độ nhạy với điều kiện ban đầu,
//!   bắt chuyển tiếp hỗn loạn trong mẫu hô hấp
//! - **Phân loại hút tử**: Tự động phân loại chuỗi thời gian sinh lý
//!   thành hút tử điểm (ổn định), chu kỳ giới hạn (tuần hoàn),
//!   hoặc hút tử lạ (hỗn loạn)
//!
//! # Tài liệu tham khảo
//! - ADR-030 Tier 4: Phát hiện trôi sinh trắc học theo chiều dọc
//! - ADR-032a Phần 6.4: Tích hợp midstreamer-attractor
//! - Takens, F. (1981). "Detecting strange attractors in turbulence."

use midstreamer_attractor::{
    AttractorAnalyzer, AttractorType, PhasePoint,
};

use super::longitudinal::DriftMetric;

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho phân tích trôi dựa trên hút tử.
#[derive(Debug, Clone)]
pub struct AttractorDriftConfig {
    /// Chiều nhúng cho tái tạo không gian pha (định lý Takens).
    /// Mặc định: 3 (đủ cho hầu hết tín hiệu sinh lý).
    pub embedding_dim: usize,
    /// Độ trễ thời gian cho nhúng không gian pha (theo bước quan sát).
    /// Mặc định: 1 (các quan sát liên tiếp).
    pub time_delay: usize,
    /// Số quan sát tối thiểu cần có trước khi phân tích có ý nghĩa.
    /// Mặc định: 30 (khoảng 1 tháng quan sát hàng ngày).
    pub min_observations: usize,
    /// Ngưỡng số mũ Lyapunov cho phát hiện hỗn loạn.
    /// Mặc định: 0.01.
    pub lyapunov_threshold: f64,
    /// Chiều dài quỹ đạo tối đa cho bộ phân tích.
    /// Mặc định: 10000.
    pub max_trajectory_length: usize,
}

impl Default for AttractorDriftConfig {
    fn default() -> Self {
        Self {
            embedding_dim: 3,
            time_delay: 1,
            min_observations: 30,
            lyapunov_threshold: 0.01,
            max_trajectory_length: 10000,
        }
    }
}

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ phân tích trôi dựa trên hút tử.
#[derive(Debug, thiserror::Error)]
pub enum AttractorDriftError {
    /// Không đủ quan sát cho nhúng không gian pha.
    #[error("Không đủ quan sát: cần >= {needed}, có {have}")]
    InsufficientData { needed: usize, have: usize },

    /// Chỉ số không có quan sát nào được ghi nhận.
    #[error("Không có quan sát cho chỉ số: {0}")]
    NoObservations(String),

    /// Chiều nhúng không gian pha không hợp lệ.
    #[error("Chiều nhúng không hợp lệ: {dim} (phải >= 2)")]
    InvalidEmbeddingDim { dim: usize },

    /// Lỗi thư viện phân tích hút tử.
    #[error("Phân tích hút tử thất bại: {0}")]
    AnalysisFailed(String),
}

// ---------------------------------------------------------------------------
// Kết quả phân loại hút tử
// ---------------------------------------------------------------------------

/// Phân loại hút tử của chuỗi thời gian sinh lý.
#[derive(Debug, Clone, PartialEq)]
pub enum BiophysicalAttractor {
    /// Hút tử điểm: chỉ số đã hội tụ về giá trị ổn định.
    Stable { center: f64 },
    /// Chu kỳ giới hạn: chỉ số dao động tuần hoàn.
    Periodic { lyapunov_max: f64 },
    /// Hút tử lạ: chỉ số thể hiện động lực hỗn loạn.
    Chaotic { lyapunov_exponent: f64 },
    /// Đang chuyển tiếp giữa các loại hút tử.
    Transitioning {
        from: Box<BiophysicalAttractor>,
        to: Box<BiophysicalAttractor>,
    },
    /// Không đủ dữ liệu để phân loại.
    Unknown,
}

impl BiophysicalAttractor {
    /// Loại hút tử này có đáng chú ý giám sát hay không.
    pub fn is_concerning(&self) -> bool {
        matches!(
            self,
            BiophysicalAttractor::Chaotic { .. } | BiophysicalAttractor::Transitioning { .. }
        )
    }

    /// Nhãn dễ đọc cho báo cáo.
    pub fn label(&self) -> &'static str {
        match self {
            BiophysicalAttractor::Stable { .. } => "stable",
            BiophysicalAttractor::Periodic { .. } => "periodic",
            BiophysicalAttractor::Chaotic { .. } => "chaotic",
            BiophysicalAttractor::Transitioning { .. } => "transitioning",
            BiophysicalAttractor::Unknown => "unknown",
        }
    }
}

// ---------------------------------------------------------------------------
// Báo cáo trôi hút tử
// ---------------------------------------------------------------------------

/// Báo cáo từ phân tích trôi dựa trên hút tử.
#[derive(Debug, Clone)]
pub struct AttractorDriftReport {
    /// Người mà báo cáo này liên quan đến.
    pub person_id: u64,
    /// Chỉ số sinh lý nào được phân tích.
    pub metric: DriftMetric,
    /// Loại hút tử đã phân loại.
    pub attractor: BiophysicalAttractor,
    /// Loại hút tử có thay đổi so với phân tích trước hay không.
    pub regime_changed: bool,
    /// Số quan sát được sử dụng trong phân tích này.
    pub observation_count: usize,
    /// Dấu thời gian của phân tích (micro giây).
    pub timestamp_us: u64,
}

// ---------------------------------------------------------------------------
// Bộ đệm quan sát cho mỗi chỉ số
// ---------------------------------------------------------------------------

/// Bộ đệm chuỗi thời gian cho một chỉ số sinh lý đơn lẻ.
#[derive(Debug, Clone)]
struct MetricBuffer {
    /// Loại chỉ số.
    metric: DriftMetric,
    /// Các giá trị quan sát (gần nhất ở cuối).
    values: Vec<f64>,
    /// Kích thước bộ đệm tối đa.
    max_size: usize,
    /// Nhãn hút tử đã phân loại lần cuối.
    last_label: String,
}

impl MetricBuffer {
    /// Tạo bộ đệm mới.
    fn new(metric: DriftMetric, max_size: usize) -> Self {
        Self {
            metric,
            values: Vec::new(),
            max_size,
            last_label: "unknown".to_string(),
        }
    }

    /// Thêm một quan sát.
    fn push(&mut self, value: f64) {
        if self.values.len() >= self.max_size {
            self.values.remove(0);
        }
        self.values.push(value);
    }

    /// Số quan sát.
    fn count(&self) -> usize {
        self.values.len()
    }
}

// ---------------------------------------------------------------------------
// Bộ phân tích trôi hút tử
// ---------------------------------------------------------------------------

/// Bộ phân tích trôi dựa trên hút tử cho giám sát sinh lý theo chiều dọc.
///
/// Sử dụng tái tạo không gian pha (định lý nhúng Takens) và
/// `midstreamer-attractor` để phân loại chế độ động lực của mỗi
/// chỉ số sinh lý. Phát hiện thay đổi chế độ xảy ra trước
/// trôi chỉ số đơn giản.
pub struct AttractorDriftAnalyzer {
    /// Cấu hình.
    config: AttractorDriftConfig,
    /// ID người đang được giám sát.
    person_id: u64,
    /// Bộ đệm quan sát cho mỗi chỉ số.
    buffers: Vec<MetricBuffer>,
    /// Tổng số phân tích đã thực hiện.
    analysis_count: u64,
}

// Debug thủ công vì AttractorAnalyzer không derive Debug
impl std::fmt::Debug for AttractorDriftAnalyzer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AttractorDriftAnalyzer")
            .field("person_id", &self.person_id)
            .field("analysis_count", &self.analysis_count)
            .finish()
    }
}

impl AttractorDriftAnalyzer {
    /// Tạo bộ phân tích trôi hút tử mới cho một người.
    pub fn new(
        person_id: u64,
        config: AttractorDriftConfig,
    ) -> Result<Self, AttractorDriftError> {
        if config.embedding_dim < 2 {
            return Err(AttractorDriftError::InvalidEmbeddingDim {
                dim: config.embedding_dim,
            });
        }

        let buffers = DriftMetric::all()
            .iter()
            .map(|&m| MetricBuffer::new(m, 365)) // 1 năm quan sát hàng ngày
            .collect();

        Ok(Self {
            config,
            person_id,
            buffers,
            analysis_count: 0,
        })
    }

    /// Thêm một quan sát cho một chỉ số cụ thể.
    pub fn add_observation(&mut self, metric: DriftMetric, value: f64) {
        if let Some(buf) = self.buffers.iter_mut().find(|b| b.metric == metric) {
            buf.push(value);
        }
    }

    /// Thực hiện phân tích hút tử trên một chỉ số cụ thể.
    ///
    /// Tái tạo không gian pha sử dụng nhúng Takens và
    /// phân loại loại hút tử bằng `midstreamer-attractor`.
    pub fn analyze(
        &mut self,
        metric: DriftMetric,
        timestamp_us: u64,
    ) -> Result<AttractorDriftReport, AttractorDriftError> {
        let buf_idx = self
            .buffers
            .iter()
            .position(|b| b.metric == metric)
            .ok_or_else(|| AttractorDriftError::NoObservations(metric.name().into()))?;

        let count = self.buffers[buf_idx].count();
        let min_needed = self.config.min_observations;
        if count < min_needed {
            return Err(AttractorDriftError::InsufficientData {
                needed: min_needed,
                have: count,
            });
        }

        // Xây dựng quỹ đạo không gian pha sử dụng nhúng Takens
        // và nạp vào AttractorAnalyzer mới
        let dim = self.config.embedding_dim;
        let delay = self.config.time_delay;
        let values = &self.buffers[buf_idx].values;
        let n_points = values.len().saturating_sub((dim - 1) * delay);

        let mut analyzer = AttractorAnalyzer::new(dim, self.config.max_trajectory_length);

        for i in 0..n_points {
            let coords: Vec<f64> = (0..dim).map(|d| values[i + d * delay]).collect();
            let point = PhasePoint::new(coords, i as u64);
            let _ = analyzer.add_point(point);
        }

        // Phân tích quỹ đạo
        let attractor = match analyzer.analyze() {
            Ok(info) => {
                let max_lyap = info
                    .max_lyapunov_exponent()
                    .unwrap_or(0.0);

                match info.attractor_type {
                    AttractorType::PointAttractor => {
                        // Tính tâm bằng trung bình vài giá trị cuối
                        let recent = &values[values.len().saturating_sub(10)..];
                        let center = recent.iter().sum::<f64>() / recent.len() as f64;
                        BiophysicalAttractor::Stable { center }
                    }
                    AttractorType::LimitCycle => BiophysicalAttractor::Periodic {
                        lyapunov_max: max_lyap,
                    },
                    AttractorType::StrangeAttractor => BiophysicalAttractor::Chaotic {
                        lyapunov_exponent: max_lyap,
                    },
                    _ => BiophysicalAttractor::Unknown,
                }
            }
            Err(_) => BiophysicalAttractor::Unknown,
        };

        // Kiểm tra thay đổi chế độ
        let label = attractor.label().to_string();
        let regime_changed = label != self.buffers[buf_idx].last_label;
        self.buffers[buf_idx].last_label = label;

        self.analysis_count += 1;

        Ok(AttractorDriftReport {
            person_id: self.person_id,
            metric,
            attractor,
            regime_changed,
            observation_count: count,
            timestamp_us,
        })
    }

    /// Số quan sát cho một chỉ số cụ thể.
    pub fn observation_count(&self, metric: DriftMetric) -> usize {
        self.buffers
            .iter()
            .find(|b| b.metric == metric)
            .map_or(0, |b| b.count())
    }

    /// Tổng số phân tích đã thực hiện.
    pub fn analysis_count(&self) -> u64 {
        self.analysis_count
    }

    /// ID người đang được giám sát.
    pub fn person_id(&self) -> u64 {
        self.person_id
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn default_analyzer() -> AttractorDriftAnalyzer {
        AttractorDriftAnalyzer::new(42, AttractorDriftConfig::default()).unwrap()
    }

    #[test]
    fn test_analyzer_creation() {
        let a = default_analyzer();
        assert_eq!(a.person_id(), 42);
        assert_eq!(a.analysis_count(), 0);
    }

    #[test]
    fn test_analyzer_invalid_embedding_dim() {
        let config = AttractorDriftConfig {
            embedding_dim: 1,
            ..Default::default()
        };
        assert!(matches!(
            AttractorDriftAnalyzer::new(1, config),
            Err(AttractorDriftError::InvalidEmbeddingDim { .. })
        ));
    }

    #[test]
    fn test_add_observation() {
        let mut a = default_analyzer();
        a.add_observation(DriftMetric::GaitSymmetry, 0.1);
        a.add_observation(DriftMetric::GaitSymmetry, 0.11);
        assert_eq!(a.observation_count(DriftMetric::GaitSymmetry), 2);
    }

    #[test]
    fn test_analyze_insufficient_data() {
        let mut a = default_analyzer();
        for i in 0..10 {
            a.add_observation(DriftMetric::GaitSymmetry, 0.1 + i as f64 * 0.001);
        }
        let result = a.analyze(DriftMetric::GaitSymmetry, 0);
        assert!(matches!(
            result,
            Err(AttractorDriftError::InsufficientData { .. })
        ));
    }

    #[test]
    fn test_analyze_stable_signal() {
        let mut a = AttractorDriftAnalyzer::new(
            1,
            AttractorDriftConfig {
                min_observations: 10,
                ..Default::default()
            },
        )
        .unwrap();

        // Tín hiệu ổn định: hằng số với nhiễu nhỏ
        for i in 0..150 {
            let noise = 0.001 * (i as f64 % 3.0 - 1.0);
            a.add_observation(DriftMetric::GaitSymmetry, 0.1 + noise);
        }

        let report = a.analyze(DriftMetric::GaitSymmetry, 1000).unwrap();
        assert_eq!(report.person_id, 1);
        assert_eq!(report.metric, DriftMetric::GaitSymmetry);
        assert_eq!(report.observation_count, 150);
        assert_eq!(a.analysis_count(), 1);
    }

    #[test]
    fn test_analyze_periodic_signal() {
        let mut a = AttractorDriftAnalyzer::new(
            2,
            AttractorDriftConfig {
                min_observations: 10,
                ..Default::default()
            },
        )
        .unwrap();

        // Tín hiệu tuần hoàn: hình sin với đủ điểm cho bộ phân tích
        for i in 0..200 {
            let value = 0.5 + 0.3 * (i as f64 * std::f64::consts::PI / 7.0).sin();
            a.add_observation(DriftMetric::BreathingRegularity, value);
        }

        let report = a.analyze(DriftMetric::BreathingRegularity, 2000).unwrap();
        assert_eq!(report.metric, DriftMetric::BreathingRegularity);
        assert!(!report.attractor.label().is_empty());
    }

    #[test]
    fn test_regime_change_detection() {
        let mut a = AttractorDriftAnalyzer::new(
            3,
            AttractorDriftConfig {
                min_observations: 10,
                ..Default::default()
            },
        )
        .unwrap();

        // Giai đoạn 1: tín hiệu ổn định (đủ cho bộ phân tích: >= 100 điểm)
        for i in 0..150 {
            let noise = 0.001 * (i as f64 % 3.0 - 1.0);
            a.add_observation(DriftMetric::StabilityIndex, 0.9 + noise);
        }
        let _report1 = a.analyze(DriftMetric::StabilityIndex, 1000).unwrap();

        // Giai đoạn 2: thêm tín hiệu dạng hỗn loạn
        for i in 150..300 {
            let value = 0.5 + 0.4 * ((i as f64 * 1.7).sin() * (i as f64 * 0.3).cos());
            a.add_observation(DriftMetric::StabilityIndex, value);
        }
        let _report2 = a.analyze(DriftMetric::StabilityIndex, 2000).unwrap();
        assert!(a.analysis_count() >= 2);
    }

    #[test]
    fn test_biophysical_attractor_labels() {
        assert_eq!(
            BiophysicalAttractor::Stable { center: 0.1 }.label(),
            "stable"
        );
        assert_eq!(
            BiophysicalAttractor::Periodic { lyapunov_max: 0.0 }.label(),
            "periodic"
        );
        assert_eq!(
            BiophysicalAttractor::Chaotic {
                lyapunov_exponent: 0.05,
            }
            .label(),
            "chaotic"
        );
        assert_eq!(BiophysicalAttractor::Unknown.label(), "unknown");
    }

    #[test]
    fn test_biophysical_attractor_is_concerning() {
        assert!(!BiophysicalAttractor::Stable { center: 0.1 }.is_concerning());
        assert!(!BiophysicalAttractor::Periodic { lyapunov_max: 0.0 }.is_concerning());
        assert!(BiophysicalAttractor::Chaotic {
            lyapunov_exponent: 0.05,
        }
        .is_concerning());
        assert!(!BiophysicalAttractor::Unknown.is_concerning());
    }

    #[test]
    fn test_default_config() {
        let cfg = AttractorDriftConfig::default();
        assert_eq!(cfg.embedding_dim, 3);
        assert_eq!(cfg.time_delay, 1);
        assert_eq!(cfg.min_observations, 30);
        assert!((cfg.lyapunov_threshold - 0.01).abs() < f64::EPSILON);
    }

    #[test]
    fn test_metric_buffer_eviction() {
        let mut buf = MetricBuffer::new(DriftMetric::GaitSymmetry, 5);
        for i in 0..10 {
            buf.push(i as f64);
        }
        assert_eq!(buf.count(), 5);
        assert!((buf.values[0] - 5.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_all_metrics_have_buffers() {
        let a = default_analyzer();
        for metric in DriftMetric::all() {
            assert_eq!(a.observation_count(*metric), 0);
        }
    }

    #[test]
    fn test_transitioning_attractor() {
        let t = BiophysicalAttractor::Transitioning {
            from: Box::new(BiophysicalAttractor::Stable { center: 0.1 }),
            to: Box::new(BiophysicalAttractor::Chaotic {
                lyapunov_exponent: 0.05,
            }),
        };
        assert!(t.is_concerning());
        assert_eq!(t.label(), "transitioning");
    }

    #[test]
    fn test_error_display() {
        let err = AttractorDriftError::InsufficientData {
            needed: 30,
            have: 10,
        };
        assert!(format!("{}", err).contains("30"));
        assert!(format!("{}", err).contains("10"));

        let err = AttractorDriftError::NoObservations("gait_symmetry".into());
        assert!(format!("{}", err).contains("gait_symmetry"));
    }

    #[test]
    fn test_debug_impl() {
        let a = default_analyzer();
        let dbg = format!("{:?}", a);
        assert!(dbg.contains("AttractorDriftAnalyzer"));
    }
}
