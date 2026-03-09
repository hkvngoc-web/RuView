//! Định nghĩa các trait cốt lõi cho hệ thống WiFi-DensePose.
//!
//! Module này định nghĩa các trừu tượng nền tảng được sử dụng xuyên suốt hệ thống,
//! cho phép kiến trúc mô-đun và dễ kiểm thử.
//!
//! # Trait
//!
//! - [`SignalProcessor`]: Xử lý khung CSI thô thành tensor sẵn sàng cho mạng nơ-ron
//! - [`NeuralInference`]: Chạy suy luận ước lượng tư thế trên tín hiệu đã xử lý
//! - [`DataStore`]: Lưu trữ và truy xuất dữ liệu CSI và ước lượng tư thế
//!
//! # Triết Lý Thiết Kế
//!
//! Các trait này được thiết kế với các nguyên tắc sau:
//!
//! 1. **Trách Nhiệm Đơn Lẻ**: Mỗi trait xử lý một mối quan tâm
//! 2. **Khả Năng Kiểm Thử**: Tất cả trait có thể dễ dàng mock cho unit test
//! 3. **Sẵn Sàng Bất Đồng Bộ**: Phiên bản async có sẵn với tính năng `async`
//! 4. **Xử Lý Lỗi**: Sử dụng nhất quán kiểu `Result` với lỗi miền

use crate::error::{CoreResult, InferenceError, SignalError, StorageError};
use crate::types::{CsiFrame, FrameId, PoseEstimate, ProcessedSignal, Timestamp};

/// Cấu hình cho xử lý tín hiệu.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
pub struct SignalProcessorConfig {
    /// Số khung đệm trước khi xử lý
    pub buffer_size: usize,
    /// Tần số lấy mẫu tính bằng Hz
    pub sample_rate_hz: f64,
    /// Có áp dụng bộ lọc nhiễu hay không
    pub apply_noise_filter: bool,
    /// Tần số cắt bộ lọc nhiễu tính bằng Hz
    pub filter_cutoff_hz: f64,
    /// Có chuẩn hoá biên độ hay không
    pub normalize_amplitude: bool,
    /// Có tháo cuộn pha hay không
    pub unwrap_phase: bool,
    /// Hàm cửa sổ cho phân tích phổ
    pub window_function: WindowFunction,
}

impl Default for SignalProcessorConfig {
    fn default() -> Self {
        Self {
            buffer_size: 64,
            sample_rate_hz: 1000.0,
            apply_noise_filter: true,
            filter_cutoff_hz: 50.0,
            normalize_amplitude: true,
            unwrap_phase: true,
            window_function: WindowFunction::Hann,
        }
    }
}

/// Các hàm cửa sổ cho phân tích phổ.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
pub enum WindowFunction {
    /// Cửa sổ hình chữ nhật (không cửa sổ hoá)
    Rectangular,
    /// Cửa sổ Hann
    #[default]
    Hann,
    /// Cửa sổ Hamming
    Hamming,
    /// Cửa sổ Blackman
    Blackman,
    /// Cửa sổ Kaiser
    Kaiser,
}

/// Bộ xử lý tín hiệu để chuyển đổi khung CSI thô thành tín hiệu đã xử lý.
///
/// Các triển khai của trait này xử lý:
/// - Đệm và tổng hợp khung CSI
/// - Lọc nhiễu và điều hoà tín hiệu
/// - Tháo cuộn pha và chuẩn hoá biên độ
/// - Trích xuất đặc trưng
///
/// # Ví Dụ
///
/// ```ignore
/// use wifi_densepose_core::{SignalProcessor, CsiFrame};
///
/// fn process_frames(processor: &mut impl SignalProcessor, frames: Vec<CsiFrame>) {
///     for frame in frames {
///         if let Err(e) = processor.push_frame(frame) {
///             eprintln!("Không thể đẩy khung: {}", e);
///         }
///     }
///
///     if let Some(signal) = processor.try_process() {
///         println!("Tín hiệu đã xử lý với {} bước thời gian", signal.num_time_steps());
///     }
/// }
/// ```
pub trait SignalProcessor: Send + Sync {
    /// Trả về cấu hình hiện tại.
    fn config(&self) -> &SignalProcessorConfig;

    /// Cập nhật cấu hình.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu cấu hình không hợp lệ.
    fn set_config(&mut self, config: SignalProcessorConfig) -> Result<(), SignalError>;

    /// Đẩy một khung CSI mới vào bộ đệm xử lý.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu khung không hợp lệ hoặc bộ đệm đầy.
    fn push_frame(&mut self, frame: CsiFrame) -> Result<(), SignalError>;

    /// Cố gắng xử lý các khung đã đệm.
    ///
    /// Trả về `None` nếu không đủ khung được đệm.
    /// Trả về `Some(ProcessedSignal)` khi xử lý thành công.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu xử lý thất bại.
    fn try_process(&mut self) -> Result<Option<ProcessedSignal>, SignalError>;

    /// Buộc xử lý bất kỳ khung nào đang đệm.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu không có khung nào được đệm hoặc xử lý thất bại.
    fn force_process(&mut self) -> Result<ProcessedSignal, SignalError>;

    /// Trả về số khung hiện đang đệm.
    fn buffered_frame_count(&self) -> usize;

    /// Xoá bộ đệm khung.
    fn clear_buffer(&mut self);

    /// Đặt lại bộ xử lý về trạng thái ban đầu.
    fn reset(&mut self);
}

/// Cấu hình cho suy luận mạng nơ-ron.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
pub struct InferenceConfig {
    /// Đường dẫn đến file mô hình
    pub model_path: String,
    /// Thiết bị chạy suy luận
    pub device: InferenceDevice,
    /// Kích thước batch tối đa
    pub max_batch_size: usize,
    /// Số luồng cho suy luận CPU
    pub num_threads: usize,
    /// Ngưỡng độ tin cậy cho phát hiện
    pub confidence_threshold: f32,
    /// Ngưỡng triệt tiêu không cực đại
    pub nms_threshold: f32,
    /// Có sử dụng nửa chính xác (FP16) hay không
    pub use_fp16: bool,
}

impl Default for InferenceConfig {
    fn default() -> Self {
        Self {
            model_path: String::new(),
            device: InferenceDevice::Cpu,
            max_batch_size: 8,
            num_threads: 4,
            confidence_threshold: 0.5,
            nms_threshold: 0.45,
            use_fp16: false,
        }
    }
}

/// Thiết bị chạy suy luận mạng nơ-ron.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[cfg_attr(feature = "serde", derive(serde::Deserialize, serde::Serialize))]
pub enum InferenceDevice {
    /// Suy luận trên CPU
    #[default]
    Cpu,
    /// Suy luận trên GPU CUDA
    Cuda {
        /// Chỉ số thiết bị GPU
        device_id: usize,
    },
    /// Suy luận tăng tốc TensorRT
    TensorRt {
        /// Chỉ số thiết bị GPU
        device_id: usize,
    },
    /// CoreML (Apple Silicon)
    CoreMl,
    /// WebGPU cho môi trường trình duyệt
    WebGpu,
}

/// Bộ suy luận mạng nơ-ron cho ước lượng tư thế.
///
/// Các triển khai của trait này xử lý:
/// - Tải và quản lý mô hình mạng nơ-ron
/// - Chạy suy luận trên tín hiệu đã xử lý
/// - Hậu xử lý đầu ra thành ước lượng tư thế
///
/// # Ví Dụ
///
/// ```ignore
/// use wifi_densepose_core::{NeuralInference, ProcessedSignal};
///
/// async fn estimate_pose(
///     engine: &impl NeuralInference,
///     signal: ProcessedSignal,
/// ) -> Result<PoseEstimate, InferenceError> {
///     engine.infer(signal).await
/// }
/// ```
pub trait NeuralInference: Send + Sync {
    /// Trả về cấu hình hiện tại.
    fn config(&self) -> &InferenceConfig;

    /// Trả về `true` nếu mô hình đã tải và sẵn sàng.
    fn is_ready(&self) -> bool;

    /// Trả về chuỗi phiên bản mô hình.
    fn model_version(&self) -> &str;

    /// Tải mô hình từ đường dẫn đã cấu hình.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu không thể tải mô hình.
    fn load_model(&mut self) -> Result<(), InferenceError>;

    /// Giải phóng mô hình hiện tại để giải phóng tài nguyên.
    fn unload_model(&mut self);

    /// Chạy suy luận trên một tín hiệu đã xử lý đơn lẻ.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu suy luận thất bại.
    fn infer(&self, signal: &ProcessedSignal) -> Result<PoseEstimate, InferenceError>;

    /// Chạy suy luận trên một batch tín hiệu đã xử lý.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu suy luận thất bại.
    fn infer_batch(&self, signals: &[ProcessedSignal])
        -> Result<Vec<PoseEstimate>, InferenceError>;

    /// Khởi động mô hình bằng cách chạy suy luận giả.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu khởi động thất bại.
    fn warmup(&mut self) -> Result<(), InferenceError>;

    /// Trả về thống kê hiệu năng.
    fn stats(&self) -> InferenceStats;
}

/// Thống kê hiệu năng cho suy luận mạng nơ-ron.
#[derive(Debug, Clone, Default)]
pub struct InferenceStats {
    /// Tổng số lần suy luận đã thực hiện
    pub total_inferences: u64,
    /// Độ trễ suy luận trung bình tính bằng mili giây
    pub avg_latency_ms: f64,
    /// Độ trễ phân vị thứ 95 tính bằng mili giây
    pub p95_latency_ms: f64,
    /// Độ trễ tối đa tính bằng mili giây
    pub max_latency_ms: f64,
    /// Thông lượng suy luận mỗi giây
    pub throughput: f64,
    /// Bộ nhớ GPU sử dụng tính bằng byte (nếu có)
    pub gpu_memory_bytes: Option<u64>,
}

/// Tuỳ chọn truy vấn cho các thao tác kho dữ liệu.
#[derive(Debug, Clone, Default)]
pub struct QueryOptions {
    /// Số kết quả tối đa trả về
    pub limit: Option<usize>,
    /// Số kết quả bỏ qua
    pub offset: Option<usize>,
    /// Bộ lọc thời gian bắt đầu (bao gồm)
    pub start_time: Option<Timestamp>,
    /// Bộ lọc thời gian kết thúc (bao gồm)
    pub end_time: Option<Timestamp>,
    /// Bộ lọc ID thiết bị
    pub device_id: Option<String>,
    /// Thứ tự sắp xếp
    pub sort_order: SortOrder,
}

/// Thứ tự sắp xếp cho kết quả truy vấn.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SortOrder {
    /// Thứ tự tăng dần (cũ nhất trước)
    #[default]
    Ascending,
    /// Thứ tự giảm dần (mới nhất trước)
    Descending,
}

/// Trait lưu trữ dữ liệu để bền hoá và truy xuất dữ liệu CSI và ước lượng tư thế.
///
/// Các triển khai có thể sử dụng nhiều backend khác nhau:
/// - PostgreSQL/SQLite cho lưu trữ quan hệ
/// - Redis cho bộ nhớ đệm
/// - Cơ sở dữ liệu chuỗi thời gian cho truy vấn thời gian hiệu quả
///
/// # Ví Dụ
///
/// ```ignore
/// use wifi_densepose_core::{DataStore, CsiFrame, PoseEstimate};
///
/// async fn save_and_query(
///     store: &impl DataStore,
///     frame: CsiFrame,
///     estimate: PoseEstimate,
/// ) {
///     store.store_csi_frame(&frame).await?;
///     store.store_pose_estimate(&estimate).await?;
///
///     let recent = store.get_recent_estimates(10).await?;
///     println!("Tìm thấy {} ước lượng gần đây", recent.len());
/// }
/// ```
pub trait DataStore: Send + Sync {
    /// Trả về `true` nếu kho đã kết nối và sẵn sàng.
    fn is_connected(&self) -> bool;

    /// Lưu trữ một khung CSI.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu thao tác lưu trữ thất bại.
    fn store_csi_frame(&self, frame: &CsiFrame) -> Result<(), StorageError>;

    /// Truy xuất khung CSI theo ID.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu không tìm thấy khung hoặc truy xuất thất bại.
    fn get_csi_frame(&self, id: &FrameId) -> Result<CsiFrame, StorageError>;

    /// Truy xuất các khung CSI khớp với tuỳ chọn truy vấn.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu truy vấn thất bại.
    fn query_csi_frames(&self, options: &QueryOptions) -> Result<Vec<CsiFrame>, StorageError>;

    /// Lưu trữ một ước lượng tư thế.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu thao tác lưu trữ thất bại.
    fn store_pose_estimate(&self, estimate: &PoseEstimate) -> Result<(), StorageError>;

    /// Truy xuất ước lượng tư thế theo ID.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu không tìm thấy ước lượng hoặc truy xuất thất bại.
    fn get_pose_estimate(&self, id: &FrameId) -> Result<PoseEstimate, StorageError>;

    /// Truy xuất các ước lượng tư thế khớp với tuỳ chọn truy vấn.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu truy vấn thất bại.
    fn query_pose_estimates(
        &self,
        options: &QueryOptions,
    ) -> Result<Vec<PoseEstimate>, StorageError>;

    /// Truy xuất N ước lượng tư thế gần nhất.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu truy vấn thất bại.
    fn get_recent_estimates(&self, count: usize) -> Result<Vec<PoseEstimate>, StorageError>;

    /// Xoá các khung CSI cũ hơn dấu thời gian cho trước.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu thao tác xoá thất bại.
    fn delete_csi_frames_before(&self, timestamp: &Timestamp) -> Result<u64, StorageError>;

    /// Xoá các ước lượng tư thế cũ hơn dấu thời gian cho trước.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu thao tác xoá thất bại.
    fn delete_pose_estimates_before(&self, timestamp: &Timestamp) -> Result<u64, StorageError>;

    /// Trả về thống kê lưu trữ.
    fn stats(&self) -> StorageStats;
}

/// Thống kê lưu trữ.
#[derive(Debug, Clone, Default)]
pub struct StorageStats {
    /// Tổng số khung CSI đã lưu
    pub csi_frame_count: u64,
    /// Tổng số ước lượng tư thế đã lưu
    pub pose_estimate_count: u64,
    /// Tổng dung lượng lưu trữ tính bằng byte
    pub total_size_bytes: u64,
    /// Dấu thời gian bản ghi cũ nhất
    pub oldest_record: Option<Timestamp>,
    /// Dấu thời gian bản ghi mới nhất
    pub newest_record: Option<Timestamp>,
}

// =============================================================================
// Định Nghĩa Trait Bất Đồng Bộ (với tính năng `async`)
// =============================================================================

#[cfg(feature = "async")]
use async_trait::async_trait;

/// Phiên bản bất đồng bộ của [`SignalProcessor`].
#[cfg(feature = "async")]
#[async_trait]
pub trait AsyncSignalProcessor: Send + Sync {
    /// Trả về cấu hình hiện tại.
    fn config(&self) -> &SignalProcessorConfig;

    /// Cập nhật cấu hình.
    async fn set_config(&mut self, config: SignalProcessorConfig) -> Result<(), SignalError>;

    /// Đẩy một khung CSI mới vào bộ đệm xử lý.
    async fn push_frame(&mut self, frame: CsiFrame) -> Result<(), SignalError>;

    /// Cố gắng xử lý các khung đã đệm.
    async fn try_process(&mut self) -> Result<Option<ProcessedSignal>, SignalError>;

    /// Buộc xử lý bất kỳ khung nào đang đệm.
    async fn force_process(&mut self) -> Result<ProcessedSignal, SignalError>;

    /// Trả về số khung hiện đang đệm.
    fn buffered_frame_count(&self) -> usize;

    /// Xoá bộ đệm khung.
    async fn clear_buffer(&mut self);

    /// Đặt lại bộ xử lý về trạng thái ban đầu.
    async fn reset(&mut self);
}

/// Phiên bản bất đồng bộ của [`NeuralInference`].
#[cfg(feature = "async")]
#[async_trait]
pub trait AsyncNeuralInference: Send + Sync {
    /// Trả về cấu hình hiện tại.
    fn config(&self) -> &InferenceConfig;

    /// Trả về `true` nếu mô hình đã tải và sẵn sàng.
    fn is_ready(&self) -> bool;

    /// Trả về chuỗi phiên bản mô hình.
    fn model_version(&self) -> &str;

    /// Tải mô hình từ đường dẫn đã cấu hình.
    async fn load_model(&mut self) -> Result<(), InferenceError>;

    /// Giải phóng mô hình hiện tại để giải phóng tài nguyên.
    async fn unload_model(&mut self);

    /// Chạy suy luận trên một tín hiệu đã xử lý đơn lẻ.
    async fn infer(&self, signal: &ProcessedSignal) -> Result<PoseEstimate, InferenceError>;

    /// Chạy suy luận trên một batch tín hiệu đã xử lý.
    async fn infer_batch(
        &self,
        signals: &[ProcessedSignal],
    ) -> Result<Vec<PoseEstimate>, InferenceError>;

    /// Khởi động mô hình bằng cách chạy suy luận giả.
    async fn warmup(&mut self) -> Result<(), InferenceError>;

    /// Trả về thống kê hiệu năng.
    fn stats(&self) -> InferenceStats;
}

/// Phiên bản bất đồng bộ của [`DataStore`].
#[cfg(feature = "async")]
#[async_trait]
pub trait AsyncDataStore: Send + Sync {
    /// Trả về `true` nếu kho đã kết nối và sẵn sàng.
    fn is_connected(&self) -> bool;

    /// Lưu trữ một khung CSI.
    async fn store_csi_frame(&self, frame: &CsiFrame) -> Result<(), StorageError>;

    /// Truy xuất khung CSI theo ID.
    async fn get_csi_frame(&self, id: &FrameId) -> Result<CsiFrame, StorageError>;

    /// Truy xuất các khung CSI khớp với tuỳ chọn truy vấn.
    async fn query_csi_frames(&self, options: &QueryOptions) -> Result<Vec<CsiFrame>, StorageError>;

    /// Lưu trữ một ước lượng tư thế.
    async fn store_pose_estimate(&self, estimate: &PoseEstimate) -> Result<(), StorageError>;

    /// Truy xuất ước lượng tư thế theo ID.
    async fn get_pose_estimate(&self, id: &FrameId) -> Result<PoseEstimate, StorageError>;

    /// Truy xuất các ước lượng tư thế khớp với tuỳ chọn truy vấn.
    async fn query_pose_estimates(
        &self,
        options: &QueryOptions,
    ) -> Result<Vec<PoseEstimate>, StorageError>;

    /// Truy xuất N ước lượng tư thế gần nhất.
    async fn get_recent_estimates(&self, count: usize) -> Result<Vec<PoseEstimate>, StorageError>;

    /// Xoá các khung CSI cũ hơn dấu thời gian cho trước.
    async fn delete_csi_frames_before(&self, timestamp: &Timestamp) -> Result<u64, StorageError>;

    /// Xoá các ước lượng tư thế cũ hơn dấu thời gian cho trước.
    async fn delete_pose_estimates_before(
        &self,
        timestamp: &Timestamp,
    ) -> Result<u64, StorageError>;

    /// Trả về thống kê lưu trữ.
    fn stats(&self) -> StorageStats;
}

// =============================================================================
// Trait Mở Rộng
// =============================================================================

/// Trait mở rộng cho tổ hợp pipeline.
pub trait Pipeline: Send + Sync {
    /// Kiểu đầu vào cho giai đoạn pipeline này.
    type Input;
    /// Kiểu đầu ra cho giai đoạn pipeline này.
    type Output;
    /// Kiểu lỗi cho giai đoạn pipeline này.
    type Error;

    /// Xử lý đầu vào và tạo ra đầu ra.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu xử lý thất bại.
    fn process(&self, input: Self::Input) -> Result<Self::Output, Self::Error>;
}

/// Trait cho các kiểu có thể tự xác thực.
pub trait Validate {
    /// Xác thực thực thể.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi mô tả các lỗi xác thực.
    fn validate(&self) -> CoreResult<()>;
}

/// Trait cho các kiểu có thể đặt lại về trạng thái mặc định.
pub trait Resettable {
    /// Đặt lại thực thể về trạng thái ban đầu.
    fn reset(&mut self);
}

/// Trait cho các kiểu theo dõi trạng thái sức khoẻ.
pub trait HealthCheck {
    /// Trạng thái sức khoẻ của thành phần.
    type Status;

    /// Thực hiện kiểm tra sức khoẻ và trả về trạng thái hiện tại.
    fn health_check(&self) -> Self::Status;

    /// Trả về `true` nếu thành phần khoẻ mạnh.
    fn is_healthy(&self) -> bool;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_signal_processor_config_default() {
        let config = SignalProcessorConfig::default();
        assert_eq!(config.buffer_size, 64);
        assert!(config.apply_noise_filter);
        assert!(config.sample_rate_hz > 0.0);
    }

    #[test]
    fn test_inference_config_default() {
        let config = InferenceConfig::default();
        assert_eq!(config.device, InferenceDevice::Cpu);
        assert!(config.confidence_threshold > 0.0);
        assert!(config.max_batch_size > 0);
    }

    #[test]
    fn test_query_options_default() {
        let options = QueryOptions::default();
        assert!(options.limit.is_none());
        assert!(options.offset.is_none());
        assert_eq!(options.sort_order, SortOrder::Ascending);
    }

    #[test]
    fn test_inference_device_variants() {
        let cpu = InferenceDevice::Cpu;
        let cuda = InferenceDevice::Cuda { device_id: 0 };
        let tensorrt = InferenceDevice::TensorRt { device_id: 1 };

        assert_eq!(cpu, InferenceDevice::Cpu);
        assert!(matches!(cuda, InferenceDevice::Cuda { device_id: 0 }));
        assert!(matches!(tensorrt, InferenceDevice::TensorRt { device_id: 1 }));
    }
}
