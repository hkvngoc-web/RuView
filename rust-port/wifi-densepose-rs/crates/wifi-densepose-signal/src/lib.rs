//! Thư Viện Xử Lý Tín Hiệu WiFi-DensePose
//!
//! Crate này cung cấp khả năng xử lý tín hiệu cho ước lượng tư thế con người dựa trên WiFi,
//! bao gồm xử lý CSI (Thông tin Trạng thái Kênh), làm sạch pha, trích xuất đặc trưng,
//! và phát hiện chuyển động.
//!
//! # Tính Năng
//!
//! - **Xử Lý CSI**: Tiền xử lý, loại bỏ nhiễu, cửa sổ hoá và chuẩn hoá
//! - **Làm Sạch Pha**: Tháo cuộn pha, loại bỏ ngoại lai và làm mượt
//! - **Trích Xuất Đặc Trưng**: Đặc trưng biên độ, pha, tương quan, Doppler và PSD
//! - **Phát Hiện Chuyển Động**: Phát hiện sự hiện diện con người với điểm số tin cậy
//!
//! # Ví Dụ
//!
//! ```rust,no_run
//! use wifi_densepose_signal::{
//!     CsiProcessor, CsiProcessorConfig,
//!     PhaseSanitizer, PhaseSanitizerConfig,
//!     MotionDetector,
//! };
//!
//! // Cấu hình bộ xử lý CSI
//! let config = CsiProcessorConfig::builder()
//!     .sampling_rate(1000.0)
//!     .window_size(256)
//!     .overlap(0.5)
//!     .noise_threshold(-30.0)
//!     .build();
//!
//! let processor = CsiProcessor::new(config);
//! ```

pub mod bvp;
pub mod csi_processor;
pub mod csi_ratio;
pub mod features;
pub mod fresnel;
pub mod hampel;
pub mod hardware_norm;
pub mod motion;
pub mod phase_sanitizer;
pub mod ruvsense;
pub mod spectrogram;
pub mod subcarrier_selection;

// Tái xuất các kiểu chính để thuận tiện
pub use csi_processor::{
    CsiData, CsiDataBuilder, CsiPreprocessor, CsiProcessor, CsiProcessorConfig,
    CsiProcessorConfigBuilder, CsiProcessorError,
};
pub use features::{
    AmplitudeFeatures, CsiFeatures, CorrelationFeatures, DopplerFeatures, FeatureExtractor,
    FeatureExtractorConfig, PhaseFeatures, PowerSpectralDensity,
};
pub use motion::{
    HumanDetectionResult, MotionAnalysis, MotionDetector, MotionDetectorConfig, MotionScore,
};
pub use hardware_norm::{
    AmplitudeStats, CanonicalCsiFrame, HardwareNormError, HardwareNormalizer, HardwareType,
};
pub use phase_sanitizer::{
    PhaseSanitizationError, PhaseSanitizer, PhaseSanitizerConfig, UnwrappingMethod,
};

/// Phiên bản thư viện
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Kiểu kết quả dùng chung cho các thao tác xử lý tín hiệu
pub type Result<T> = std::result::Result<T, SignalError>;

/// Kiểu lỗi thống nhất cho các thao tác xử lý tín hiệu
#[derive(Debug, thiserror::Error)]
pub enum SignalError {
    /// Lỗi xử lý CSI
    #[error("Lỗi xử lý CSI: {0}")]
    CsiProcessing(#[from] CsiProcessorError),

    /// Lỗi làm sạch pha
    #[error("Lỗi làm sạch pha: {0}")]
    PhaseSanitization(#[from] PhaseSanitizationError),

    /// Lỗi trích xuất đặc trưng
    #[error("Lỗi trích xuất đặc trưng: {0}")]
    FeatureExtraction(String),

    /// Lỗi phát hiện chuyển động
    #[error("Lỗi phát hiện chuyển động: {0}")]
    MotionDetection(String),

    /// Cấu hình không hợp lệ
    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),

    /// Lỗi xác thực dữ liệu
    #[error("Lỗi xác thực dữ liệu: {0}")]
    DataValidation(String),
}

/// Module prelude để import thuận tiện
pub mod prelude {
    pub use crate::csi_processor::{CsiData, CsiProcessor, CsiProcessorConfig};
    pub use crate::features::{CsiFeatures, FeatureExtractor};
    pub use crate::motion::{HumanDetectionResult, MotionDetector};
    pub use crate::phase_sanitizer::{PhaseSanitizer, PhaseSanitizerConfig};
    pub use crate::{Result, SignalError};
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version() {
        assert!(!VERSION.is_empty());
    }
}
