//! Chính Sách Cập Nhật Cổng Tương Hợp (ADR-029 Mục 2.6)
//!
//! Áp dụng quy tắc cổng dựa trên ngưỡng cho điểm tương hợp, tạo ra
//! một `GateDecision` điều khiển cập nhật bộ lọc Kalman phía sau:
//!
//! - **Chấp Nhận** (tương hợp > 0.85): Cập nhật đo lường đầy đủ với nhiễu danh nghĩa.
//! - **Chỉ Dự Đoán** (0.5 < tương hợp < 0.85): Chỉ chạy bước dự đoán Kalman,
//!   nhiễu đo lường tăng gấp 3x.
//! - **Từ Chối** (tương hợp < 0.5): Loại bỏ hoàn toàn đo lường.
//! - **Hiệu Chuẩn Lại** (>10s tương hợp thấp liên tục): Kích hoạt pipeline
//!   hiệu chuẩn lại SONA/AETHER.
//!
//! Cổng hoạt động trên điểm tương hợp do module `coherence` tạo ra
//! và bộ đếm khung cũ từ `CoherenceState`.

/// Quyết định cổng điều khiển hành vi cập nhật bộ lọc Kalman.
#[derive(Debug, Clone, PartialEq)]
pub enum GateDecision {
    /// Tương hợp cao. Tiến hành cập nhật đo lường Kalman đầy đủ.
    /// Chứa hệ số nhân nhiễu đo lường tăng (1.0 = danh nghĩa).
    Accept {
        /// Hệ số nhân nhiễu đo lường (1.0 cho chấp nhận đầy đủ).
        noise_multiplier: f32,
    },

    /// Tương hợp trung bình. Chỉ chạy dự đoán Kalman (không cập nhật đo lường).
    /// Nhiễu đo lường sẽ tăng gấp 3x nếu sử dụng.
    PredictOnly,

    /// Tương hợp thấp. Từ chối hoàn toàn đo lường này.
    Reject,

    /// Tương hợp thấp kéo dài. Kích hoạt hiệu chuẩn lại môi trường.
    /// Pipeline nên đóng băng đầu ra ở tư thế tốt cuối cùng và
    /// bắt đầu chu kỳ thích ứng TTT SONA/AETHER.
    Recalibrate {
        /// Thời lượng tương hợp thấp tính bằng khung.
        stale_frames: u64,
    },
}

impl GateDecision {
    /// Trả về true nếu quyết định này cho phép cập nhật đo lường.
    pub fn allows_update(&self) -> bool {
        matches!(self, GateDecision::Accept { .. })
    }

    /// Trả về true nếu đây là quyết định từ chối hoặc hiệu chuẩn lại.
    pub fn is_rejected(&self) -> bool {
        matches!(self, GateDecision::Reject | GateDecision::Recalibrate { .. })
    }

    /// Trả về hệ số nhân nhiễu cho quyết định chấp nhận, hoặc None nếu không.
    pub fn noise_multiplier(&self) -> Option<f32> {
        match self {
            GateDecision::Accept { noise_multiplier } => Some(*noise_multiplier),
            _ => None,
        }
    }
}

/// Cấu hình cho các ngưỡng chính sách cổng.
#[derive(Debug, Clone)]
pub struct GatePolicyConfig {
    /// Ngưỡng tương hợp để chấp nhận đo lường.
    pub accept_threshold: f32,
    /// Ngưỡng tương hợp để từ chối đo lường.
    pub reject_threshold: f32,
    /// Số khung cũ tối đa trước khi kích hoạt hiệu chuẩn lại.
    pub max_stale_frames: u64,
    /// Hệ số tăng nhiễu cho vùng Chỉ Dự Đoán.
    pub predict_only_noise: f32,
    /// Có sử dụng ngưỡng thích ứng dựa trên hồ sơ trôi hay không.
    pub adaptive: bool,
}

impl Default for GatePolicyConfig {
    fn default() -> Self {
        Self {
            accept_threshold: 0.85,
            reject_threshold: 0.5,
            max_stale_frames: 200, // 10s ở 20Hz
            predict_only_noise: 3.0,
            adaptive: false,
        }
    }
}

/// Chính sách cổng ánh xạ điểm tương hợp sang quyết định cổng.
#[derive(Debug, Clone)]
pub struct GatePolicy {
    /// Ngưỡng chấp nhận.
    accept_threshold: f32,
    /// Ngưỡng từ chối.
    reject_threshold: f32,
    /// Số khung cũ tối đa trước khi hiệu chuẩn lại.
    max_stale_frames: u64,
    /// Tăng nhiễu cho vùng chỉ dự đoán.
    predict_only_noise: f32,
    /// Bộ đếm chạy của các khung tương hợp thấp liên tiếp.
    consecutive_low: u64,
    /// Quyết định gần nhất để theo dõi chuyển đổi.
    last_decision: Option<GateDecision>,
}

impl GatePolicy {
    /// Tạo chính sách cổng với các ngưỡng cho trước.
    pub fn new(accept: f32, reject: f32, max_stale: u64) -> Self {
        Self {
            accept_threshold: accept,
            reject_threshold: reject,
            max_stale_frames: max_stale,
            predict_only_noise: 3.0,
            consecutive_low: 0,
            last_decision: None,
        }
    }

    /// Tạo chính sách cổng từ cấu hình.
    pub fn from_config(config: &GatePolicyConfig) -> Self {
        Self {
            accept_threshold: config.accept_threshold,
            reject_threshold: config.reject_threshold,
            max_stale_frames: config.max_stale_frames,
            predict_only_noise: config.predict_only_noise,
            consecutive_low: 0,
            last_decision: None,
        }
    }

    /// Đánh giá quyết định cổng cho điểm tương hợp và số khung cũ cho trước.
    pub fn evaluate(&mut self, coherence_score: f32, stale_count: u64) -> GateDecision {
        let decision = if stale_count >= self.max_stale_frames {
            GateDecision::Recalibrate {
                stale_frames: stale_count,
            }
        } else if coherence_score >= self.accept_threshold {
            self.consecutive_low = 0;
            GateDecision::Accept {
                noise_multiplier: 1.0,
            }
        } else if coherence_score >= self.reject_threshold {
            self.consecutive_low += 1;
            GateDecision::PredictOnly
        } else {
            self.consecutive_low += 1;
            GateDecision::Reject
        };

        self.last_decision = Some(decision.clone());
        decision
    }

    /// Trả về quyết định cổng gần nhất, nếu có.
    pub fn last_decision(&self) -> Option<&GateDecision> {
        self.last_decision.as_ref()
    }

    /// Trả về bộ đếm hiện tại của các khung tương hợp thấp liên tiếp.
    pub fn consecutive_low_count(&self) -> u64 {
        self.consecutive_low
    }

    /// Trả về ngưỡng chấp nhận.
    pub fn accept_threshold(&self) -> f32 {
        self.accept_threshold
    }

    /// Trả về ngưỡng từ chối.
    pub fn reject_threshold(&self) -> f32 {
        self.reject_threshold
    }

    /// Đặt lại trạng thái chính sách (ví dụ: sau hiệu chuẩn lại).
    pub fn reset(&mut self) {
        self.consecutive_low = 0;
        self.last_decision = None;
    }
}

impl Default for GatePolicy {
    fn default() -> Self {
        Self::from_config(&GatePolicyConfig::default())
    }
}

/// Tính hệ số nhân nhiễu thích ứng cho vùng Chỉ Dự Đoán.
///
/// Khi tương hợp giảm từ ngưỡng chấp nhận đến ngưỡng từ chối, hệ số nhân
/// nhiễu tăng từ 1.0 đến `max_inflation`.
pub fn adaptive_noise_multiplier(
    coherence: f32,
    accept: f32,
    reject: f32,
    max_inflation: f32,
) -> f32 {
    if coherence >= accept {
        return 1.0;
    }
    if coherence <= reject {
        return max_inflation;
    }
    let range = accept - reject;
    if range < 1e-6 {
        return max_inflation;
    }
    let t = (accept - coherence) / range;
    1.0 + t * (max_inflation - 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accept_high_coherence() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.95, 0);
        assert!(matches!(decision, GateDecision::Accept { noise_multiplier } if (noise_multiplier - 1.0).abs() < f32::EPSILON));
        assert!(decision.allows_update());
        assert!(!decision.is_rejected());
    }

    #[test]
    fn predict_only_moderate_coherence() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.7, 0);
        assert!(matches!(decision, GateDecision::PredictOnly));
        assert!(!decision.allows_update());
        assert!(!decision.is_rejected());
    }

    #[test]
    fn reject_low_coherence() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.3, 0);
        assert!(matches!(decision, GateDecision::Reject));
        assert!(!decision.allows_update());
        assert!(decision.is_rejected());
    }

    #[test]
    fn recalibrate_after_stale_timeout() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.3, 200);
        assert!(matches!(decision, GateDecision::Recalibrate { stale_frames: 200 }));
        assert!(decision.is_rejected());
    }

    #[test]
    fn recalibrate_overrides_accept() {
        let mut gate = GatePolicy::new(0.85, 0.5, 100);
        // Ngay cả với tương hợp cao, số khung cũ kích hoạt hiệu chuẩn lại
        let decision = gate.evaluate(0.95, 100);
        assert!(matches!(decision, GateDecision::Recalibrate { .. }));
    }

    #[test]
    fn consecutive_low_counter() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        gate.evaluate(0.3, 0);
        assert_eq!(gate.consecutive_low_count(), 1);
        gate.evaluate(0.6, 0);
        assert_eq!(gate.consecutive_low_count(), 2);
        gate.evaluate(0.9, 0); // chấp nhận -> đặt lại
        assert_eq!(gate.consecutive_low_count(), 0);
    }

    #[test]
    fn last_decision_tracked() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        assert!(gate.last_decision().is_none());
        gate.evaluate(0.9, 0);
        assert!(gate.last_decision().is_some());
    }

    #[test]
    fn reset_clears_state() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        gate.evaluate(0.3, 0);
        gate.evaluate(0.3, 0);
        gate.reset();
        assert_eq!(gate.consecutive_low_count(), 0);
        assert!(gate.last_decision().is_none());
    }

    #[test]
    fn noise_multiplier_accessor() {
        let accept = GateDecision::Accept { noise_multiplier: 2.5 };
        assert_eq!(accept.noise_multiplier(), Some(2.5));

        let reject = GateDecision::Reject;
        assert_eq!(reject.noise_multiplier(), None);

        let predict = GateDecision::PredictOnly;
        assert_eq!(predict.noise_multiplier(), None);
    }

    #[test]
    fn adaptive_noise_at_boundaries() {
        assert!((adaptive_noise_multiplier(0.9, 0.85, 0.5, 3.0) - 1.0).abs() < f32::EPSILON);
        assert!((adaptive_noise_multiplier(0.3, 0.85, 0.5, 3.0) - 3.0).abs() < f32::EPSILON);
    }

    #[test]
    fn adaptive_noise_midpoint() {
        let mid = adaptive_noise_multiplier(0.675, 0.85, 0.5, 3.0);
        assert!((mid - 2.0).abs() < 0.01, "Nhiễu tại điểm giữa phải xấp xỉ 2.0, nhận được {}", mid);
    }

    #[test]
    fn adaptive_noise_tiny_range() {
        // Khi accept == reject, tương hợp >= accept trả về 1.0
        let val = adaptive_noise_multiplier(0.5, 0.5, 0.5, 3.0);
        assert!((val - 1.0).abs() < f32::EPSILON);
        // Dưới cả hai ngưỡng phải trả về max_inflation
        let val2 = adaptive_noise_multiplier(0.4, 0.5, 0.5, 3.0);
        assert!((val2 - 3.0).abs() < f32::EPSILON);
    }

    #[test]
    fn default_config_values() {
        let cfg = GatePolicyConfig::default();
        assert!((cfg.accept_threshold - 0.85).abs() < f32::EPSILON);
        assert!((cfg.reject_threshold - 0.5).abs() < f32::EPSILON);
        assert_eq!(cfg.max_stale_frames, 200);
        assert!((cfg.predict_only_noise - 3.0).abs() < f32::EPSILON);
        assert!(!cfg.adaptive);
    }

    #[test]
    fn from_config_construction() {
        let cfg = GatePolicyConfig {
            accept_threshold: 0.9,
            reject_threshold: 0.4,
            max_stale_frames: 100,
            predict_only_noise: 5.0,
            adaptive: true,
        };
        let gate = GatePolicy::from_config(&cfg);
        assert!((gate.accept_threshold() - 0.9).abs() < f32::EPSILON);
        assert!((gate.reject_threshold() - 0.4).abs() < f32::EPSILON);
    }

    #[test]
    fn boundary_at_exact_accept_threshold() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.85, 0);
        assert!(matches!(decision, GateDecision::Accept { .. }));
    }

    #[test]
    fn boundary_at_exact_reject_threshold() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.5, 0);
        assert!(matches!(decision, GateDecision::PredictOnly));
    }

    #[test]
    fn boundary_just_below_reject_threshold() {
        let mut gate = GatePolicy::new(0.85, 0.5, 200);
        let decision = gate.evaluate(0.499, 0);
        assert!(matches!(decision, GateDecision::Reject));
    }
}
