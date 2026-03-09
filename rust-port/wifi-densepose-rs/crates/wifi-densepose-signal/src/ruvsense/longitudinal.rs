//! Phát hiện trôi sinh trắc học theo chiều dọc thời gian.
//!
//! Duy trì đường cơ sở sinh lý cá nhân theo ngày/tuần sử dụng thống kê
//! trực tuyến Welford. Phát hiện trôi có ý nghĩa trong đối xứng dáng đi,
//! độ ổn định, quy luật hô hấp, vi rung, và mức hoạt động. Tạo ra
//! báo cáo bằng chứng có thể truy vết liên kết đến quỹ đạo nhúng đã lưu.
//!
//! # Bất biến chính
//! - Đường cơ sở yêu cầu >= 7 ngày quan sát trước khi phát hiện trôi được kích hoạt
//! - Cảnh báo trôi yêu cầu độ lệch > 2-sigma duy trì >= 3 ngày liên tiếp
//! - Đầu ra là giá trị chỉ số và độ lệch, không bao giờ dùng ngôn ngữ chẩn đoán
//! - Thống kê Welford sử dụng toàn bộ lịch sử (không cửa sổ) để đảm bảo ổn định
//!
//! # Tài liệu tham khảo
//! - Welford, B.P. (1962). "Note on a Method for Calculating Corrected
//!   Sums of Squares." Technometrics.
//! - ADR-030 Tier 4: Phát hiện trôi sinh trắc học theo chiều dọc

use crate::ruvsense::field_model::WelfordStats;

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ thao tác giám sát theo chiều dọc.
#[derive(Debug, thiserror::Error)]
pub enum LongitudinalError {
    /// Không đủ ngày quan sát cho phát hiện trôi.
    #[error("Không đủ ngày quan sát: cần >= {needed}, có {got}")]
    InsufficientDays { needed: u32, got: u32 },

    /// Không tìm thấy ID người trong sổ đăng ký.
    #[error("ID người không xác định: {0}")]
    UnknownPerson(u64),

    /// Chiều nhúng không khớp.
    #[error("Chiều nhúng không khớp: kỳ vọng {expected}, nhận được {got}")]
    EmbeddingDimensionMismatch { expected: usize, got: usize },

    /// Giá trị chỉ số không hợp lệ.
    #[error("Giá trị chỉ số không hợp lệ cho {metric}: {reason}")]
    InvalidMetric { metric: String, reason: String },
}

// ---------------------------------------------------------------------------
// Kiểu miền
// ---------------------------------------------------------------------------

/// Các loại chỉ số sinh lý được theo dõi cho mỗi người.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum DriftMetric {
    /// Tỉ lệ đối xứng dáng đi (0.0 = hoàn toàn đối xứng, cao hơn = bất đối xứng).
    GaitSymmetry,
    /// Chỉ số ổn định (thấp hơn = kém ổn định hơn).
    StabilityIndex,
    /// Quy luật hô hấp (hệ số biến thiên của khoảng thở).
    BreathingRegularity,
    /// Biên độ vi rung (mm, từ nhiễu tư thế tần số cao).
    MicroTremor,
    /// Mức hoạt động hàng ngày (chuẩn hóa 0-1).
    ActivityLevel,
}

impl DriftMetric {
    /// Tất cả các biến thể chỉ số.
    pub fn all() -> &'static [DriftMetric] {
        &[
            DriftMetric::GaitSymmetry,
            DriftMetric::StabilityIndex,
            DriftMetric::BreathingRegularity,
            DriftMetric::MicroTremor,
            DriftMetric::ActivityLevel,
        ]
    }

    /// Tên dễ đọc.
    pub fn name(&self) -> &'static str {
        match self {
            DriftMetric::GaitSymmetry => "gait_symmetry",
            DriftMetric::StabilityIndex => "stability_index",
            DriftMetric::BreathingRegularity => "breathing_regularity",
            DriftMetric::MicroTremor => "micro_tremor",
            DriftMetric::ActivityLevel => "activity_level",
        }
    }
}

/// Hướng trôi.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DriftDirection {
    /// Chỉ số đang tăng so với đường cơ sở.
    Increasing,
    /// Chỉ số đang giảm so với đường cơ sở.
    Decreasing,
}

/// Mức giám sát cho báo cáo trôi.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum MonitoringLevel {
    /// Mức 1: Giá trị chỉ số sinh lý thô.
    Physiological = 1,
    /// Mức 2: Độ lệch so với đường cơ sở cá nhân.
    Drift = 2,
    /// Mức 3: Tương quan rủi ro đối chiếu mẫu.
    RiskCorrelation = 3,
}

/// Báo cáo trôi với bằng chứng có thể truy vết.
#[derive(Debug, Clone)]
pub struct DriftReport {
    /// Người mà báo cáo này liên quan đến.
    pub person_id: u64,
    /// Chỉ số nào bị trôi.
    pub metric: DriftMetric,
    /// Hướng trôi.
    pub direction: DriftDirection,
    /// Điểm Z so với đường cơ sở cá nhân.
    pub z_score: f64,
    /// Giá trị chỉ số hiện tại (hôm nay hoặc gần nhất).
    pub current_value: f64,
    /// Trung bình đường cơ sở cho chỉ số này.
    pub baseline_mean: f64,
    /// Độ lệch chuẩn đường cơ sở.
    pub baseline_std: f64,
    /// Số ngày liên tiếp trôi đã được duy trì.
    pub sustained_days: u32,
    /// Mức giám sát.
    pub level: MonitoringLevel,
    /// Dấu thời gian (micro giây) khi báo cáo này được tạo.
    pub timestamp_us: u64,
}

/// Tóm tắt chỉ số hàng ngày cho một người.
#[derive(Debug, Clone)]
pub struct DailyMetricSummary {
    /// ID người.
    pub person_id: u64,
    /// Dấu thời gian ngày (đầu ngày, micro giây).
    pub day_us: u64,
    /// Giá trị chỉ số cho ngày này.
    pub metrics: Vec<(DriftMetric, f64)>,
    /// Trọng tâm nhúng AETHER cho ngày này.
    pub embedding_centroid: Option<Vec<f32>>,
}

// ---------------------------------------------------------------------------
// Đường cơ sở cá nhân
// ---------------------------------------------------------------------------

/// Đường cơ sở theo chiều dọc cho mỗi người với thống kê Welford.
///
/// Theo dõi trung bình chạy và phương sai cho mỗi chỉ số sinh lý
/// trên toàn bộ lịch sử quan sát của người đó. Sử dụng thuật toán Welford
/// để đảm bảo ổn định số học.
#[derive(Debug, Clone)]
pub struct PersonalBaseline {
    /// Định danh duy nhất của người.
    pub person_id: u64,
    /// Bộ tích lũy Welford cho mỗi chỉ số.
    pub gait_symmetry: WelfordStats,
    pub stability_index: WelfordStats,
    pub breathing_regularity: WelfordStats,
    pub micro_tremor: WelfordStats,
    pub activity_level: WelfordStats,
    /// Trọng tâm chạy của nhúng AETHER.
    pub embedding_centroid: Vec<f32>,
    /// Số ngày quan sát.
    pub observation_days: u32,
    /// Dấu thời gian cập nhật cuối (micro giây).
    pub updated_at_us: u64,
    /// Bộ đếm ngày trôi liên tiếp cho mỗi chỉ số.
    drift_counters: [u32; 5],
}

impl PersonalBaseline {
    /// Tạo đường cơ sở mới cho một người.
    ///
    /// `embedding_dim` thường là 128 cho nhúng AETHER.
    pub fn new(person_id: u64, embedding_dim: usize) -> Self {
        Self {
            person_id,
            gait_symmetry: WelfordStats::new(),
            stability_index: WelfordStats::new(),
            breathing_regularity: WelfordStats::new(),
            micro_tremor: WelfordStats::new(),
            activity_level: WelfordStats::new(),
            embedding_centroid: vec![0.0; embedding_dim],
            observation_days: 0,
            updated_at_us: 0,
            drift_counters: [0; 5],
        }
    }

    /// Lấy thống kê Welford cho một chỉ số cụ thể.
    pub fn stats_for(&self, metric: DriftMetric) -> &WelfordStats {
        match metric {
            DriftMetric::GaitSymmetry => &self.gait_symmetry,
            DriftMetric::StabilityIndex => &self.stability_index,
            DriftMetric::BreathingRegularity => &self.breathing_regularity,
            DriftMetric::MicroTremor => &self.micro_tremor,
            DriftMetric::ActivityLevel => &self.activity_level,
        }
    }

    /// Lấy thống kê Welford có thể thay đổi cho một chỉ số cụ thể.
    fn stats_for_mut(&mut self, metric: DriftMetric) -> &mut WelfordStats {
        match metric {
            DriftMetric::GaitSymmetry => &mut self.gait_symmetry,
            DriftMetric::StabilityIndex => &mut self.stability_index,
            DriftMetric::BreathingRegularity => &mut self.breathing_regularity,
            DriftMetric::MicroTremor => &mut self.micro_tremor,
            DriftMetric::ActivityLevel => &mut self.activity_level,
        }
    }

    /// Chỉ số của một chỉ số trong mảng drift_counters.
    fn metric_index(metric: DriftMetric) -> usize {
        match metric {
            DriftMetric::GaitSymmetry => 0,
            DriftMetric::StabilityIndex => 1,
            DriftMetric::BreathingRegularity => 2,
            DriftMetric::MicroTremor => 3,
            DriftMetric::ActivityLevel => 4,
        }
    }

    /// Đường cơ sở đã có đủ dữ liệu cho phát hiện trôi hay chưa.
    pub fn is_ready(&self) -> bool {
        self.observation_days >= 7
    }

    /// Cập nhật đường cơ sở với tóm tắt hàng ngày.
    ///
    /// Trả về báo cáo trôi cho bất kỳ chỉ số nào vượt ngưỡng.
    pub fn update_daily(
        &mut self,
        summary: &DailyMetricSummary,
        timestamp_us: u64,
    ) -> Vec<DriftReport> {
        self.observation_days += 1;
        self.updated_at_us = timestamp_us;

        // Cập nhật trọng tâm nhúng với EMA (hệ số suy giảm = 0.95)
        if let Some(ref emb) = summary.embedding_centroid {
            if emb.len() == self.embedding_centroid.len() {
                let alpha = 0.05_f32; // 1 - 0.95
                for (c, e) in self.embedding_centroid.iter_mut().zip(emb.iter()) {
                    *c = (1.0 - alpha) * *c + alpha * *e;
                }
            }
        }

        let mut reports = Vec::new();

        let observation_days = self.observation_days;

        for &(metric, value) in &summary.metrics {
            // Cập nhật thống kê và trích xuất giá trị trước khi giải phóng mượn thay đổi
            let (z, baseline_mean, baseline_std) = {
                let stats = self.stats_for_mut(metric);
                stats.update(value);
                let z = stats.z_score(value);
                let mean = stats.mean;
                let std = stats.std_dev();
                (z, mean, std)
            };

            if !self.is_ready_at(observation_days) {
                continue;
            }

            let idx = Self::metric_index(metric);

            if z.abs() > 2.0 {
                self.drift_counters[idx] += 1;
            } else {
                self.drift_counters[idx] = 0;
            }

            if self.drift_counters[idx] >= 3 {
                let direction = if z > 0.0 {
                    DriftDirection::Increasing
                } else {
                    DriftDirection::Decreasing
                };

                let level = if self.drift_counters[idx] >= 7 {
                    MonitoringLevel::RiskCorrelation
                } else {
                    MonitoringLevel::Drift
                };

                reports.push(DriftReport {
                    person_id: self.person_id,
                    metric,
                    direction,
                    z_score: z,
                    current_value: value,
                    baseline_mean,
                    baseline_std,
                    sustained_days: self.drift_counters[idx],
                    level,
                    timestamp_us,
                });
            }
        }

        reports
    }

    /// Kiểm tra sẵn sàng tại số ngày quan sát cụ thể (hàm nội bộ).
    fn is_ready_at(&self, days: u32) -> bool {
        days >= 7
    }

    /// Lấy bộ đếm trôi hiện tại cho một chỉ số.
    pub fn drift_days(&self, metric: DriftMetric) -> u32 {
        self.drift_counters[Self::metric_index(metric)]
    }
}

// ---------------------------------------------------------------------------
// Lịch sử nhúng (kho lưu chỉ mục HNSW đơn giản hóa)
// ---------------------------------------------------------------------------

/// Mục nhập trong lịch sử nhúng.
#[derive(Debug, Clone)]
pub struct EmbeddingEntry {
    /// ID người.
    pub person_id: u64,
    /// Dấu thời gian ngày (micro giây).
    pub day_us: u64,
    /// Vector nhúng AETHER.
    pub embedding: Vec<f32>,
}

/// Kho lưu lịch sử nhúng đơn giản hóa cho theo dõi chiều dọc.
///
/// Trong sản xuất, kho này sẽ được hỗ trợ bởi chỉ mục HNSW cho tìm
/// láng giềng gần nhanh. Triển khai này dùng tương đồng cosine
/// vét cạn để đảm bảo đúng đắn.
#[derive(Debug)]
pub struct EmbeddingHistory {
    entries: Vec<EmbeddingEntry>,
    max_entries: usize,
    embedding_dim: usize,
}

impl EmbeddingHistory {
    /// Tạo kho lưu lịch sử nhúng mới.
    pub fn new(embedding_dim: usize, max_entries: usize) -> Self {
        Self {
            entries: Vec::new(),
            max_entries,
            embedding_dim,
        }
    }

    /// Thêm một mục nhập nhúng.
    pub fn push(&mut self, entry: EmbeddingEntry) -> Result<(), LongitudinalError> {
        if entry.embedding.len() != self.embedding_dim {
            return Err(LongitudinalError::EmbeddingDimensionMismatch {
                expected: self.embedding_dim,
                got: entry.embedding.len(),
            });
        }
        if self.entries.len() >= self.max_entries {
            self.entries.drain(..1); // Loại bỏ FIFO — chấp nhận được cho tốc độ chèn hàng ngày
        }
        self.entries.push(entry);
        Ok(())
    }

    /// Tìm K nhúng gần nhất với vector truy vấn (cosine vét cạn).
    pub fn search(&self, query: &[f32], k: usize) -> Vec<(usize, f32)> {
        let mut similarities: Vec<(usize, f32)> = self
            .entries
            .iter()
            .enumerate()
            .map(|(i, e)| (i, cosine_similarity(query, &e.embedding)))
            .collect();

        similarities.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        similarities.truncate(k);
        similarities
    }

    /// Số mục nhập đã lưu.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Kho lưu có trống hay không.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Lấy mục nhập theo chỉ số.
    pub fn get(&self, index: usize) -> Option<&EmbeddingEntry> {
        self.entries.get(index)
    }

    /// Lấy tất cả mục nhập cho một người cụ thể.
    pub fn entries_for_person(&self, person_id: u64) -> Vec<&EmbeddingEntry> {
        self.entries
            .iter()
            .filter(|e| e.person_id == person_id)
            .collect()
    }
}

/// Tương đồng cosine giữa hai vector f32.
fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    let denom = norm_a * norm_b;
    if denom < 1e-9 {
        0.0
    } else {
        dot / denom
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_daily_summary(person_id: u64, day: u64, values: [f64; 5]) -> DailyMetricSummary {
        DailyMetricSummary {
            person_id,
            day_us: day * 86_400_000_000,
            metrics: vec![
                (DriftMetric::GaitSymmetry, values[0]),
                (DriftMetric::StabilityIndex, values[1]),
                (DriftMetric::BreathingRegularity, values[2]),
                (DriftMetric::MicroTremor, values[3]),
                (DriftMetric::ActivityLevel, values[4]),
            ],
            embedding_centroid: None,
        }
    }

    #[test]
    fn test_personal_baseline_creation() {
        let baseline = PersonalBaseline::new(42, 128);
        assert_eq!(baseline.person_id, 42);
        assert_eq!(baseline.observation_days, 0);
        assert!(!baseline.is_ready());
        assert_eq!(baseline.embedding_centroid.len(), 128);
    }

    #[test]
    fn test_baseline_not_ready_before_7_days() {
        let mut baseline = PersonalBaseline::new(1, 128);
        for day in 0..6 {
            let summary = make_daily_summary(1, day, [0.1, 0.9, 0.15, 0.5, 0.7]);
            let reports = baseline.update_daily(&summary, day * 86_400_000_000);
            assert!(reports.is_empty(), "Không nên có trôi trước 7 ngày");
        }
        assert!(!baseline.is_ready());
    }

    #[test]
    fn test_baseline_ready_after_7_days() {
        let mut baseline = PersonalBaseline::new(1, 128);
        for day in 0..7 {
            let summary = make_daily_summary(1, day, [0.1, 0.9, 0.15, 0.5, 0.7]);
            baseline.update_daily(&summary, day * 86_400_000_000);
        }
        assert!(baseline.is_ready());
        assert_eq!(baseline.observation_days, 7);
    }

    #[test]
    fn test_stable_metrics_no_drift() {
        let mut baseline = PersonalBaseline::new(1, 128);

        // 20 ngày chỉ số ổn định
        for day in 0..20 {
            let summary = make_daily_summary(1, day, [0.1, 0.9, 0.15, 0.5, 0.7]);
            let reports = baseline.update_daily(&summary, day * 86_400_000_000);
            assert!(
                reports.is_empty(),
                "Chỉ số ổn định không nên kích hoạt trôi"
            );
        }
    }

    #[test]
    fn test_drift_detected_after_sustained_deviation() {
        let mut baseline = PersonalBaseline::new(1, 128);

        // 30 ngày đối xứng dáng đi rất ổn định = 0.1 với nhiễu nhỏ
        // (nhiều ngày cơ sở hơn = prior mạnh hơn, nên trôi giữ > 2-sigma lâu hơn)
        for day in 0..30 {
            let noise = 0.001 * (day as f64 % 3.0 - 1.0); // biến thiên nhỏ
            let summary = make_daily_summary(1, day, [0.1 + noise, 0.9, 0.15, 0.5, 0.7]);
            baseline.update_daily(&summary, day * 86_400_000_000);
        }

        // Bây giờ tiêm trôi rất lớn trong đối xứng dáng đi (0.1 -> 5.0) trong 5 ngày.
        // Ngay cả khi Welford tích lũy các giá trị này, điểm z nên giữ trên 2.0
        // vì 30 ngày cơ sở neo trung bình gần 0.1 với độ lệch chuẩn nhỏ.
        let mut any_drift = false;
        for day in 30..36 {
            let summary = make_daily_summary(1, day, [5.0, 0.9, 0.15, 0.5, 0.7]);
            let reports = baseline.update_daily(&summary, day * 86_400_000_000);
            if !reports.is_empty() {
                any_drift = true;
                let r = &reports[0];
                assert_eq!(r.metric, DriftMetric::GaitSymmetry);
                assert_eq!(r.direction, DriftDirection::Increasing);
                assert!(r.z_score > 2.0);
                assert!(r.sustained_days >= 3);
            }
        }
        assert!(any_drift, "Phải phát hiện trôi sau độ lệch duy trì");
    }

    #[test]
    fn test_drift_resolves_when_metric_returns() {
        let mut baseline = PersonalBaseline::new(1, 128);

        // Đường cơ sở ổn định
        for day in 0..10 {
            let summary = make_daily_summary(1, day, [0.1, 0.9, 0.15, 0.5, 0.7]);
            baseline.update_daily(&summary, day * 86_400_000_000);
        }

        // Trôi trong 3 ngày
        for day in 10..13 {
            let summary = make_daily_summary(1, day, [0.9, 0.9, 0.15, 0.5, 0.7]);
            baseline.update_daily(&summary, day * 86_400_000_000);
        }

        // Trở về bình thường
        for day in 13..16 {
            let summary = make_daily_summary(1, day, [0.1, 0.9, 0.15, 0.5, 0.7]);
            let reports = baseline.update_daily(&summary, day * 86_400_000_000);
            // Sau khi trở về bình thường, bộ đếm trôi đặt lại
            if day == 15 {
                assert!(reports.is_empty(), "Trôi phải được giải quyết");
                assert_eq!(baseline.drift_days(DriftMetric::GaitSymmetry), 0);
            }
        }
    }

    #[test]
    fn test_monitoring_level_escalation() {
        let mut baseline = PersonalBaseline::new(1, 128);

        // 30 ngày đường cơ sở ổn định với nhiễu nhỏ để neo thống kê
        for day in 0..30 {
            let noise = 0.001 * (day as f64 % 3.0 - 1.0);
            let summary = make_daily_summary(1, day, [0.1 + noise, 0.9, 0.15, 0.5, 0.7]);
            baseline.update_daily(&summary, day * 86_400_000_000);
        }

        // Trôi lớn duy trì 10+ ngày phải leo thang lên RiskCorrelation.
        // Dùng giá trị 10.0 (so với cơ sở ~0.1) để đảm bảo điểm z giữ trên 2.0
        // ngay cả khi Welford tích lũy các giá trị trôi.
        let mut max_level = MonitoringLevel::Physiological;
        for day in 30..42 {
            let summary = make_daily_summary(1, day, [10.0, 0.9, 0.15, 0.5, 0.7]);
            let reports = baseline.update_daily(&summary, day * 86_400_000_000);
            for r in &reports {
                if r.level > max_level {
                    max_level = r.level;
                }
            }
        }
        assert_eq!(
            max_level,
            MonitoringLevel::RiskCorrelation,
            "Trôi duy trì 7+ ngày phải đạt mức RiskCorrelation"
        );
    }

    #[test]
    fn test_embedding_history_push_and_search() {
        let mut history = EmbeddingHistory::new(4, 100);

        history
            .push(EmbeddingEntry {
                person_id: 1,
                day_us: 0,
                embedding: vec![1.0, 0.0, 0.0, 0.0],
            })
            .unwrap();
        history
            .push(EmbeddingEntry {
                person_id: 1,
                day_us: 1,
                embedding: vec![0.9, 0.1, 0.0, 0.0],
            })
            .unwrap();
        history
            .push(EmbeddingEntry {
                person_id: 2,
                day_us: 0,
                embedding: vec![0.0, 0.0, 1.0, 0.0],
            })
            .unwrap();

        let results = history.search(&[1.0, 0.0, 0.0, 0.0], 2);
        assert_eq!(results.len(), 2);
        // Kết quả đầu tiên phải là khớp chính xác
        assert!((results[0].1 - 1.0).abs() < 1e-5);
    }

    #[test]
    fn test_embedding_history_dimension_mismatch() {
        let mut history = EmbeddingHistory::new(4, 100);
        let result = history.push(EmbeddingEntry {
            person_id: 1,
            day_us: 0,
            embedding: vec![1.0, 0.0], // chiều sai
        });
        assert!(matches!(
            result,
            Err(LongitudinalError::EmbeddingDimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_embedding_history_fifo_eviction() {
        let mut history = EmbeddingHistory::new(2, 3);
        for i in 0..5 {
            history
                .push(EmbeddingEntry {
                    person_id: 1,
                    day_us: i,
                    embedding: vec![i as f32, 0.0],
                })
                .unwrap();
        }
        assert_eq!(history.len(), 3);
        // Mục nhập đầu tiên phải là ngày 2 (0 và 1 đã bị loại)
        assert_eq!(history.get(0).unwrap().day_us, 2);
    }

    #[test]
    fn test_entries_for_person() {
        let mut history = EmbeddingHistory::new(2, 100);
        history
            .push(EmbeddingEntry {
                person_id: 1,
                day_us: 0,
                embedding: vec![1.0, 0.0],
            })
            .unwrap();
        history
            .push(EmbeddingEntry {
                person_id: 2,
                day_us: 0,
                embedding: vec![0.0, 1.0],
            })
            .unwrap();
        history
            .push(EmbeddingEntry {
                person_id: 1,
                day_us: 1,
                embedding: vec![0.9, 0.1],
            })
            .unwrap();

        let entries = history.entries_for_person(1);
        assert_eq!(entries.len(), 2);
    }

    #[test]
    fn test_drift_metric_names() {
        assert_eq!(DriftMetric::GaitSymmetry.name(), "gait_symmetry");
        assert_eq!(DriftMetric::ActivityLevel.name(), "activity_level");
        assert_eq!(DriftMetric::all().len(), 5);
    }

    #[test]
    fn test_cosine_similarity_unit_vectors() {
        let a = vec![1.0_f32, 0.0, 0.0];
        let b = vec![0.0_f32, 1.0, 0.0];
        assert!(cosine_similarity(&a, &b).abs() < 1e-6, "Trực giao = 0");

        let c = vec![1.0_f32, 0.0, 0.0];
        assert!((cosine_similarity(&a, &c) - 1.0).abs() < 1e-6, "Cùng hướng = 1");
    }
}
