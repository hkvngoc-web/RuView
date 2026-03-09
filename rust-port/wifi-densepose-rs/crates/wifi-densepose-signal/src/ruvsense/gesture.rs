//! Phân loại cử chỉ từ mẫu nhiễu loạn CSI mỗi người.
//!
//! Phân loại cử chỉ bằng cách so sánh chuỗi thời gian nhiễu loạn CSI
//! mỗi người với thư viện mẫu cử chỉ sử dụng Xoắn Thời Gian Động
//! (DTW). Hoạt động xuyên tường và trong bóng tối vì hoạt động
//! trên nhiễu loạn RF, không phải đặc trưng thị giác.
//!
//! # Thuật Toán
//! 1. Thu thập nhiễu loạn CSI mỗi người trong cửa sổ cử chỉ (~1s)
//! 2. Chuẩn hóa và chiếu lên các thành phần chính
//! 3. So sánh với các mẫu cử chỉ đã lưu bằng khoảng cách DTW
//! 4. Phân loại là mẫu gần nhất nếu khoảng cách < ngưỡng
//!
//! # Cử Chỉ Hỗ Trợ
//! Vẫy, chỉ, vẫy gọi, đẩy, vòng tròn, cộng mẫu tùy chỉnh do người dùng định nghĩa.
//!
//! # Tham Khảo
//! - ADR-030 Tầng 6: Lớp Tương Tác Vô Hình
//! - Sakoe & Chiba (1978), "Dynamic programming algorithm optimization
//!   for spoken word recognition" IEEE TASSP

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ phân loại cử chỉ.
#[derive(Debug, thiserror::Error)]
pub enum GestureError {
    /// Chuỗi cử chỉ quá ngắn.
    #[error("Chuỗi quá ngắn: cần >= {needed} khung, có {got}")]
    SequenceTooShort { needed: usize, got: usize },

    /// Không có mẫu nào được đăng ký cho phân loại.
    #[error("Không có mẫu cử chỉ nào được đăng ký")]
    NoTemplates,

    /// Chiều đặc trưng không khớp.
    #[error("Chiều đặc trưng không khớp: kỳ vọng {expected}, nhận được {got}")]
    DimensionMismatch { expected: usize, got: usize },

    /// Tên mẫu không hợp lệ.
    #[error("Tên mẫu không hợp lệ: {0}")]
    InvalidTemplateName(String),
}

// ---------------------------------------------------------------------------
// Kiểu miền
// ---------------------------------------------------------------------------

/// Các danh mục cử chỉ tích hợp.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum GestureType {
    /// Vẫy tay (qua lại).
    Wave,
    /// Chỉ vào mục tiêu.
    Point,
    /// Vẫy gọi (lại đây).
    Beckon,
    /// Chuyển động đẩy về phía trước.
    Push,
    /// Chuyển động vòng tròn.
    Circle,
    /// Cử chỉ tùy chỉnh do người dùng định nghĩa.
    Custom,
}

impl GestureType {
    /// Tên đọc được.
    pub fn name(&self) -> &'static str {
        match self {
            GestureType::Wave => "wave",
            GestureType::Point => "point",
            GestureType::Beckon => "beckon",
            GestureType::Push => "push",
            GestureType::Circle => "circle",
            GestureType::Custom => "custom",
        }
    }
}

/// Mẫu cử chỉ: chuỗi thời gian tham chiếu cho cử chỉ đã biết.
#[derive(Debug, Clone)]
pub struct GestureTemplate {
    /// Tên mẫu duy nhất (ví dụ: "wave_right", "push_forward").
    pub name: String,
    /// Danh mục cử chỉ.
    pub gesture_type: GestureType,
    /// Chuỗi đặc trưng mẫu: `[n_khung][chiều_đặc_trưng]`.
    pub sequence: Vec<Vec<f64>>,
    /// Chiều đặc trưng.
    pub feature_dim: usize,
}

/// Kết quả phân loại cử chỉ.
#[derive(Debug, Clone)]
pub struct GestureResult {
    /// Cử chỉ có được nhận dạng hay không.
    pub recognized: bool,
    /// Loại cử chỉ đã khớp (nếu được nhận dạng).
    pub gesture_type: Option<GestureType>,
    /// Tên mẫu đã khớp (nếu được nhận dạng).
    pub template_name: Option<String>,
    /// Khoảng cách DTW đến đối chiếu tốt nhất.
    pub distance: f64,
    /// Độ tin cậy (0.0 đến 1.0, dựa trên khoảng cách tương đối).
    pub confidence: f64,
    /// ID người mà cử chỉ này thuộc về.
    pub person_id: u64,
    /// Dấu thời gian (micro giây).
    pub timestamp_us: u64,
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho bộ phân loại cử chỉ.
#[derive(Debug, Clone)]
pub struct GestureConfig {
    /// Chiều đặc trưng của vector nhiễu loạn.
    pub feature_dim: usize,
    /// Độ dài chuỗi tối thiểu (khung) cho cử chỉ hợp lệ.
    pub min_sequence_len: usize,
    /// Khoảng cách DTW tối đa cho đối chiếu (thấp hơn = nghiêm ngặt hơn).
    pub max_distance: f64,
    /// Độ rộng dải Sakoe-Chiba DTW (hạn chế xoắn).
    pub band_width: usize,
}

impl Default for GestureConfig {
    fn default() -> Self {
        Self {
            feature_dim: 8,
            min_sequence_len: 10,
            max_distance: 50.0,
            band_width: 5,
        }
    }
}

// ---------------------------------------------------------------------------
// Bộ phân loại cử chỉ
// ---------------------------------------------------------------------------

/// Bộ phân loại cử chỉ sử dụng đối chiếu mẫu DTW.
///
/// Duy trì thư viện mẫu cử chỉ và phân loại các chuỗi
/// nhiễu loạn mới bằng cách tìm mẫu gần nhất.
#[derive(Debug)]
pub struct GestureClassifier {
    config: GestureConfig,
    templates: Vec<GestureTemplate>,
}

impl GestureClassifier {
    /// Tạo bộ phân loại cử chỉ mới.
    pub fn new(config: GestureConfig) -> Self {
        Self {
            config,
            templates: Vec::new(),
        }
    }

    /// Đăng ký mẫu cử chỉ.
    pub fn add_template(&mut self, template: GestureTemplate) -> Result<(), GestureError> {
        if template.name.is_empty() {
            return Err(GestureError::InvalidTemplateName(
                "Tên mẫu không được rỗng".into(),
            ));
        }
        if template.feature_dim != self.config.feature_dim {
            return Err(GestureError::DimensionMismatch {
                expected: self.config.feature_dim,
                got: template.feature_dim,
            });
        }
        if template.sequence.len() < self.config.min_sequence_len {
            return Err(GestureError::SequenceTooShort {
                needed: self.config.min_sequence_len,
                got: template.sequence.len(),
            });
        }
        self.templates.push(template);
        Ok(())
    }

    /// Số mẫu đã đăng ký.
    pub fn template_count(&self) -> usize {
        self.templates.len()
    }

    /// Phân loại chuỗi nhiễu loạn so với các mẫu đã đăng ký.
    ///
    /// `sequence` là `[n_khung][chiều_đặc_trưng]` các đặc trưng nhiễu loạn.
    pub fn classify(
        &self,
        sequence: &[Vec<f64>],
        person_id: u64,
        timestamp_us: u64,
    ) -> Result<GestureResult, GestureError> {
        if self.templates.is_empty() {
            return Err(GestureError::NoTemplates);
        }
        if sequence.len() < self.config.min_sequence_len {
            return Err(GestureError::SequenceTooShort {
                needed: self.config.min_sequence_len,
                got: sequence.len(),
            });
        }
        // Xác thực chiều đặc trưng
        for frame in sequence {
            if frame.len() != self.config.feature_dim {
                return Err(GestureError::DimensionMismatch {
                    expected: self.config.feature_dim,
                    got: frame.len(),
                });
            }
        }

        // Tính khoảng cách DTW đến mỗi mẫu
        let mut best_dist = f64::INFINITY;
        let mut second_best_dist = f64::INFINITY;
        let mut best_idx: Option<usize> = None;

        for (idx, template) in self.templates.iter().enumerate() {
            let dist = dtw_distance(sequence, &template.sequence, self.config.band_width);
            if dist < best_dist {
                second_best_dist = best_dist;
                best_dist = dist;
                best_idx = Some(idx);
            } else if dist < second_best_dist {
                second_best_dist = dist;
            }
        }

        let recognized = best_dist <= self.config.max_distance;

        // Độ tin cậy: đối chiếu tốt nhất tốt hơn bao nhiêu so với tốt nhì
        let confidence = if recognized && second_best_dist.is_finite() && second_best_dist > 1e-10 {
            (1.0 - best_dist / second_best_dist).clamp(0.0, 1.0)
        } else if recognized {
            (1.0 - best_dist / self.config.max_distance).clamp(0.0, 1.0)
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
                distance: best_dist,
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
}

// ---------------------------------------------------------------------------
// Xoắn Thời Gian Động
// ---------------------------------------------------------------------------

/// Tính khoảng cách DTW giữa hai chuỗi thời gian đa biến.
///
/// Sử dụng ràng buộc dải Sakoe-Chiba để hạn chế xoắn.
/// Mỗi khung là một vector `feature_dim` chiều.
fn dtw_distance(seq_a: &[Vec<f64>], seq_b: &[Vec<f64>], band_width: usize) -> f64 {
    let n = seq_a.len();
    let m = seq_b.len();

    if n == 0 || m == 0 {
        return f64::INFINITY;
    }

    // Ma trận chi phí (chỉ cần 2 hàng cho hiệu quả bộ nhớ)
    let mut prev = vec![f64::INFINITY; m + 1];
    let mut curr = vec![f64::INFINITY; m + 1];
    prev[0] = 0.0;

    for i in 1..=n {
        curr[0] = f64::INFINITY;

        let j_start = if band_width >= i {
            1
        } else {
            i.saturating_sub(band_width).max(1)
        };
        let j_end = (i + band_width).min(m);

        for j in 1..=m {
            if j < j_start || j > j_end {
                curr[j] = f64::INFINITY;
                continue;
            }

            let cost = euclidean_distance(&seq_a[i - 1], &seq_b[j - 1]);
            curr[j] = cost
                + prev[j] // chèn
                    .min(curr[j - 1]) // xóa
                    .min(prev[j - 1]); // khớp
        }

        std::mem::swap(&mut prev, &mut curr);
    }

    prev[m]
}

/// Khoảng cách Euclid giữa hai vector đặc trưng.
fn euclidean_distance(a: &[f64], b: &[f64]) -> f64 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (x - y) * (x - y))
        .sum::<f64>()
        .sqrt()
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

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

    fn small_config() -> GestureConfig {
        GestureConfig {
            feature_dim: 4,
            min_sequence_len: 5,
            max_distance: 10.0,
            band_width: 3,
        }
    }

    #[test]
    fn test_classifier_creation() {
        let classifier = GestureClassifier::new(small_config());
        assert_eq!(classifier.template_count(), 0);
    }

    #[test]
    fn test_add_template() {
        let mut classifier = GestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 4, wave_pattern);
        classifier.add_template(template).unwrap();
        assert_eq!(classifier.template_count(), 1);
    }

    #[test]
    fn test_add_template_empty_name() {
        let mut classifier = GestureClassifier::new(small_config());
        let template = make_template("", GestureType::Wave, 10, 4, wave_pattern);
        assert!(matches!(
            classifier.add_template(template),
            Err(GestureError::InvalidTemplateName(_))
        ));
    }

    #[test]
    fn test_add_template_wrong_dim() {
        let mut classifier = GestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 8, wave_pattern);
        assert!(matches!(
            classifier.add_template(template),
            Err(GestureError::DimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_add_template_too_short() {
        let mut classifier = GestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 3, 4, wave_pattern);
        assert!(matches!(
            classifier.add_template(template),
            Err(GestureError::SequenceTooShort { .. })
        ));
    }

    #[test]
    fn test_classify_no_templates() {
        let classifier = GestureClassifier::new(small_config());
        let seq: Vec<Vec<f64>> = (0..10).map(|_| vec![0.0; 4]).collect();
        assert!(matches!(
            classifier.classify(&seq, 1, 0),
            Err(GestureError::NoTemplates)
        ));
    }

    #[test]
    fn test_classify_exact_match() {
        let mut classifier = GestureClassifier::new(small_config());
        let template = make_template("wave", GestureType::Wave, 10, 4, wave_pattern);
        classifier.add_template(template).unwrap();

        // Nạp mẫu giống hệt
        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d)).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 100_000).unwrap();
        assert!(result.recognized);
        assert_eq!(result.gesture_type, Some(GestureType::Wave));
        assert!(
            result.distance < 1e-10,
            "Khớp chính xác phải có khoảng cách bằng 0"
        );
    }

    #[test]
    fn test_classify_best_of_two() {
        let mut classifier = GestureClassifier::new(GestureConfig {
            max_distance: 100.0,
            ..small_config()
        });
        classifier
            .add_template(make_template(
                "wave",
                GestureType::Wave,
                10,
                4,
                wave_pattern,
            ))
            .unwrap();
        classifier
            .add_template(make_template(
                "push",
                GestureType::Push,
                10,
                4,
                push_pattern,
            ))
            .unwrap();

        // Nạp mẫu giống vẫy
        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| (0..4).map(|d| wave_pattern(t, d) + 0.01).collect())
            .collect();

        let result = classifier.classify(&seq, 1, 0).unwrap();
        assert!(result.recognized);
        assert_eq!(result.gesture_type, Some(GestureType::Wave));
    }

    #[test]
    fn test_classify_no_match_high_distance() {
        let mut classifier = GestureClassifier::new(GestureConfig {
            max_distance: 0.001, // rất nghiêm ngặt
            ..small_config()
        });
        classifier
            .add_template(make_template(
                "wave",
                GestureType::Wave,
                10,
                4,
                wave_pattern,
            ))
            .unwrap();

        // Chuỗi ngẫu nhiên
        let seq: Vec<Vec<f64>> = (0..10)
            .map(|t| vec![t as f64 * 10.0, 0.0, 0.0, 0.0])
            .collect();

        let result = classifier.classify(&seq, 1, 0).unwrap();
        assert!(!result.recognized);
        assert!(result.gesture_type.is_none());
    }

    #[test]
    fn test_dtw_identical_sequences() {
        let seq: Vec<Vec<f64>> = vec![vec![1.0, 2.0], vec![3.0, 4.0], vec![5.0, 6.0]];
        let dist = dtw_distance(&seq, &seq, 3);
        assert!(
            dist < 1e-10,
            "Chuỗi giống hệt phải có khoảng cách DTW bằng 0"
        );
    }

    #[test]
    fn test_dtw_different_sequences() {
        let a: Vec<Vec<f64>> = vec![vec![0.0], vec![0.0], vec![0.0]];
        let b: Vec<Vec<f64>> = vec![vec![10.0], vec![10.0], vec![10.0]];
        let dist = dtw_distance(&a, &b, 3);
        assert!(
            dist > 0.0,
            "Chuỗi khác nhau phải có khoảng cách DTW khác 0"
        );
    }

    #[test]
    fn test_dtw_time_warped() {
        // Cùng hình dạng nhưng tốc độ khác
        let a: Vec<Vec<f64>> = vec![vec![0.0], vec![1.0], vec![2.0], vec![3.0]];
        let b: Vec<Vec<f64>> = vec![
            vec![0.0],
            vec![0.5],
            vec![1.0],
            vec![1.5],
            vec![2.0],
            vec![2.5],
            vec![3.0],
        ];
        let dist = dtw_distance(&a, &b, 4);
        // DTW phải tương đối nhỏ dù độ dài khác nhau
        assert!(dist < 2.0, "DTW phải xử lý được xoắn thời gian, nhận được {}", dist);
    }

    #[test]
    fn test_euclidean_distance() {
        let a = vec![0.0, 3.0];
        let b = vec![4.0, 0.0];
        let d = euclidean_distance(&a, &b);
        assert!((d - 5.0).abs() < 1e-10);
    }

    #[test]
    fn test_gesture_type_names() {
        assert_eq!(GestureType::Wave.name(), "wave");
        assert_eq!(GestureType::Push.name(), "push");
        assert_eq!(GestureType::Circle.name(), "circle");
        assert_eq!(GestureType::Custom.name(), "custom");
    }
}
