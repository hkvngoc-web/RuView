//! # WiFi-DensePose Core
//!
//! Các kiểu dữ liệu cốt lõi, trait và tiện ích cho hệ thống ước lượng tư thế WiFi-DensePose.
//!
//! Crate này cung cấp các khối xây dựng nền tảng được sử dụng xuyên suốt
//! hệ sinh thái WiFi-DensePose, bao gồm:
//!
//! - **Kiểu Dữ Liệu Cốt Lõi**: [`CsiFrame`], [`ProcessedSignal`], [`PoseEstimate`],
//!   [`PersonPose`], và [`Keypoint`] để biểu diễn dữ liệu CSI `WiFi` và kết quả
//!   ước lượng tư thế.
//!
//! - **Kiểu Lỗi**: Xử lý lỗi toàn diện qua module [`error`],
//!   với các kiểu lỗi cụ thể cho từng hệ thống con.
//!
//! - **Trait**: Các trừu tượng cốt lõi như [`SignalProcessor`], [`NeuralInference`],
//!   và [`DataStore`] định nghĩa giao ước cho xử lý tín hiệu, suy luận
//!   mạng nơ-ron, và lưu trữ dữ liệu.
//!
//! - **Tiện Ích**: Các hàm và kiểu trợ giúp dùng chung trong toàn bộ mã nguồn.
//!
//! ## Cờ Tính Năng
//!
//! - `std` (mặc định): Bật hỗ trợ thư viện chuẩn
//! - `serde`: Bật tuần tự hoá/giải tuần tự hoá qua serde
//! - `async`: Bật định nghĩa trait bất đồng bộ
//!
//! ## Ví Dụ
//!
//! ```rust
//! use wifi_densepose_core::{CsiFrame, Keypoint, KeypointType, Confidence};
//!
//! // Tạo một điểm khớp với độ tin cậy cao
//! let keypoint = Keypoint::new(
//!     KeypointType::Nose,
//!     0.5,
//!     0.3,
//!     Confidence::new(0.95).unwrap(),
//! );
//!
//! assert!(keypoint.is_visible());
//! ```

#![cfg_attr(not(feature = "std"), no_std)]
#![forbid(unsafe_code)]

#[cfg(not(feature = "std"))]
extern crate alloc;

pub mod error;
pub mod traits;
pub mod types;
pub mod utils;

// Tái xuất các kiểu thường dùng ở gốc crate
pub use error::{CoreError, CoreResult, SignalError, InferenceError, StorageError};
pub use traits::{SignalProcessor, NeuralInference, DataStore};
pub use types::{
    // Kiểu CSI
    CsiFrame, CsiMetadata, AntennaConfig,
    // Kiểu tín hiệu
    ProcessedSignal, SignalFeatures, FrequencyBand,
    // Kiểu tư thế
    PoseEstimate, PersonPose, Keypoint, KeypointType,
    // Kiểu dùng chung
    Confidence, Timestamp, FrameId, DeviceId,
    // Khung bao
    BoundingBox,
};

/// Phiên bản crate
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Số điểm khớp tối đa mỗi người (định dạng COCO)
pub const MAX_KEYPOINTS: usize = 17;

/// Số sóng mang con tối đa thường dùng trong CSI `WiFi`
pub const MAX_SUBCARRIERS: usize = 256;

/// Ngưỡng độ tin cậy mặc định cho khả năng hiển thị điểm khớp
pub const DEFAULT_CONFIDENCE_THRESHOLD: f32 = 0.5;

/// Module prelude để import thuận tiện.
///
/// Tái xuất tiện lợi các kiểu và trait thường dùng.
///
/// ```rust
/// use wifi_densepose_core::prelude::*;
/// ```
pub mod prelude {

    pub use crate::error::{CoreError, CoreResult};
    pub use crate::traits::{DataStore, NeuralInference, SignalProcessor};
    pub use crate::types::{
        AntennaConfig, BoundingBox, Confidence, CsiFrame, CsiMetadata, DeviceId, FrameId,
        FrequencyBand, Keypoint, KeypointType, PersonPose, PoseEstimate, ProcessedSignal,
        SignalFeatures, Timestamp,
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_is_valid() {
        assert!(!VERSION.is_empty());
    }

    #[test]
    fn test_constants() {
        assert_eq!(MAX_KEYPOINTS, 17);
        assert!(MAX_SUBCARRIERS > 0);
        assert!(DEFAULT_CONFIDENCE_THRESHOLD > 0.0);
        assert!(DEFAULT_CONFIDENCE_THRESHOLD < 1.0);
    }
}
