//! RuvSense -- Chế Độ RF Ưu Tiên Cảm Biến cho WiFi DensePose Đa Tĩnh (ADR-029)
//!
//! Bounded context này triển khai pipeline cảm biến đa tĩnh kết hợp
//! CSI từ nhiều node ESP32 trên nhiều kênh WiFi thành một khung
//! cảm biến nhất quán mỗi chu kỳ TDMA 50 ms (đầu ra 20 Hz).
//!
//! # Kiến Trúc
//!
//! Pipeline chạy qua sáu giai đoạn:
//!
//! 1. **Kết Hợp Đa Băng** (`multiband`) -- Tổng hợp các khung CSI theo kênh
//!    từ nhảy kênh thành ảnh chụp ảo băng rộng cho mỗi node.
//! 2. **Căn Chỉnh Pha** (`phase_align`) -- Sửa xoay pha do LO gây ra
//!    giữa các kênh sử dụng `ruvector-solver::NeumannSolver`.
//! 3. **Kết Hợp Đa Tĩnh** (`multistatic`) -- Kết hợp N quan sát node thành
//!    một `FusedSensingFrame` duy nhất với trọng số chú ý chéo node
//!    qua `ruvector-attn-mincut`.
//! 4. **Chấm Điểm Tương Hợp** (`coherence`) -- Tính điểm tương hợp z-score
//!    theo sóng mang con so với mẫu tham chiếu cuốn.
//! 5. **Cổng Tương Hợp** (`coherence_gate`) -- Áp dụng quyết định cổng
//!    dựa trên ngưỡng: Chấp Nhận / Chỉ Dự Đoán / Từ Chối / Hiệu Chuẩn Lại.
//! 6. **Theo Dõi Tư Thế** (`pose_tracker`) -- Bộ theo dõi Kalman 17 điểm khớp với
//!    máy trạng thái vòng đời và hỗ trợ nhúng tái nhận dạng AETHER.
//!
//! # Sử Dụng Crate RuVector
//!
//! - `ruvector-solver` -- Căn chỉnh pha, phân tách tương hợp
//! - `ruvector-attn-mincut` -- Kết hợp phổ chéo node
//! - `ruvector-mincut` -- Tách người và gán theo dõi
//! - `ruvector-attention` -- Trọng số đặc trưng chéo kênh
//!
//! # Tham Khảo
//!
//! - ADR-029: Dự Án RuvSense
//! - IEEE 802.11bf-2024 Cảm Biến WLAN

// ADR-030: Các tầng cảm biến nâng cao
pub mod adversarial;
pub mod cross_room;
pub mod field_model;
pub mod gesture;
pub mod intention;
pub mod longitudinal;
pub mod tomography;

// ADR-032a: Cảm biến nâng cao Midstreamer
pub mod temporal_gesture;
pub mod attractor_drift;

// ADR-029: Pipeline đa tĩnh cốt lõi
pub mod coherence;
pub mod coherence_gate;
pub mod multiband;
pub mod multistatic;
pub mod phase_align;
pub mod pose_tracker;

// Tái xuất các kiểu cốt lõi để truy cập thuận tiện
pub use coherence::CoherenceState;
pub use coherence_gate::{GateDecision, GatePolicy};
pub use multiband::MultiBandCsiFrame;
pub use multistatic::FusedSensingFrame;
pub use phase_align::{PhaseAligner, PhaseAlignError};
pub use pose_tracker::{KeypointState, PoseTrack, TrackLifecycleState};

/// Số điểm khớp trong khung xương tư thế toàn thân (COCO-17).
pub const NUM_KEYPOINTS: usize = 17;

/// Chỉ số điểm khớp theo quy ước COCO-17.
pub mod keypoint {
    pub const NOSE: usize = 0;
    pub const LEFT_EYE: usize = 1;
    pub const RIGHT_EYE: usize = 2;
    pub const LEFT_EAR: usize = 3;
    pub const RIGHT_EAR: usize = 4;
    pub const LEFT_SHOULDER: usize = 5;
    pub const RIGHT_SHOULDER: usize = 6;
    pub const LEFT_ELBOW: usize = 7;
    pub const RIGHT_ELBOW: usize = 8;
    pub const LEFT_WRIST: usize = 9;
    pub const RIGHT_WRIST: usize = 10;
    pub const LEFT_HIP: usize = 11;
    pub const RIGHT_HIP: usize = 12;
    pub const LEFT_KNEE: usize = 13;
    pub const RIGHT_KNEE: usize = 14;
    pub const LEFT_ANKLE: usize = 15;
    pub const RIGHT_ANKLE: usize = 16;

    /// Chỉ số điểm khớp thân (vai, hông, proxy điểm giữa cột sống).
    pub const TORSO_INDICES: &[usize] = &[
        LEFT_SHOULDER,
        RIGHT_SHOULDER,
        LEFT_HIP,
        RIGHT_HIP,
    ];
}

/// Định danh duy nhất cho một theo dõi tư thế.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TrackId(pub u64);

impl TrackId {
    /// Tạo định danh theo dõi mới.
    pub fn new(id: u64) -> Self {
        Self(id)
    }
}

impl std::fmt::Display for TrackId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Track({})", self.0)
    }
}

/// Kiểu lỗi dùng chung trong pipeline RuvSense.
#[derive(Debug, thiserror::Error)]
pub enum RuvSenseError {
    /// Căn chỉnh pha thất bại.
    #[error("Lỗi căn chỉnh pha: {0}")]
    PhaseAlign(#[from] phase_align::PhaseAlignError),

    /// Lỗi kết hợp đa băng.
    #[error("Lỗi kết hợp đa băng: {0}")]
    MultiBand(#[from] multiband::MultiBandError),

    /// Lỗi kết hợp đa tĩnh.
    #[error("Lỗi kết hợp đa tĩnh: {0}")]
    Multistatic(#[from] multistatic::MultistaticError),

    /// Lỗi tính toán tương hợp.
    #[error("Lỗi tương hợp: {0}")]
    Coherence(#[from] coherence::CoherenceError),

    /// Lỗi bộ theo dõi tư thế.
    #[error("Lỗi bộ theo dõi tư thế: {0}")]
    PoseTracker(#[from] pose_tracker::PoseTrackerError),
}

/// Kiểu kết quả dùng chung cho các thao tác RuvSense.
pub type Result<T> = std::result::Result<T, RuvSenseError>;

/// Cấu hình cho pipeline RuvSense.
#[derive(Debug, Clone)]
pub struct RuvSenseConfig {
    /// Số node tối đa trong lưới đa tĩnh.
    pub max_nodes: usize,
    /// Tốc độ đầu ra mục tiêu tính bằng Hz.
    pub target_hz: f64,
    /// Số kênh trong chuỗi nhảy.
    pub num_channels: usize,
    /// Ngưỡng chấp nhận tương hợp (mặc định 0.85).
    pub coherence_accept: f32,
    /// Ngưỡng trôi tương hợp (mặc định 0.5).
    pub coherence_drift: f32,
    /// Số khung cũ tối đa trước khi hiệu chuẩn lại (mặc định 200 = 10s ở 20Hz).
    pub max_stale_frames: u64,
    /// Chiều nhúng cho tái nhận dạng AETHER (mặc định 128).
    pub embedding_dim: usize,
}

impl Default for RuvSenseConfig {
    fn default() -> Self {
        Self {
            max_nodes: 4,
            target_hz: 20.0,
            num_channels: 3,
            coherence_accept: 0.85,
            coherence_drift: 0.5,
            max_stale_frames: 200,
            embedding_dim: 128,
        }
    }
}

/// Bộ điều phối pipeline cấp cao cho cảm biến đa tĩnh RuvSense.
///
/// Điều phối luồng từ khung CSI thô mỗi node qua kết hợp
/// đa băng, căn chỉnh pha, kết hợp đa tĩnh, cổng tương hợp, và
/// cuối cùng vào bộ theo dõi tư thế.
pub struct RuvSensePipeline {
    config: RuvSenseConfig,
    phase_aligner: PhaseAligner,
    coherence_state: CoherenceState,
    gate_policy: GatePolicy,
    frame_counter: u64,
}

impl RuvSensePipeline {
    /// Tạo pipeline mới với cấu hình mặc định.
    pub fn new() -> Self {
        Self::with_config(RuvSenseConfig::default())
    }

    /// Tạo pipeline mới với cấu hình cho trước.
    pub fn with_config(config: RuvSenseConfig) -> Self {
        let n_sub = 56; // số sóng mang con chuẩn
        Self {
            phase_aligner: PhaseAligner::new(config.num_channels),
            coherence_state: CoherenceState::new(n_sub, config.coherence_accept),
            gate_policy: GatePolicy::new(
                config.coherence_accept,
                config.coherence_drift,
                config.max_stale_frames,
            ),
            config,
            frame_counter: 0,
        }
    }

    /// Trả về tham chiếu đến cấu hình pipeline hiện tại.
    pub fn config(&self) -> &RuvSenseConfig {
        &self.config
    }

    /// Trả về tổng số khung đã xử lý.
    pub fn frame_count(&self) -> u64 {
        self.frame_counter
    }

    /// Trả về tham chiếu đến trạng thái tương hợp hiện tại.
    pub fn coherence_state(&self) -> &CoherenceState {
        &self.coherence_state
    }

    /// Tăng bộ đếm khung (gọi một lần mỗi chu kỳ cảm biến).
    pub fn tick(&mut self) {
        self.frame_counter += 1;
    }
}

impl Default for RuvSensePipeline {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_values() {
        let cfg = RuvSenseConfig::default();
        assert_eq!(cfg.max_nodes, 4);
        assert!((cfg.target_hz - 20.0).abs() < f64::EPSILON);
        assert_eq!(cfg.num_channels, 3);
        assert!((cfg.coherence_accept - 0.85).abs() < f32::EPSILON);
        assert!((cfg.coherence_drift - 0.5).abs() < f32::EPSILON);
        assert_eq!(cfg.max_stale_frames, 200);
        assert_eq!(cfg.embedding_dim, 128);
    }

    #[test]
    fn pipeline_creation_defaults() {
        let pipe = RuvSensePipeline::new();
        assert_eq!(pipe.frame_count(), 0);
        assert_eq!(pipe.config().max_nodes, 4);
    }

    #[test]
    fn pipeline_tick_increments() {
        let mut pipe = RuvSensePipeline::new();
        pipe.tick();
        pipe.tick();
        pipe.tick();
        assert_eq!(pipe.frame_count(), 3);
    }

    #[test]
    fn track_id_display() {
        let tid = TrackId::new(42);
        assert_eq!(format!("{}", tid), "Track(42)");
        assert_eq!(tid.0, 42);
    }

    #[test]
    fn track_id_equality() {
        assert_eq!(TrackId(1), TrackId(1));
        assert_ne!(TrackId(1), TrackId(2));
    }

    #[test]
    fn keypoint_constants() {
        assert_eq!(keypoint::NOSE, 0);
        assert_eq!(keypoint::LEFT_ANKLE, 15);
        assert_eq!(keypoint::RIGHT_ANKLE, 16);
        assert_eq!(keypoint::TORSO_INDICES.len(), 4);
    }

    #[test]
    fn num_keypoints_is_17() {
        assert_eq!(NUM_KEYPOINTS, 17);
    }

    #[test]
    fn custom_config_pipeline() {
        let cfg = RuvSenseConfig {
            max_nodes: 6,
            target_hz: 10.0,
            num_channels: 6,
            coherence_accept: 0.9,
            coherence_drift: 0.4,
            max_stale_frames: 100,
            embedding_dim: 64,
        };
        let pipe = RuvSensePipeline::with_config(cfg);
        assert_eq!(pipe.config().max_nodes, 6);
        assert!((pipe.config().target_hz - 10.0).abs() < f64::EPSILON);
    }

    #[test]
    fn error_display() {
        let err = RuvSenseError::Coherence(coherence::CoherenceError::EmptyInput);
        let msg = format!("{}", err);
        assert!(msg.contains("tương hợp"));
    }

    #[test]
    fn pipeline_coherence_state_accessible() {
        let pipe = RuvSensePipeline::new();
        let cs = pipe.coherence_state();
        assert!(cs.score() >= 0.0);
    }
}
