//! Phát hiện đối kháng: nhận dạng tín hiệu vật lý bất khả thi.
//!
//! Phát hiện tín hiệu WiFi giả mạo hoặc tiêm bằng cách kiểm tra
//! tính nhất quán đa liên kết, vi phạm ràng buộc mô hình trường, và
//! tính hợp lý vật lý. Một lần tiêm đơn liên kết không thể đánh lừa lưới
//! đa tĩnh vì nó sẽ vi phạm ràng buộc hình học giữa các liên kết.
//!
//! # Kiểm Tra
//! 1. **Nhất quán đa liên kết**: Cơ thể thực gây nhiễu loạn tất cả liên kết
//!    đi qua vị trí của nó. Tiêm chỉ ảnh hưởng liên kết mục tiêu.
//! 2. **Ràng buộc mô hình trường**: Nhiễu loạn phải nhất quán với
//!    cấu trúc eigenmode của phòng.
//! 3. **Liên tục thời gian**: Chuyển động thực mượt mà; tiêm gây ra
//!    bất liên tục trong không gian nhúng.
//! 4. **Bảo toàn năng lượng**: Tổng năng lượng nhiễu loạn giữa các liên kết
//!    phải nhất quán với số lượng và kích thước cơ thể hiện diện.
//!
//! # Tham Khảo
//! - ADR-030 Tầng 7: Phát Hiện Đối Kháng

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ phát hiện đối kháng.
#[derive(Debug, thiserror::Error)]
pub enum AdversarialError {
    /// Không đủ liên kết cho kiểm tra nhất quán đa liên kết.
    #[error("Không đủ liên kết: cần >= {needed}, có {got}")]
    InsufficientLinks { needed: usize, got: usize },

    /// Chiều không khớp.
    #[error("Chiều không khớp: kỳ vọng {expected}, nhận được {got}")]
    DimensionMismatch { expected: usize, got: usize },

    /// Không có đường cơ sở cho kiểm tra ràng buộc.
    #[error("Không có đường cơ sở — hiệu chuẩn mô hình trường trước")]
    NoBaseline,
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho phát hiện đối kháng.
#[derive(Debug, Clone)]
pub struct AdversarialConfig {
    /// Số liên kết trong lưới.
    pub n_links: usize,
    /// Số liên kết tối thiểu cho nhất quán đa liên kết (mặc định 4).
    pub min_links: usize,
    /// Ngưỡng nhất quán: tỷ lệ liên kết phải đồng thuận (0.0-1.0).
    pub consistency_threshold: f64,
    /// Tỷ lệ năng lượng tối đa cho phép giữa bất kỳ liên kết đơn nào và tổng.
    pub max_single_link_energy_ratio: f64,
    /// Bất liên tục thời gian tối đa cho phép trong không gian nhúng.
    pub max_temporal_discontinuity: f64,
    /// Năng lượng nhiễu loạn tối đa cho phép mỗi cơ thể.
    pub max_energy_per_body: f64,
}

impl Default for AdversarialConfig {
    fn default() -> Self {
        Self {
            n_links: 12,
            min_links: 4,
            consistency_threshold: 0.6,
            max_single_link_energy_ratio: 0.5,
            max_temporal_discontinuity: 5.0,
            max_energy_per_body: 100.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Kết quả phát hiện
// ---------------------------------------------------------------------------

/// Loại bất thường đối kháng được phát hiện.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnomalyType {
    /// Liên kết đơn có nhiễu loạn không nhất quán với các liên kết khác.
    SingleLinkInjection,
    /// Nhiễu loạn vi phạm cấu trúc eigenmode mô hình trường.
    FieldModelViolation,
    /// Bất liên tục đột ngột trong quỹ đạo nhúng.
    TemporalDiscontinuity,
    /// Tổng năng lượng nhiễu loạn không nhất quán với mức chiếm dụng.
    EnergyViolation,
    /// Nhiều loại bất thường được phát hiện đồng thời.
    MultipleViolations,
}

impl AnomalyType {
    /// Tên đọc được.
    pub fn name(&self) -> &'static str {
        match self {
            AnomalyType::SingleLinkInjection => "single_link_injection",
            AnomalyType::FieldModelViolation => "field_model_violation",
            AnomalyType::TemporalDiscontinuity => "temporal_discontinuity",
            AnomalyType::EnergyViolation => "energy_violation",
            AnomalyType::MultipleViolations => "multiple_violations",
        }
    }
}

/// Kết quả phát hiện đối kháng trên một khung.
#[derive(Debug, Clone)]
pub struct AdversarialResult {
    /// Có phát hiện bất thường nào hay không.
    pub anomaly_detected: bool,
    /// Loại bất thường (nếu được phát hiện).
    pub anomaly_type: Option<AnomalyType>,
    /// Điểm bất thường (0.0 = sạch, 1.0 = chắc chắn đối kháng).
    pub anomaly_score: f64,
    /// Kết quả từng kiểm tra.
    pub checks: CheckResults,
    /// Chỉ số liên kết bị ảnh hưởng (nếu tiêm đơn liên kết).
    pub affected_links: Vec<usize>,
    /// Dấu thời gian (micro giây).
    pub timestamp_us: u64,
}

/// Kết quả của từng kiểm tra riêng lẻ.
#[derive(Debug, Clone)]
pub struct CheckResults {
    /// Điểm nhất quán đa liên kết (0.0 = không nhất quán, 1.0 = hoàn toàn nhất quán).
    pub consistency_score: f64,
    /// Điểm phần dư mô hình trường (thấp hơn = nhất quán hơn với mode).
    pub field_model_residual: f64,
    /// Điểm liên tục thời gian (thấp hơn = mượt hơn).
    pub temporal_continuity: f64,
    /// Điểm bảo toàn năng lượng (gần 1.0 hơn = nhất quán).
    pub energy_ratio: f64,
}

// ---------------------------------------------------------------------------
// Bộ phát hiện đối kháng
// ---------------------------------------------------------------------------

/// Bộ phát hiện tín hiệu đối kháng cho lưới đa tĩnh.
///
/// Kiểm tra mỗi khung về tính hợp lý vật lý trên nhiều
/// tiêu chí độc lập. Tín hiệu giả mạo vượt qua một kiểm tra
/// khó có khả năng vượt qua tất cả.
#[derive(Debug)]
pub struct AdversarialDetector {
    config: AdversarialConfig,
    /// Năng lượng mỗi liên kết của khung trước (cho liên tục thời gian).
    prev_energies: Option<Vec<f64>>,
    /// Tổng năng lượng của khung trước.
    prev_total_energy: Option<f64>,
    /// Tổng số khung đã xử lý.
    total_frames: u64,
    /// Tổng số bất thường đã phát hiện.
    anomaly_count: u64,
}

impl AdversarialDetector {
    /// Tạo bộ phát hiện đối kháng mới.
    pub fn new(config: AdversarialConfig) -> Result<Self, AdversarialError> {
        if config.n_links < config.min_links {
            return Err(AdversarialError::InsufficientLinks {
                needed: config.min_links,
                got: config.n_links,
            });
        }
        Ok(Self {
            config,
            prev_energies: None,
            prev_total_energy: None,
            total_frames: 0,
            anomaly_count: 0,
        })
    }

    /// Kiểm tra một khung về bất thường đối kháng.
    ///
    /// `link_energies`: năng lượng nhiễu loạn mỗi liên kết (từ mô hình trường).
    /// `n_bodies`: số cơ thể ước lượng hiện diện.
    /// `timestamp_us`: dấu thời gian khung.
    pub fn check(
        &mut self,
        link_energies: &[f64],
        n_bodies: usize,
        timestamp_us: u64,
    ) -> Result<AdversarialResult, AdversarialError> {
        if link_energies.len() != self.config.n_links {
            return Err(AdversarialError::DimensionMismatch {
                expected: self.config.n_links,
                got: link_energies.len(),
            });
        }

        self.total_frames += 1;

        let total_energy: f64 = link_energies.iter().sum();

        // Kiểm tra 1: Nhất quán đa liên kết
        let consistency = self.check_consistency(link_energies, total_energy);

        // Kiểm tra 2: Phần dư mô hình trường (đơn giản — kiểm tra phân bố năng lượng)
        let field_residual = self.check_field_model(link_energies, total_energy);

        // Kiểm tra 3: Liên tục thời gian
        let temporal = self.check_temporal(link_energies, total_energy);

        // Kiểm tra 4: Bảo toàn năng lượng
        let energy_ratio = self.check_energy(total_energy, n_bodies);

        // Lưu cho khung tiếp theo
        self.prev_energies = Some(link_energies.to_vec());
        self.prev_total_energy = Some(total_energy);

        let checks = CheckResults {
            consistency_score: consistency,
            field_model_residual: field_residual,
            temporal_continuity: temporal,
            energy_ratio,
        };

        // Tổng hợp điểm bất thường
        let mut violations = Vec::new();

        if consistency < self.config.consistency_threshold {
            violations.push(AnomalyType::SingleLinkInjection);
        }
        if field_residual > 0.8 {
            violations.push(AnomalyType::FieldModelViolation);
        }
        if temporal > self.config.max_temporal_discontinuity {
            violations.push(AnomalyType::TemporalDiscontinuity);
        }
        if energy_ratio > 2.0 || (n_bodies > 0 && energy_ratio < 0.1) {
            violations.push(AnomalyType::EnergyViolation);
        }

        let anomaly_detected = !violations.is_empty();
        let anomaly_type = match violations.len() {
            0 => None,
            1 => Some(violations[0]),
            _ => Some(AnomalyType::MultipleViolations),
        };

        // Điểm: kết hợp có trọng số
        let anomaly_score = ((1.0 - consistency) * 0.4
            + field_residual * 0.2
            + (temporal / self.config.max_temporal_discontinuity).min(1.0) * 0.2
            + ((energy_ratio - 1.0).abs() / 2.0).min(1.0) * 0.2)
            .clamp(0.0, 1.0);

        // Tìm liên kết bị ảnh hưởng (tỷ lệ năng lượng đơn liên kết cao nhất)
        let affected_links = if anomaly_detected {
            self.find_anomalous_links(link_energies, total_energy)
        } else {
            Vec::new()
        };

        if anomaly_detected {
            self.anomaly_count += 1;
        }

        Ok(AdversarialResult {
            anomaly_detected,
            anomaly_type,
            anomaly_score,
            checks,
            affected_links,
            timestamp_us,
        })
    }

    /// Nhất quán đa liên kết: tỷ lệ liên kết có năng lượng tương quan?
    ///
    /// Cơ thể thực gây nhiễu loạn nhiều liên kết. Tiêm ảnh hưởng ít liên kết.
    fn check_consistency(&self, energies: &[f64], total: f64) -> f64 {
        if total < 1e-15 {
            return 1.0; // Không có nhiễu loạn = nhất quán (phòng trống)
        }

        let mean = total / energies.len() as f64;
        let threshold = mean * 0.1; // liên kết phải có ít nhất 10% năng lượng trung bình

        let active_count = energies.iter().filter(|&&e| e > threshold).count();
        active_count as f64 / energies.len() as f64
    }

    /// Kiểm tra mô hình trường: phân bố năng lượng có nhất quán với truyền vật lý không?
    ///
    /// Trong kịch bản thực, năng lượng nên phân bố giữa các liên kết
    /// dựa trên hình học. Tiêm tập trung cho điểm phần dư cao.
    fn check_field_model(&self, energies: &[f64], total: f64) -> f64 {
        if total < 1e-15 {
            return 0.0;
        }

        // Tính hệ số Gini của phân bố năng lượng
        // Gini = 0 → phân bố đều hoàn hảo, Gini = 1 → tất cả trong một liên kết
        let n = energies.len() as f64;
        let mut sorted: Vec<f64> = energies.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let numerator: f64 = sorted
            .iter()
            .enumerate()
            .map(|(i, &x)| (2.0 * (i + 1) as f64 - n - 1.0) * x)
            .sum();

        let gini = numerator / (n * total);
        gini.clamp(0.0, 1.0)
    }

    /// Liên tục thời gian: năng lượng mỗi liên kết thay đổi bao nhiêu so với khung trước?
    fn check_temporal(&self, energies: &[f64], _total: f64) -> f64 {
        match &self.prev_energies {
            None => 0.0, // Khung đầu tiên, không kiểm tra thời gian
            Some(prev) => {
                let diff_energy: f64 = energies
                    .iter()
                    .zip(prev.iter())
                    .map(|(&a, &b)| (a - b) * (a - b))
                    .sum::<f64>()
                    .sqrt();
                diff_energy
            }
        }
    }

    /// Bảo toàn năng lượng: tổng năng lượng có nhất quán với số cơ thể không?
    fn check_energy(&self, total_energy: f64, n_bodies: usize) -> f64 {
        if n_bodies == 0 {
            // Không có cơ thể: bất kỳ năng lượng nào đều đáng ngờ
            return if total_energy > 1e-10 {
                total_energy
            } else {
                0.0
            };
        }
        let expected = n_bodies as f64 * self.config.max_energy_per_body;
        if expected < 1e-15 {
            return 0.0;
        }
        total_energy / expected
    }

    /// Tìm liên kết có năng lượng bất thường cao so với trung bình.
    fn find_anomalous_links(&self, energies: &[f64], total: f64) -> Vec<usize> {
        if total < 1e-15 {
            return Vec::new();
        }

        energies
            .iter()
            .enumerate()
            .filter(|(_, &e)| e / total > self.config.max_single_link_energy_ratio)
            .map(|(i, _)| i)
            .collect()
    }

    /// Tổng số khung đã xử lý.
    pub fn total_frames(&self) -> u64 {
        self.total_frames
    }

    /// Tổng số bất thường đã phát hiện.
    pub fn anomaly_count(&self) -> u64 {
        self.anomaly_count
    }

    /// Tỷ lệ bất thường (bất thường / tổng khung).
    pub fn anomaly_rate(&self) -> f64 {
        if self.total_frames == 0 {
            0.0
        } else {
            self.anomaly_count as f64 / self.total_frames as f64
        }
    }

    /// Đặt lại trạng thái bộ phát hiện.
    pub fn reset(&mut self) {
        self.prev_energies = None;
        self.prev_total_energy = None;
        self.total_frames = 0;
        self.anomaly_count = 0;
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn default_config() -> AdversarialConfig {
        AdversarialConfig {
            n_links: 6,
            min_links: 4,
            consistency_threshold: 0.6,
            max_single_link_energy_ratio: 0.5,
            max_temporal_discontinuity: 5.0,
            max_energy_per_body: 10.0,
        }
    }

    #[test]
    fn test_detector_creation() {
        let det = AdversarialDetector::new(default_config()).unwrap();
        assert_eq!(det.total_frames(), 0);
        assert_eq!(det.anomaly_count(), 0);
    }

    #[test]
    fn test_insufficient_links() {
        let config = AdversarialConfig {
            n_links: 2,
            min_links: 4,
            ..default_config()
        };
        assert!(matches!(
            AdversarialDetector::new(config),
            Err(AdversarialError::InsufficientLinks { .. })
        ));
    }

    #[test]
    fn test_clean_frame_no_anomaly() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();

        // Năng lượng đồng đều giữa tất cả liên kết (cơ thể thực)
        let energies = vec![1.0, 1.1, 0.9, 1.0, 1.05, 0.95];
        let result = det.check(&energies, 1, 0).unwrap();

        assert!(
            !result.anomaly_detected,
            "Năng lượng đồng đều không nên kích hoạt bất thường"
        );
        assert!(result.anomaly_score < 0.5);
    }

    #[test]
    fn test_single_link_injection_detected() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();

        // Tất cả năng lượng trên một liên kết (tiêm)
        let energies = vec![10.0, 0.0, 0.0, 0.0, 0.0, 0.0];
        let result = det.check(&energies, 0, 0).unwrap();

        assert!(
            result.anomaly_detected,
            "Tiêm đơn liên kết phải được phát hiện"
        );
        assert!(result.affected_links.contains(&0));
    }

    #[test]
    fn test_empty_room_no_anomaly() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();

        let energies = vec![0.0; 6];
        let result = det.check(&energies, 0, 0).unwrap();

        assert!(!result.anomaly_detected);
    }

    #[test]
    fn test_temporal_discontinuity() {
        let mut det = AdversarialDetector::new(AdversarialConfig {
            max_temporal_discontinuity: 1.0, // nghiêm ngặt
            ..default_config()
        })
        .unwrap();

        // Khung 1: năng lượng thấp
        let energies1 = vec![0.1; 6];
        det.check(&energies1, 0, 0).unwrap();

        // Khung 2: năng lượng lớn đột ngột (bất liên tục)
        let energies2 = vec![100.0; 6];
        let result = det.check(&energies2, 0, 50_000).unwrap();

        assert!(
            result.anomaly_detected,
            "Bất liên tục thời gian phải được phát hiện"
        );
    }

    #[test]
    fn test_energy_violation_too_high() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();

        // Năng lượng vượt xa mức 1 cơ thể nên tạo ra
        let energies = vec![100.0; 6]; // tổng = 600, max_per_body = 10
        let result = det.check(&energies, 1, 0).unwrap();

        assert!(
            result.anomaly_detected,
            "Năng lượng quá mức phải kích hoạt bất thường"
        );
    }

    #[test]
    fn test_dimension_mismatch() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();
        let result = det.check(&[1.0, 2.0], 0, 0);
        assert!(matches!(
            result,
            Err(AdversarialError::DimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_anomaly_rate() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();

        // 2 khung sạch
        det.check(&vec![1.0; 6], 1, 0).unwrap();
        det.check(&vec![1.0; 6], 1, 50_000).unwrap();

        // 1 khung bất thường
        det.check(&vec![10.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0, 100_000)
            .unwrap();

        assert_eq!(det.total_frames(), 3);
        assert!(det.anomaly_count() >= 1);
        assert!(det.anomaly_rate() > 0.0);
    }

    #[test]
    fn test_reset() {
        let mut det = AdversarialDetector::new(default_config()).unwrap();
        det.check(&vec![1.0; 6], 1, 0).unwrap();
        det.reset();

        assert_eq!(det.total_frames(), 0);
        assert_eq!(det.anomaly_count(), 0);
    }

    #[test]
    fn test_anomaly_type_names() {
        assert_eq!(
            AnomalyType::SingleLinkInjection.name(),
            "single_link_injection"
        );
        assert_eq!(
            AnomalyType::FieldModelViolation.name(),
            "field_model_violation"
        );
        assert_eq!(
            AnomalyType::TemporalDiscontinuity.name(),
            "temporal_discontinuity"
        );
        assert_eq!(AnomalyType::EnergyViolation.name(), "energy_violation");
        assert_eq!(
            AnomalyType::MultipleViolations.name(),
            "multiple_violations"
        );
    }

    #[test]
    fn test_gini_coefficient_uniform() {
        let det = AdversarialDetector::new(default_config()).unwrap();
        let energies = vec![1.0; 6];
        let total = 6.0;
        let gini = det.check_field_model(&energies, total);
        assert!(
            gini < 0.1,
            "Phân bố đồng đều phải có Gini thấp: {}",
            gini
        );
    }

    #[test]
    fn test_gini_coefficient_concentrated() {
        let det = AdversarialDetector::new(default_config()).unwrap();
        let energies = vec![6.0, 0.0, 0.0, 0.0, 0.0, 0.0];
        let total = 6.0;
        let gini = det.check_field_model(&energies, total);
        assert!(
            gini > 0.5,
            "Phân bố tập trung phải có Gini cao: {}",
            gini
        );
    }
}
