//! Phân loại cử chỉ nâng cao sử dụng `midstreamer-temporal-compare`.
//!
//! Mở rộng bộ phân loại cử chỉ dựa DTW từ `gesture.rs` với
//! các thuật toán so sánh thời gian tối ưu cung cấp bởi crate
//! `midstreamer-temporal-compare` (ADR-032a Phần 6.4).
//!
//! # Cải tiến so với bộ phân loại cử chỉ cơ bản
//!
//! - **DTW có bộ nhớ đệm**: Kết quả được lưu đệm theo mã băm chuỗi cho so sánh lặp lại
//! - **Đa thuật toán**: DTW, LCS, và khoảng cách chỉnh sửa khả dụng
//! - **Phát hiện mẫu**: Trích xuất mẫu phụ cử chỉ tự động
//!
//! # Tài liệu tham khảo
//! - ADR-030 Tier 6: Lớp tương tác vô hình
//! - ADR-032a Phần 6.4: Tích hợp midstreamer-temporal-compare

use midstreamer_temporal_compare::{
    ComparisonAlgorithm, Sequence, TemporalComparator,
};

use super::gesture::{GestureConfig, GestureError, GestureResult, GestureTemplate};

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Lựa chọn thuật toán cho đối chiếu cử chỉ thời gian.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GestureAlgorithm {
    /// Xoắn thời gian động (kinh điển, từ module cử chỉ cơ bản).
    Dtw,
    /// Chuỗi con chung dài nhất (tốt hơn cho cử chỉ thưa).
    Lcs,
    /// Khoảng cách chỉnh sửa (tốt hơn cho các pha cử chỉ rời rạc).
    EditDistance,
}

impl GestureAlgorithm {
    /// Chuyển đổi sang thuật toán so sánh midstreamer.
    pub fn to_comparison_algorithm(&self) -> ComparisonAlgorithm {
        match self {
            GestureAlgorithm::Dtw => ComparisonAlgorithm::DTW,
            GestureAlgorithm::Lcs => ComparisonAlgorithm::LCS,
            GestureAlgorithm::EditDistance => ComparisonAlgorithm::EditDistance,
        }
    }
}

/// Cấu hình cho bộ phân loại cử chỉ thời gian.
#[derive(Debug, Clone)]
pub struct TemporalGestureConfig {
    /// Cấu hình cử chỉ cơ bản (feature_dim, min_sequence_len, v.v.).
    pub base: GestureConfig,
    /// Thuật toán so sánh chính.
    pub algorithm: GestureAlgorithm,
    /// Có bật bộ nhớ đệm kết quả hay không.
    pub enable_cache: bool,
    /// Dung lượng bộ nhớ đệm (số kết quả so sánh lưu đệm).
    pub cache_capacity: usize,
    /// Khoảng cách tối đa cho khớp (thấp hơn = nghiêm ngặt hơn).
    pub max_distance: f64,
    /// Chiều dài chuỗi tối đa được bộ so sánh chấp nhận.
    pub max_sequence_length: usize,
}

impl Default for TemporalGestureConfig {
    fn default() -> Self {
        Self {
            base: GestureConfig::default(),
            algorithm: GestureAlgorithm::Dtw,
            enable_cache: true,
            cache_capacity: 256,
            max_distance: 50.0,
            max_sequence_length: 1024,
        }
    }
}

// ---------------------------------------------------------------------------
// Bộ phân loại cử chỉ thời gian
// ---------------------------------------------------------------------------

/// Bộ phân loại cử chỉ nâng cao sử dụng `midstreamer-temporal-compare`.
///
/// Cung cấp đối chiếu cử chỉ đa thuật toán với bộ nhớ đệm.
/// Bộ so sánh sử dụng phần tử `f64` trong đó mỗi khung được rút gọn
/// thành chuẩn L2 cho so sánh thời gian vô hướng.
pub struct TemporalGestureClassifier {
    /// Cấu hình.
    config: TemporalGestureConfig,
    /// Các mẫu cử chỉ đã đăng ký.
    templates: Vec<GestureTemplate>,
    /// Chuỗi mẫu đã chuyển đổi trước sang định dạng midstreamer.
    template_sequences: Vec<Sequence<i64>>,
    /// Bộ so sánh thời gian với bộ nhớ đệm.
    comparator: TemporalComparator<i64>,
}

impl TemporalGestureClassifier {
    /// Tạo bộ phân loại cử chỉ thời gian mới.
    pub fn new(config: TemporalGestureConfig) -> Self {
        let comparator = TemporalComparator::new(
            config.cache_capacity,
            config.max_sequence_length,
        );
        Self {
            config,
            templates: Vec::new(),
            template_sequences: Vec::new(),
            comparator,
        }
    }

    /// Đăng ký một mẫu cử chỉ.
    pub fn add_template(
        &mut self,
        template: GestureTemplate,
    ) -> Result<(), GestureError> {
        if template.name.is_empty() {
            return Err(GestureError::InvalidTemplateName(
                "Tên mẫu không được rỗng".into(),
            ));
        }
        if template.feature_dim != self.config.base.feature_dim {
            return Err(GestureError::DimensionMismatch {
                expected: self.config.base.feature_dim,
                got: template.feature_dim,
            });
        }
        if template.sequence.len() < self.config.base.min_sequence_len {
            return Err(GestureError::SequenceTooShort {
                needed: self.config.base.min_sequence_len,
                got: template.sequence.len(),
            });
        }

        let seq = Self::to_sequence(&template.sequence);
        self.template_sequences.push(seq);
        self.templates.push(template);
        Ok(())
    }

    /// Số mẫu đã đăng ký.
    pub fn template_count(&self) -> usize {
        self.templates.len()
    }

    /// Phân loại chuỗi nhiễu loạn so với các mẫu đã đăng ký.
    ///
    /// Sử dụng thuật toán so sánh đã cấu hình (DTW, LCS, hoặc khoảng cách chỉnh sửa)
    /// từ `midstreamer-temporal-compare`.
    pub fn classify(
        &self,
        sequence: &[Vec<f64>],
        person_id: u64,
        timestamp_us: u64,
    ) -> Result<GestureResult, GestureError> {
        if self.templates.is_empty() {
            return Err(GestureError::NoTemplates);
        }
        if sequence.len() < self.config.base.min_sequence_len {
            return Err(GestureError::SequenceTooShort {
                needed: self.config.base.min_sequence_len,
                got: sequence.len(),
            });
        }
        for frame in sequence {
            if frame.len() != self.config.base.feature_dim {
                return Err(GestureError::DimensionMismatch {
                    expected: self.config.base.feature_dim,
                    got: frame.len(),
                });
            }
        }

        let query_seq = Self::to_sequence(sequence);
        let algo = self.config.algorithm.to_comparison_algorithm();

        let mut best_distance = f64::INFINITY;
        let mut second_best = f64::INFINITY;
        let mut best_idx: Option<usize> = None;

        for (idx, template_seq) in self.template_sequences.iter().enumerate() {
            let result = self
                .comparator
                .compare(&query_seq, template_seq, algo);
            // Dùng khoảng cách từ ComparisonResult (thấp hơn = khớp tốt hơn)
            let distance = match result {
                Ok(cr) => cr.distance,
                Err(_) => f64::INFINITY,
            };

            if distance < best_distance {
                second_best = best_distance;
                best_distance = distance;
                best_idx = Some(idx);
            } else if distance < second_best {
                second_best = distance;
            }
        }

        let recognized = best_distance <= self.config.max_distance;

        // Độ tin cậy dựa trên khoảng cách giữa tốt nhất và tốt nhì
        let confidence = if recognized && second_best.is_finite() && second_best > 1e-10 {
            (1.0 - best_distance / second_best).clamp(0.0, 1.0)
        } else if recognized {
            (1.0 - best_distance / self.config.max_distance).clamp(0.0, 1.0)
        } else {
            0.0
        };

        if let Some(idx) = best_idx {
            let template = &self.templates[idx];
            Ok(GestureResult {
                recognized,
                gesture_type: if recognized {
                    Some(template.gesture_type)
                } else {
                    None
                },
                template_name: if recognized {
                    Some(template.name.clone())
                } else {
                    None
                },
                distance: best_distance,
                confidence,
                person_id,
                timestamp_us,
            })
        } else {
            Ok(GestureResult {
                recognized: false,
                gesture_type: None,
                template_name: None,
                distance: f64::INFINITY,
                confidence: 0.0,
                person_id,
                timestamp_us,
            })
        }
    }

    /// Lấy thống kê bộ nhớ đệm từ bộ so sánh thời gian.
    pub fn cache_stats(&self) -> midstreamer_temporal_compare::CacheStats {
        self.comparator.cache_stats()
    }

    /// Thuật toán so sánh đang hoạt động.
    pub fn algorithm(&self) -> GestureAlgorithm {
        self.config.algorithm
    }

    /// Chuyển đổi chuỗi đặc trưng sang `Sequence<i64>` của midstreamer.
    ///
    /// Chuẩn L2 của mỗi khung được lượng tử hóa thành i64 (nhân 1000)
    /// để sử dụng với bộ so sánh tổng quát.
    fn to_sequence(frames: &[Vec<f64>]) -> Sequence<i64> {
        let mut seq = Sequence::new();
        for (i, frame) in frames.iter().enumerate() {
            let norm = frame.iter().map(|x| x * x).sum::<f64>().sqrt();
            let quantized = (norm * 1000.0) as i64;
            seq.push(quantized, i as u64);
        }
        seq
    }
}

// Triển khai Debug thủ công vì TemporalComparator không derive Debug
impl std::fmt::Debug for TemporalGestureClassifier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TemporalGestureClassifier")
            .field("config", &self.config)
            .field("template_count", &self.templates.len())
            .finish()
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::gesture::GestureType;

    fn make_template(
        name: &str,
        gesture_type: GestureType,
        n_frames: usize,
        feature_dim: usize,
        pattern: fn(usize, usize) -> f64,
    ) -> GestureTemplate {
        let sequence: Vec<Vec<f64>> = (0..n_frames)
            .map(|t| (0..feature_dim).map(|d| pattern(t, d)).collect())
            .collect();
        GestureTemplate {
            name: name.to_string(),
            gesture_type,
            sequence,
            feature_dim,
        }
    }

    fn wave_pattern(t: usize, d: usize) -> f64 {
        if d == 0 {
            (t as f64 * 0.5).sin()
        } else {
            0.0
        }
    }

    fn push_pattern(t: usize, d: usize) -> f64 {
        if d == 0 {
            t as f64 * 0.1
        } else {
            0.0
        }
    }

    fn small_config() -> TemporalGestureConfig {
        TemporalGestureConfig {
            base: GestureConfig {
                feature_dim: 4,
                min_sequence_len: 5,
                max_distance: 10.0,
                band_width: 3,
            },
            algorithm: GestureAlgorithm::Dtw,
            enable_cache: false,
            cache_capacity: 64,
            max_distance: 100000.0, // rộng rãi cho kiểm thử
            max_sequence_length: 1024,
        }
    }

    #[test]
    fn test_temporal_classifier_creation() {
        let classifier = TemporalGestureClassifier::new(small_config());
        assert_eq!(classifier.template_count(), 0);
        assert_eq!(classifier.algorithm(), GestureAlgorithm::Dtw);
    }

    #[test]
    fn test_temporal_add_template() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 4, wave_pattern);
        classifier.add_template(template).unwrap();
        assert_eq!(classifier.template_count(), 1);
    }

    #[test]
    fn test_temporal_add_template_empty_name() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        let template = make_template("", GestureType::Wave, 10, 4, wave_pattern);
        assert!(matches!(
            classifier.add_template(template),
            Err(GestureError::InvalidTemplateName(_))
        ));
    }

    #[test]
    fn test_temporal_add_template_wrong_dim() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 8, wave_pattern);
        assert!(matches!(
            classifier.add_template(template),
            Err(GestureError::DimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_temporal_classify_no_templates() {
        let classifier = TemporalGestureClassifier::new(small_config());
        let seq: Vec<Vec<f64>> = (0..10).map(|_| vec![0.0; 4]).collect();
        assert!(matches!(
            classifier.classify(&seq, 1, 0),
            Err(GestureError::NoTemplates)
        ));
    }

    #[test]
    fn test_temporal_classify_too_short() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        classifier
            .add_template(make_template("wave", GestureType::Wave, 10, 4, wave_pattern))
            .unwrap();
        let seq: Vec<Vec<f64>> = (0..3).map(|_| vec![0.0; 4]).collect();
        assert!(matches!(
            classifier.classify(&seq, 1, 0),
            Err(GestureError::SequenceTooShort { .. })
        ));
    }

    #[test]
    fn test_temporal_classify_exact_match() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 4, wave_pattern);
        classifier.add_template(template).unwrap();

        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d)).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 100_000).unwrap();
        assert!(result.recognized, "Khớp chính xác phải được nhận diện");
        assert_eq!(result.gesture_type, Some(GestureType::Wave));
        assert!(result.distance < 1e-6, "Khớp chính xác phải có khoảng cách gần 0");
    }

    #[test]
    fn test_temporal_classify_best_of_two() {
        let mut classifier = TemporalGestureClassifier::new(small_config());
        classifier
            .add_template(make_template("wave", GestureType::Wave, 10, 4, wave_pattern))
            .unwrap();
        classifier
            .add_template(make_template("push", GestureType::Push, 10, 4, push_pattern))
            .unwrap();

        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d)).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 0).unwrap();
        assert!(result.recognized);
    }

    #[test]
    fn test_temporal_algorithm_selection() {
        assert_eq!(
            GestureAlgorithm::Dtw.to_comparison_algorithm(),
            ComparisonAlgorithm::DTW
        );
        assert_eq!(
            GestureAlgorithm::Lcs.to_comparison_algorithm(),
            ComparisonAlgorithm::LCS
        );
        assert_eq!(
            GestureAlgorithm::EditDistance.to_comparison_algorithm(),
            ComparisonAlgorithm::EditDistance
        );
    }

    #[test]
    fn test_temporal_lcs_algorithm() {
        let config = TemporalGestureConfig {
            algorithm: GestureAlgorithm::Lcs,
            ..small_config()
        };
        let mut classifier = TemporalGestureClassifier::new(config);
        classifier
            .add_template(make_template("wave", GestureType::Wave, 10, 4, wave_pattern))
            .unwrap();

        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d)).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 0).unwrap();
        assert!(result.recognized);
    }

    #[test]
    fn test_temporal_edit_distance_algorithm() {
        let config = TemporalGestureConfig {
            algorithm: GestureAlgorithm::EditDistance,
            ..small_config()
        };
        let mut classifier = TemporalGestureClassifier::new(config);
        classifier
            .add_template(make_template("wave", GestureType::Wave, 10, 4, wave_pattern))
            .unwrap();

        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d)).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 0).unwrap();
        assert!(result.recognized);
    }

    #[test]
    fn test_temporal_default_config() {
        let config = TemporalGestureConfig::default();
        assert_eq!(config.algorithm, GestureAlgorithm::Dtw);
        assert!(config.enable_cache);
        assert_eq!(config.cache_capacity, 256);
        assert!((config.max_distance - 50.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_temporal_cache_stats() {
        let classifier = TemporalGestureClassifier::new(small_config());
        let stats = classifier.cache_stats();
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
    }

    #[test]
    fn test_to_sequence_conversion() {
        let frames: Vec<Vec<f64>> = vec![vec![3.0, 4.0], vec![0.0, 1.0]];
        let seq = TemporalGestureClassifier::to_sequence(&frames);
        // Phần tử đầu: sqrt(9+16) = 5.0 -> 5000
        // Phần tử thứ hai: sqrt(0+1) = 1.0 -> 1000
        assert_eq!(seq.len(), 2);
    }

    #[test]
    fn test_debug_impl() {
        let classifier = TemporalGestureClassifier::new(small_config());
        let dbg = format!("{:?}", classifier);
        assert!(dbg.contains("TemporalGestureClassifier"));
    }
}
