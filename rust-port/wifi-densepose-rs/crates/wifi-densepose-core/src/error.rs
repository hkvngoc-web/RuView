//! Các kiểu lỗi cho hệ thống WiFi-DensePose.
//!
//! Module này cung cấp xử lý lỗi toàn diện sử dụng [`thiserror`] để
//! tự động triển khai trait `Display` và `Error`.
//!
//! # Phân Cấp Lỗi
//!
//! - [`CoreError`]: Kiểu lỗi cấp cao nhất bao quát tất cả lỗi hệ thống con
//! - [`SignalError`]: Lỗi liên quan đến xử lý tín hiệu CSI
//! - [`InferenceError`]: Lỗi từ suy luận mạng nơ-ron
//! - [`StorageError`]: Lỗi từ các thao tác lưu trữ dữ liệu
//!
//! # Ví Dụ
//!
//! ```rust
//! use wifi_densepose_core::error::{CoreError, SignalError};
//!
//! fn process_signal() -> Result<(), CoreError> {
//!     // Xử lý tín hiệu có thể thất bại
//!     Err(SignalError::InvalidSubcarrierCount { expected: 256, actual: 128 }.into())
//! }
//! ```

use thiserror::Error;

/// Kiểu `Result` chuyên dụng cho các thao tác cốt lõi.
pub type CoreResult<T> = Result<T, CoreError>;

/// Kiểu lỗi cấp cao nhất cho hệ thống WiFi-DensePose.
///
/// Enum này bao quát tất cả các lỗi có thể xảy ra trong hệ thống
/// cốt lõi, cung cấp kiểu lỗi thống nhất cho toàn bộ crate.
#[derive(Error, Debug)]
#[non_exhaustive]
pub enum CoreError {
    /// Lỗi xử lý tín hiệu
    #[error("Lỗi xử lý tín hiệu: {0}")]
    Signal(#[from] SignalError),

    /// Lỗi suy luận mạng nơ-ron
    #[error("Lỗi suy luận: {0}")]
    Inference(#[from] InferenceError),

    /// Lỗi lưu trữ dữ liệu
    #[error("Lỗi lưu trữ: {0}")]
    Storage(#[from] StorageError),

    /// Lỗi cấu hình
    #[error("Lỗi cấu hình: {message}")]
    Configuration {
        /// Mô tả lỗi cấu hình
        message: String,
    },

    /// Lỗi xác thực dữ liệu đầu vào
    #[error("Lỗi xác thực: {message}")]
    Validation {
        /// Mô tả xác thực nào thất bại
        message: String,
    },

    /// Không tìm thấy tài nguyên
    #[error("Không tìm thấy tài nguyên: {resource_type} với id '{id}'")]
    NotFound {
        /// Loại tài nguyên không tìm thấy
        resource_type: &'static str,
        /// Định danh của tài nguyên bị thiếu
        id: String,
    },

    /// Thao tác hết thời gian chờ
    #[error("Thao tác hết thời gian chờ sau {duration_ms}ms: {operation}")]
    Timeout {
        /// Thao tác bị hết thời gian
        operation: String,
        /// Thời lượng tính bằng mili giây trước khi hết giờ
        duration_ms: u64,
    },

    /// Trạng thái không hợp lệ cho thao tác yêu cầu
    #[error("Trạng thái không hợp lệ: mong đợi {expected}, nhận được {actual}")]
    InvalidState {
        /// Trạng thái mong đợi
        expected: String,
        /// Trạng thái thực tế
        actual: String,
    },

    /// Lỗi nội bộ (không nên xảy ra trong hoạt động bình thường)
    #[error("Lỗi nội bộ: {message}")]
    Internal {
        /// Mô tả lỗi nội bộ
        message: String,
    },
}

impl CoreError {
    /// Tạo lỗi cấu hình mới.
    #[must_use]
    pub fn configuration(message: impl Into<String>) -> Self {
        Self::Configuration {
            message: message.into(),
        }
    }

    /// Tạo lỗi xác thực mới.
    #[must_use]
    pub fn validation(message: impl Into<String>) -> Self {
        Self::Validation {
            message: message.into(),
        }
    }

    /// Tạo lỗi không tìm thấy mới.
    #[must_use]
    pub fn not_found(resource_type: &'static str, id: impl Into<String>) -> Self {
        Self::NotFound {
            resource_type,
            id: id.into(),
        }
    }

    /// Tạo lỗi hết thời gian mới.
    #[must_use]
    pub fn timeout(operation: impl Into<String>, duration_ms: u64) -> Self {
        Self::Timeout {
            operation: operation.into(),
            duration_ms,
        }
    }

    /// Tạo lỗi trạng thái không hợp lệ mới.
    #[must_use]
    pub fn invalid_state(expected: impl Into<String>, actual: impl Into<String>) -> Self {
        Self::InvalidState {
            expected: expected.into(),
            actual: actual.into(),
        }
    }

    /// Tạo lỗi nội bộ mới.
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::Internal {
            message: message.into(),
        }
    }

    /// Trả về `true` nếu lỗi này có thể khôi phục được.
    #[must_use]
    pub fn is_recoverable(&self) -> bool {
        match self {
            Self::Signal(e) => e.is_recoverable(),
            Self::Inference(e) => e.is_recoverable(),
            Self::Storage(e) => e.is_recoverable(),
            Self::Timeout { .. } => true,
            Self::NotFound { .. }
            | Self::Configuration { .. }
            | Self::Validation { .. }
            | Self::InvalidState { .. }
            | Self::Internal { .. } => false,
        }
    }
}

/// Các lỗi liên quan đến xử lý tín hiệu CSI.
#[derive(Error, Debug)]
#[non_exhaustive]
pub enum SignalError {
    /// Số lượng sóng mang con không hợp lệ trong dữ liệu CSI
    #[error("Số lượng sóng mang con không hợp lệ: mong đợi {expected}, nhận được {actual}")]
    InvalidSubcarrierCount {
        /// Số sóng mang con mong đợi
        expected: usize,
        /// Số sóng mang con thực tế nhận được
        actual: usize,
    },

    /// Cấu hình ăng-ten không hợp lệ
    #[error("Cấu hình ăng-ten không hợp lệ: {message}")]
    InvalidAntennaConfig {
        /// Mô tả lỗi cấu hình
        message: String,
    },

    /// Biên độ tín hiệu ngoài phạm vi hợp lệ
    #[error("Biên độ tín hiệu {value} ngoài phạm vi [{min}, {max}]")]
    AmplitudeOutOfRange {
        /// Giá trị biên độ không hợp lệ
        value: f64,
        /// Biên độ hợp lệ tối thiểu
        min: f64,
        /// Biên độ hợp lệ tối đa
        max: f64,
    },

    /// Tháo cuộn pha thất bại
    #[error("Tháo cuộn pha thất bại: {reason}")]
    PhaseUnwrapFailed {
        /// Lý do thất bại
        reason: String,
    },

    /// Thao tác FFT thất bại
    #[error("Thao tác FFT thất bại: {message}")]
    FftFailed {
        /// Mô tả lỗi FFT
        message: String,
    },

    /// Lỗi thiết kế hoặc áp dụng bộ lọc
    #[error("Lỗi bộ lọc: {message}")]
    FilterError {
        /// Mô tả lỗi bộ lọc
        message: String,
    },

    /// Không đủ mẫu để xử lý
    #[error("Không đủ mẫu: cần ít nhất {required}, có {available}")]
    InsufficientSamples {
        /// Số mẫu tối thiểu cần thiết
        required: usize,
        /// Số mẫu hiện có
        available: usize,
    },

    /// Chất lượng tín hiệu quá thấp để xử lý đáng tin cậy
    #[error("Chất lượng tín hiệu quá thấp: SNR {snr_db:.2} dB dưới ngưỡng {threshold_db:.2} dB")]
    LowSignalQuality {
        /// SNR đo được tính bằng dB
        snr_db: f64,
        /// SNR tối thiểu yêu cầu tính bằng dB
        threshold_db: f64,
    },

    /// Lỗi đồng bộ dấu thời gian
    #[error("Lỗi đồng bộ dấu thời gian: {message}")]
    TimestampSync {
        /// Mô tả lỗi đồng bộ
        message: String,
    },

    /// Băng tần không hợp lệ
    #[error("Băng tần không hợp lệ: {band}")]
    InvalidFrequencyBand {
        /// Định danh băng tần không hợp lệ
        band: String,
    },
}

impl SignalError {
    /// Trả về `true` nếu lỗi này có thể khôi phục được.
    #[must_use]
    pub const fn is_recoverable(&self) -> bool {
        match self {
            Self::LowSignalQuality { .. }
            | Self::InsufficientSamples { .. }
            | Self::TimestampSync { .. }
            | Self::PhaseUnwrapFailed { .. }
            | Self::FftFailed { .. } => true,
            Self::InvalidSubcarrierCount { .. }
            | Self::InvalidAntennaConfig { .. }
            | Self::AmplitudeOutOfRange { .. }
            | Self::FilterError { .. }
            | Self::InvalidFrequencyBand { .. } => false,
        }
    }
}

/// Các lỗi liên quan đến suy luận mạng nơ-ron.
#[derive(Error, Debug)]
#[non_exhaustive]
pub enum InferenceError {
    /// Không tìm thấy hoặc không thể tải file mô hình
    #[error("Không thể tải mô hình từ '{path}': {reason}")]
    ModelLoadFailed {
        /// Đường dẫn đến file mô hình
        path: String,
        /// Lý do thất bại
        reason: String,
    },

    /// Kích thước tensor đầu vào không khớp
    #[error("Kích thước đầu vào không khớp: mong đợi {expected:?}, nhận được {actual:?}")]
    InputShapeMismatch {
        /// Kích thước tensor mong đợi
        expected: Vec<usize>,
        /// Kích thước tensor thực tế
        actual: Vec<usize>,
    },

    /// Kích thước tensor đầu ra không khớp
    #[error("Kích thước đầu ra không khớp: mong đợi {expected:?}, nhận được {actual:?}")]
    OutputShapeMismatch {
        /// Kích thước tensor mong đợi
        expected: Vec<usize>,
        /// Kích thước tensor thực tế
        actual: Vec<usize>,
    },

    /// Lỗi CUDA/GPU
    #[error("Lỗi GPU: {message}")]
    GpuError {
        /// Mô tả lỗi GPU
        message: String,
    },

    /// Suy luận mô hình thất bại
    #[error("Suy luận thất bại: {message}")]
    InferenceFailed {
        /// Mô tả lỗi
        message: String,
    },

    /// Mô hình chưa được khởi tạo
    #[error("Mô hình chưa được khởi tạo: {name}")]
    ModelNotInitialized {
        /// Tên mô hình chưa khởi tạo
        name: String,
    },

    /// Định dạng mô hình không được hỗ trợ
    #[error("Định dạng mô hình không được hỗ trợ: {format}")]
    UnsupportedFormat {
        /// Định dạng không được hỗ trợ
        format: String,
    },

    /// Lỗi lượng tử hoá
    #[error("Lỗi lượng tử hoá: {message}")]
    QuantizationError {
        /// Mô tả lỗi lượng tử hoá
        message: String,
    },

    /// Lỗi kích thước batch
    #[error("Kích thước batch không hợp lệ: {size}, tối đa là {max_size}")]
    InvalidBatchSize {
        /// Kích thước batch không hợp lệ
        size: usize,
        /// Kích thước batch tối đa cho phép
        max_size: usize,
    },
}

impl InferenceError {
    /// Trả về `true` nếu lỗi này có thể khôi phục được.
    #[must_use]
    pub const fn is_recoverable(&self) -> bool {
        match self {
            Self::GpuError { .. } | Self::InferenceFailed { .. } => true,
            Self::ModelLoadFailed { .. }
            | Self::InputShapeMismatch { .. }
            | Self::OutputShapeMismatch { .. }
            | Self::ModelNotInitialized { .. }
            | Self::UnsupportedFormat { .. }
            | Self::QuantizationError { .. }
            | Self::InvalidBatchSize { .. } => false,
        }
    }
}

/// Các lỗi liên quan đến lưu trữ và bền hoá dữ liệu.
#[derive(Error, Debug)]
#[non_exhaustive]
pub enum StorageError {
    /// Kết nối cơ sở dữ liệu thất bại
    #[error("Kết nối cơ sở dữ liệu thất bại: {message}")]
    ConnectionFailed {
        /// Mô tả lỗi kết nối
        message: String,
    },

    /// Thực thi truy vấn thất bại
    #[error("Truy vấn thất bại: {query_type} - {message}")]
    QueryFailed {
        /// Loại truy vấn thất bại
        query_type: String,
        /// Thông báo lỗi
        message: String,
    },

    /// Không tìm thấy bản ghi
    #[error("Không tìm thấy bản ghi: {table}.{id}")]
    RecordNotFound {
        /// Tên bảng
        table: String,
        /// Định danh bản ghi
        id: String,
    },

    /// Vi phạm khoá trùng lặp
    #[error("Khoá trùng lặp trong {table}: {key}")]
    DuplicateKey {
        /// Tên bảng
        table: String,
        /// Khoá trùng lặp
        key: String,
    },

    /// Lỗi giao dịch
    #[error("Lỗi giao dịch: {message}")]
    TransactionError {
        /// Mô tả lỗi giao dịch
        message: String,
    },

    /// Lỗi tuần tự hoá/giải tuần tự hoá
    #[error("Lỗi tuần tự hoá: {message}")]
    SerializationError {
        /// Mô tả lỗi tuần tự hoá
        message: String,
    },

    /// Lỗi bộ nhớ đệm
    #[error("Lỗi bộ nhớ đệm: {message}")]
    CacheError {
        /// Mô tả lỗi bộ nhớ đệm
        message: String,
    },

    /// Lỗi di chuyển dữ liệu
    #[error("Lỗi di chuyển dữ liệu: {message}")]
    MigrationError {
        /// Mô tả lỗi di chuyển
        message: String,
    },

    /// Vượt quá dung lượng lưu trữ
    #[error("Vượt quá dung lượng lưu trữ: {current} / {limit} byte")]
    CapacityExceeded {
        /// Dung lượng sử dụng hiện tại
        current: u64,
        /// Giới hạn lưu trữ
        limit: u64,
    },
}

impl StorageError {
    /// Trả về `true` nếu lỗi này có thể khôi phục được.
    #[must_use]
    pub const fn is_recoverable(&self) -> bool {
        match self {
            Self::ConnectionFailed { .. }
            | Self::QueryFailed { .. }
            | Self::TransactionError { .. }
            | Self::CacheError { .. } => true,
            Self::RecordNotFound { .. }
            | Self::DuplicateKey { .. }
            | Self::SerializationError { .. }
            | Self::MigrationError { .. }
            | Self::CapacityExceeded { .. } => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_core_error_display() {
        let err = CoreError::configuration("Giá trị ngưỡng không hợp lệ");
        assert!(err.to_string().contains("Lỗi cấu hình"));
        assert!(err.to_string().contains("ngưỡng không hợp lệ"));
    }

    #[test]
    fn test_signal_error_recoverable() {
        let recoverable = SignalError::LowSignalQuality {
            snr_db: 5.0,
            threshold_db: 10.0,
        };
        assert!(recoverable.is_recoverable());

        let non_recoverable = SignalError::InvalidSubcarrierCount {
            expected: 256,
            actual: 128,
        };
        assert!(!non_recoverable.is_recoverable());
    }

    #[test]
    fn test_error_conversion() {
        let signal_err = SignalError::InvalidSubcarrierCount {
            expected: 256,
            actual: 128,
        };
        let core_err: CoreError = signal_err.into();
        assert!(matches!(core_err, CoreError::Signal(_)));
    }

    #[test]
    fn test_not_found_error() {
        let err = CoreError::not_found("CsiFrame", "frame_123");
        assert!(err.to_string().contains("CsiFrame"));
        assert!(err.to_string().contains("frame_123"));
    }

    #[test]
    fn test_timeout_error() {
        let err = CoreError::timeout("suy luận", 5000);
        assert!(err.to_string().contains("5000ms"));
        assert!(err.to_string().contains("suy luận"));
    }
}
