//! # Crate mạng nơ-ron WiFi-DensePose
//!
//! Crate này cung cấp khả năng suy luận mạng nơ-ron cho hệ thống ước lượng
//! tư thế WiFi-DensePose. Hỗ trợ nhiều backend bao gồm ONNX Runtime,
//! tch-rs (PyTorch), và Candle để triển khai linh hoạt.
//!
//! ## Tính năng
//!
//! - **Đầu DensePose**: Phân đoạn bộ phận cơ thể và hồi quy tọa độ UV
//! - **Bộ dịch phương thức**: Dịch CSI sang không gian đặc trưng thị giác
//! - **Hỗ trợ đa backend**: ONNX, PyTorch (tch), và Candle
//! - **Tối ưu suy luận**: Gom lô, tăng tốc GPU, và bộ nhớ đệm mô hình
//!
//! ## Ví dụ
//!
//! ```rust,ignore
//! use wifi_densepose_nn::{InferenceEngine, DensePoseConfig, OnnxBackend};
//!
//! // Tạo bộ suy luận với backend ONNX
//! let config = DensePoseConfig::default();
//! let backend = OnnxBackend::from_file("model.onnx")?;
//! let engine = InferenceEngine::new(backend, config)?;
//!
//! // Chạy suy luận
//! let input = ndarray::Array4::zeros((1, 256, 64, 64));
//! let output = engine.infer(&input)?;
//! ```

#![warn(missing_docs)]
#![warn(rustdoc::missing_doc_code_examples)]
#![deny(unsafe_code)]

pub mod densepose;
pub mod error;
pub mod inference;
#[cfg(feature = "onnx")]
pub mod onnx;
pub mod tensor;
pub mod translator;

// Tái xuất để tiện sử dụng
pub use densepose::{DensePoseConfig, DensePoseHead, DensePoseOutput};
pub use error::{NnError, NnResult};
pub use inference::{Backend, InferenceEngine, InferenceOptions};
#[cfg(feature = "onnx")]
pub use onnx::{OnnxBackend, OnnxSession};
pub use tensor::{Tensor, TensorShape};
pub use translator::{ModalityTranslator, TranslatorConfig, TranslatorOutput};

/// Mô-đun prelude để import tiện lợi
pub mod prelude {
    pub use crate::densepose::{DensePoseConfig, DensePoseHead, DensePoseOutput};
    pub use crate::error::{NnError, NnResult};
    pub use crate::inference::{Backend, InferenceEngine, InferenceOptions};
    #[cfg(feature = "onnx")]
    pub use crate::onnx::{OnnxBackend, OnnxSession};
    pub use crate::tensor::{Tensor, TensorShape};
    pub use crate::translator::{ModalityTranslator, TranslatorConfig, TranslatorOutput};
}

/// Thông tin phiên bản
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Số bộ phận cơ thể trong mô hình DensePose (cấu hình chuẩn)
pub const NUM_BODY_PARTS: usize = 24;

/// Số tọa độ UV (U và V)
pub const NUM_UV_COORDINATES: usize = 2;

/// Kích thước kênh ẩn mặc định cho mạng
pub const DEFAULT_HIDDEN_CHANNELS: &[usize] = &[256, 128, 64];
