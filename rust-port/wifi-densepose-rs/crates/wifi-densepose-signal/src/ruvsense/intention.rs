//! Bộ phát hiện tín hiệu dẫn trước ý định chuyển động.
//!
//! Phát hiện điều chỉnh tư thế dự báo (APA) 200-500ms trước khi
//! chuyển động bắt đầu nhìn thấy được. Hoạt động bằng cách phân tích
//! quỹ đạo nhúng AETHER trong không gian nhúng: trước khi một người
//! bắt đầu bước hoặc vươn tay, việc chuyển trọng lượng tạo ra thay đổi
//! CSI tinh tế xuất hiện dưới dạng vận tốc và gia tốc trong không gian nhúng.
//!
//! # Thuật toán
//! 1. Duy trì cửa sổ trượt của các nhúng gần đây (2 giây ở 20 Hz)
//! 2. Tính vận tốc (đạo hàm bậc nhất) và gia tốc (đạo hàm bậc hai)
//!    trong không gian nhúng
//! 3. Phát hiện khi gia tốc vượt ngưỡng trong khi vận tốc vẫn thấp
//!    (cơ thể đang nạp/chuyển nhưng chưa di chuyển)
//! 4. Xuất tín hiệu dẫn trước với thời gian ước lượng đến chuyển động
//!
//! # Tài liệu tham khảo
//! - ADR-030 Tier 3: Tín hiệu dẫn trước ý định
//! - Massion (1992), "Movement, posture and equilibrium: Interaction
//!   and coordination" Progress in Neurobiology

use std::collections::VecDeque;

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ thao tác phát hiện ý định.
#[derive(Debug, thiserror::Error)]
pub enum IntentionError {
    /// Không đủ lịch sử nhúng để tính đạo hàm.
    #[error("Không đủ lịch sử: cần >= {needed} khung, có {got}")]
    InsufficientHistory { needed: usize, got: usize },

    /// Chiều nhúng không khớp.
    #[error("Chiều nhúng không khớp: kỳ vọng {expected}, nhận được {got}")]
    DimensionMismatch { expected: usize, got: usize },

    /// Cấu hình không hợp lệ.
    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho bộ phát hiện ý định.
#[derive(Debug, Clone)]
pub struct IntentionConfig {
    /// Chiều nhúng (thường là 128).
    pub embedding_dim: usize,
    /// Kích thước cửa sổ trượt theo khung (2 giây ở 20Hz = 40 khung).
    pub window_size: usize,
    /// Tần số lấy mẫu tính bằng Hz.
    pub sample_rate_hz: f64,
    /// Ngưỡng gia tốc cho phát hiện tiền chuyển động (đơn vị không gian nhúng/s^2).
    pub acceleration_threshold: f64,
    /// Vận tốc tối đa cho tín hiệu tiền chuyển động (dưới mức này = vẫn đang chuẩn bị).
    pub max_pre_movement_velocity: f64,
    /// Số khung gia tốc duy trì tối thiểu để kích hoạt tín hiệu dẫn trước.
    pub min_sustained_frames: usize,
    /// Cửa sổ thời gian dẫn trước: số giây tối đa trước chuyển động mà ta đánh dấu.
    pub max_lead_time_s: f64,
}

impl Default for IntentionConfig {
    fn default() -> Self {
        Self {
            embedding_dim: 128,
            window_size: 40,
            sample_rate_hz: 20.0,
            acceleration_threshold: 0.5,
            max_pre_movement_velocity: 2.0,
            min_sustained_frames: 4,
            max_lead_time_s: 0.5,
        }
    }
}

// ---------------------------------------------------------------------------
// Kết quả tín hiệu dẫn trước
// ---------------------------------------------------------------------------

/// Tín hiệu dẫn trước tiền chuyển động.
#[derive(Debug, Clone)]
pub struct LeadSignal {
    /// Tín hiệu tiền chuyển động có được phát hiện hay không.
    pub detected: bool,
    /// Độ tin cậy trong phát hiện (0.0 đến 1.0).
    pub confidence: f64,
    /// Thời gian ước lượng đến khi chuyển động bắt đầu (giây).
    pub estimated_lead_time_s: f64,
    /// Biên độ vận tốc hiện tại trong không gian nhúng.
    pub velocity_magnitude: f64,
    /// Biên độ gia tốc hiện tại trong không gian nhúng.
    pub acceleration_magnitude: f64,
    /// Số khung liên tiếp có gia tốc duy trì.
    pub sustained_frames: usize,
    /// Dấu thời gian (micro giây) của phát hiện này.
    pub timestamp_us: u64,
    /// Hướng gia tốc chủ đạo (vector đơn vị trong không gian nhúng, 3 chiều đầu).
    pub direction_hint: [f64; 3],
}

/// Trạng thái quỹ đạo cho một khung.
#[derive(Debug, Clone)]
struct TrajectoryPoint {
    embedding: Vec<f64>,
    timestamp_us: u64,
}

// ---------------------------------------------------------------------------
// Bộ phát hiện ý định
// ---------------------------------------------------------------------------

/// Bộ phát hiện tín hiệu dẫn trước ý định tiền chuyển động.
///
/// Duy trì cửa sổ trượt của các nhúng và tính vận tốc
/// cùng gia tốc trong không gian nhúng để phát hiện điều chỉnh
/// tư thế dự báo trước khi chuyển động bắt đầu.
#[derive(Debug)]
pub struct IntentionDetector {
    config: IntentionConfig,
    /// Cửa sổ trượt các điểm quỹ đạo gần đây.
    history: VecDeque<TrajectoryPoint>,
    /// Đếm số khung liên tiếp có dấu hiệu tiền chuyển động.
    sustained_count: usize,
    /// Tổng số khung đã xử lý.
    total_frames: u64,
}

impl IntentionDetector {
    /// Tạo bộ phát hiện ý định mới.
    pub fn new(config: IntentionConfig) -> Result<Self, IntentionError> {
        if config.embedding_dim == 0 {
            return Err(IntentionError::InvalidConfig(
                "embedding_dim phải > 0".into(),
            ));
        }
        if config.window_size < 3 {
            return Err(IntentionError::InvalidConfig(
                "window_size phải >= 3 cho đạo hàm bậc hai".into(),
            ));
        }
        Ok(Self {
            history: VecDeque::with_capacity(config.window_size),
            config,
            sustained_count: 0,
            total_frames: 0,
        })
    }

    /// Nạp một nhúng mới và kiểm tra tín hiệu tiền chuyển động.
    ///
    /// `embedding` là nhúng AETHER cho khung hiện tại.
    /// Trả về kết quả tín hiệu dẫn trước.
    pub fn update(
        &mut self,
        embedding: &[f32],
        timestamp_us: u64,
    ) -> Result<LeadSignal, IntentionError> {
        if embedding.len() != self.config.embedding_dim {
            return Err(IntentionError::DimensionMismatch {
                expected: self.config.embedding_dim,
                got: embedding.len(),
            });
        }

        self.total_frames += 1;

        // Chuyển sang f64 cho phân tích quỹ đạo
        let emb_f64: Vec<f64> = embedding.iter().map(|&x| x as f64).collect();

        // Thêm vào lịch sử
        if self.history.len() >= self.config.window_size {
            self.history.pop_front();
        }
        self.history.push_back(TrajectoryPoint {
            embedding: emb_f64,
            timestamp_us,
        });

        // Cần ít nhất 3 điểm cho đạo hàm bậc hai
        if self.history.len() < 3 {
            return Ok(LeadSignal {
                detected: false,
                confidence: 0.0,
                estimated_lead_time_s: 0.0,
                velocity_magnitude: 0.0,
                acceleration_magnitude: 0.0,
                sustained_frames: 0,
                timestamp_us,
                direction_hint: [0.0; 3],
            });
        }

        // Tính vận tốc và gia tốc
        let n = self.history.len();
        let dt = 1.0 / self.config.sample_rate_hz;

        // Vận tốc: (embedding[n-1] - embedding[n-2]) / dt
        let velocity = embedding_diff(
            &self.history[n - 1].embedding,
            &self.history[n - 2].embedding,
            dt,
        );
        let velocity_mag = l2_norm_f64(&velocity);

        // Gia tốc: (velocity[n-1] - velocity[n-2]) / dt
        // Xấp xỉ: (emb[n-1] - 2*emb[n-2] + emb[n-3]) / dt^2
        let acceleration = embedding_second_diff(
            &self.history[n - 1].embedding,
            &self.history[n - 2].embedding,
            &self.history[n - 3].embedding,
            dt,
        );
        let accel_mag = l2_norm_f64(&acceleration);

        // Phát hiện tiền chuyển động:
        // Gia tốc cao + vận tốc thấp = cơ thể đang nạp/chuyển nhưng chưa di chuyển
        let is_pre_movement = accel_mag > self.config.acceleration_threshold
            && velocity_mag < self.config.max_pre_movement_velocity;

        if is_pre_movement {
            self.sustained_count += 1;
        } else {
            self.sustained_count = 0;
        }

        let detected = self.sustained_count >= self.config.min_sustained_frames;

        // Ước lượng thời gian dẫn trước dựa trên gia tốc và vận tốc hiện tại
        let estimated_lead = if detected && accel_mag > 1e-10 {
            // Thời gian cho đến khi vận tốc đạt ngưỡng: t = (v_ngưỡng - v) / a
            let remaining = (self.config.max_pre_movement_velocity - velocity_mag) / accel_mag;
            remaining.clamp(0.0, self.config.max_lead_time_s)
        } else {
            0.0
        };

        // Độ tin cậy dựa trên mức gia tốc vượt ngưỡng rõ ràng đến đâu
        let confidence = if detected {
            let ratio = accel_mag / self.config.acceleration_threshold;
            (ratio - 1.0).clamp(0.0, 1.0)
                * (self.sustained_count as f64 / self.config.min_sustained_frames as f64).min(1.0)
        } else {
            0.0
        };

        // Gợi ý hướng từ 3 chiều đầu của gia tốc
        let direction_hint = [
            acceleration.first().copied().unwrap_or(0.0),
            acceleration.get(1).copied().unwrap_or(0.0),
            acceleration.get(2).copied().unwrap_or(0.0),
        ];

        Ok(LeadSignal {
            detected,
            confidence,
            estimated_lead_time_s: estimated_lead,
            velocity_magnitude: velocity_mag,
            acceleration_magnitude: accel_mag,
            sustained_frames: self.sustained_count,
            timestamp_us,
            direction_hint,
        })
    }

    /// Đặt lại trạng thái bộ phát hiện.
    pub fn reset(&mut self) {
        self.history.clear();
        self.sustained_count = 0;
    }

    /// Số khung trong lịch sử.
    pub fn history_len(&self) -> usize {
        self.history.len()
    }

    /// Tổng số khung đã xử lý.
    pub fn total_frames(&self) -> u64 {
        self.total_frames
    }
}

// ---------------------------------------------------------------------------
// Hàm tiện ích
// ---------------------------------------------------------------------------

/// Hiệu bậc nhất của hai vector nhúng, chia cho dt.
fn embedding_diff(a: &[f64], b: &[f64], dt: f64) -> Vec<f64> {
    a.iter()
        .zip(b.iter())
        .map(|(&ai, &bi)| (ai - bi) / dt)
        .collect()
}

/// Hiệu bậc hai: (a - 2b + c) / dt^2.
fn embedding_second_diff(a: &[f64], b: &[f64], c: &[f64], dt: f64) -> Vec<f64> {
    let dt2 = dt * dt;
    a.iter()
        .zip(b.iter())
        .zip(c.iter())
        .map(|((&ai, &bi), &ci)| (ai - 2.0 * bi + ci) / dt2)
        .collect()
}

/// Chuẩn L2 của một lát f64.
fn l2_norm_f64(v: &[f64]) -> f64 {
    v.iter().map(|x| x * x).sum::<f64>().sqrt()
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_config() -> IntentionConfig {
        IntentionConfig {
            embedding_dim: 4,
            window_size: 10,
            sample_rate_hz: 20.0,
            acceleration_threshold: 0.5,
            max_pre_movement_velocity: 2.0,
            min_sustained_frames: 3,
            max_lead_time_s: 0.5,
        }
    }

    fn static_embedding() -> Vec<f32> {
        vec![1.0, 0.0, 0.0, 0.0]
    }

    #[test]
    fn test_creation() {
        let config = make_config();
        let detector = IntentionDetector::new(config).unwrap();
        assert_eq!(detector.history_len(), 0);
        assert_eq!(detector.total_frames(), 0);
    }

    #[test]
    fn test_invalid_config_zero_dim() {
        let config = IntentionConfig {
            embedding_dim: 0,
            ..make_config()
        };
        assert!(matches!(
            IntentionDetector::new(config),
            Err(IntentionError::InvalidConfig(_))
        ));
    }

    #[test]
    fn test_invalid_config_small_window() {
        let config = IntentionConfig {
            window_size: 2,
            ..make_config()
        };
        assert!(matches!(
            IntentionDetector::new(config),
            Err(IntentionError::InvalidConfig(_))
        ));
    }

    #[test]
    fn test_dimension_mismatch() {
        let config = make_config();
        let mut detector = IntentionDetector::new(config).unwrap();
        let result = detector.update(&[1.0, 0.0], 0);
        assert!(matches!(
            result,
            Err(IntentionError::DimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_static_scene_no_detection() {
        let config = make_config();
        let mut detector = IntentionDetector::new(config).unwrap();

        for frame in 0..20 {
            let signal = detector
                .update(&static_embedding(), frame * 50_000)
                .unwrap();
            assert!(
                !signal.detected,
                "Cảnh tĩnh không nên kích hoạt phát hiện"
            );
        }
    }

    #[test]
    fn test_gradual_acceleration_detected() {
        let mut config = make_config();
        config.acceleration_threshold = 100.0; // ngưỡng thấp cho kiểm thử
        config.max_pre_movement_velocity = 100000.0;
        config.min_sustained_frames = 2;

        let mut detector = IntentionDetector::new(config).unwrap();

        // Nạp các nhúng gia tốc dần
        // Vị trí = 0.5 * a * t^2, nên nhúng dịch theo bậc hai
        let mut any_detected = false;
        for frame in 0..30_u64 {
            let t = frame as f32 * 0.05;
            let pos = 50.0 * t * t; // gia tốc = 100 đơn vị/s^2
            let emb = vec![1.0 + pos, 0.0, 0.0, 0.0];
            let signal = detector.update(&emb, frame * 50_000).unwrap();
            if signal.detected {
                any_detected = true;
                assert!(signal.confidence > 0.0);
                assert!(signal.acceleration_magnitude > 0.0);
            }
        }
        assert!(any_detected, "Tín hiệu gia tốc phải kích hoạt phát hiện");
    }

    #[test]
    fn test_constant_velocity_no_detection() {
        let config = make_config();
        let mut detector = IntentionDetector::new(config).unwrap();

        // Vận tốc không đổi = gia tốc bằng 0 → không có tiền chuyển động
        for frame in 0..20_u64 {
            let pos = frame as f32 * 0.01; // vận tốc không đổi
            let emb = vec![1.0 + pos, 0.0, 0.0, 0.0];
            let signal = detector.update(&emb, frame * 50_000).unwrap();
            assert!(
                !signal.detected,
                "Vận tốc không đổi không nên kích hoạt tiền chuyển động"
            );
        }
    }

    #[test]
    fn test_reset() {
        let config = make_config();
        let mut detector = IntentionDetector::new(config).unwrap();

        for frame in 0..5_u64 {
            detector
                .update(&static_embedding(), frame * 50_000)
                .unwrap();
        }
        assert_eq!(detector.history_len(), 5);

        detector.reset();
        assert_eq!(detector.history_len(), 0);
    }

    #[test]
    fn test_lead_signal_fields() {
        let config = make_config();
        let mut detector = IntentionDetector::new(config).unwrap();

        // Cần ít nhất 3 khung cho đạo hàm
        for frame in 0..3_u64 {
            let signal = detector
                .update(&static_embedding(), frame * 50_000)
                .unwrap();
            assert_eq!(signal.sustained_frames, 0);
        }

        let signal = detector.update(&static_embedding(), 150_000).unwrap();
        assert!(signal.velocity_magnitude >= 0.0);
        assert!(signal.acceleration_magnitude >= 0.0);
        assert_eq!(signal.direction_hint.len(), 3);
    }

    #[test]
    fn test_window_size_limit() {
        let config = IntentionConfig {
            window_size: 5,
            ..make_config()
        };
        let mut detector = IntentionDetector::new(config).unwrap();

        for frame in 0..10_u64 {
            detector
                .update(&static_embedding(), frame * 50_000)
                .unwrap();
        }
        assert_eq!(detector.history_len(), 5);
    }

    #[test]
    fn test_embedding_diff() {
        let a = vec![2.0, 4.0];
        let b = vec![1.0, 2.0];
        let diff = embedding_diff(&a, &b, 0.5);
        assert!((diff[0] - 2.0).abs() < 1e-10); // (2-1)/0.5
        assert!((diff[1] - 4.0).abs() < 1e-10); // (4-2)/0.5
    }

    #[test]
    fn test_embedding_second_diff() {
        // Chuỗi bậc hai: 1, 4, 9 → hiệu bậc hai = 2
        let a = vec![9.0];
        let b = vec![4.0];
        let c = vec![1.0];
        let sd = embedding_second_diff(&a, &b, &c, 1.0);
        assert!((sd[0] - 2.0).abs() < 1e-10);
    }
}
