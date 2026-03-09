//! Các kiểu lỗi cho crate mạng nơ-ron.

use thiserror::Error;

/// Bí danh kiểu Result cho các thao tác mạng nơ-ron
pub type NnResult<T> = Result<T, NnError>;

/// Các lỗi mạng nơ-ron
#[derive(Error, Debug)]
pub enum NnError {
    /// Lỗi xác thực cấu hình
    #[error("Lỗi cấu hình: {0}")]
    Config(String),

    /// Lỗi tải mô hình
    #[error("Tải mô hình thất bại: {0}")]
    ModelLoad(String),

    /// Lỗi suy luận
    #[error("Suy luận thất bại: {0}")]
    Inference(String),

    /// Lỗi không khớp hình dạng
    #[error("Hình dạng không khớp: kỳ vọng {expected:?}, nhận được {actual:?}")]
    ShapeMismatch {
        /// Hình dạng kỳ vọng
        expected: Vec<usize>,
        /// Hình dạng thực tế
        actual: Vec<usize>,
    },

    /// Lỗi đầu vào không hợp lệ
    #[error("Đầu vào không hợp lệ: {0}")]
    InvalidInput(String),

    /// Backend không khả dụng
    #[error("Backend không khả dụng: {0}")]
    BackendUnavailable(String),

    /// Lỗi ONNX Runtime
    #[cfg(feature = "onnx")]
    #[error("Lỗi ONNX Runtime: {0}")]
    OnnxRuntime(#[from] ort::Error),

    /// Lỗi IO
    #[error("Lỗi IO: {0}")]
    Io(#[from] std::io::Error),

    /// Lỗi tuần tự hóa
    #[error("Lỗi tuần tự hóa: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Lỗi thao tác tensor
    #[error("Lỗi thao tác tensor: {0}")]
    TensorOp(String),

    /// Thao tác không được hỗ trợ
    #[error("Thao tác không được hỗ trợ: {0}")]
    Unsupported(String),
}

impl NnError {
    /// Tạo lỗi cấu hình
    pub fn config<S: Into<String>>(msg: S) -> Self {
        NnError::Config(msg.into())
    }

    /// Tạo lỗi tải mô hình
    pub fn model_load<S: Into<String>>(msg: S) -> Self {
        NnError::ModelLoad(msg.into())
    }

    /// Tạo lỗi suy luận
    pub fn inference<S: Into<String>>(msg: S) -> Self {
        NnError::Inference(msg.into())
    }

    /// Tạo lỗi không khớp hình dạng
    pub fn shape_mismatch(expected: Vec<usize>, actual: Vec<usize>) -> Self {
        NnError::ShapeMismatch { expected, actual }
    }

    /// Tạo lỗi đầu vào không hợp lệ
    pub fn invalid_input<S: Into<String>>(msg: S) -> Self {
        NnError::InvalidInput(msg.into())
    }

    /// Tạo lỗi thao tác tensor
    pub fn tensor_op<S: Into<String>>(msg: S) -> Self {
        NnError::TensorOp(msg.into())
    }
}
