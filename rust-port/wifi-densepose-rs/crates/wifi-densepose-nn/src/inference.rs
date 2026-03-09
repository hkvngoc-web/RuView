//! Trừu tượng hóa bộ suy luận cho các backend mạng nơ-ron.
//!
//! Mô-đun này cung cấp giao diện thống nhất để chạy suy luận trên
//! các backend khác nhau (ONNX Runtime, tch-rs, Candle).

use crate::densepose::{DensePoseConfig, DensePoseOutput};
use crate::error::{NnError, NnResult};
use crate::tensor::{Tensor, TensorShape};
use crate::translator::TranslatorConfig;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{debug, info, instrument};

/// Tùy chọn thực thi suy luận
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceOptions {
    /// Kích thước lô cho suy luận
    #[serde(default = "default_batch_size")]
    pub batch_size: usize,
    /// Có sử dụng tăng tốc GPU hay không
    #[serde(default)]
    pub use_gpu: bool,
    /// ID thiết bị GPU (nếu dùng GPU)
    #[serde(default)]
    pub gpu_device_id: usize,
    /// Số luồng CPU cho suy luận
    #[serde(default = "default_num_threads")]
    pub num_threads: usize,
    /// Bật tối ưu/hợp nhất mô hình
    #[serde(default = "default_optimize")]
    pub optimize: bool,
    /// Giới hạn bộ nhớ tính bằng byte (0 = không giới hạn)
    #[serde(default)]
    pub memory_limit: usize,
    /// Bật phân tích hiệu năng
    #[serde(default)]
    pub profiling: bool,
}

fn default_batch_size() -> usize {
    1
}

fn default_num_threads() -> usize {
    4
}

fn default_optimize() -> bool {
    true
}

impl Default for InferenceOptions {
    fn default() -> Self {
        Self {
            batch_size: default_batch_size(),
            use_gpu: false,
            gpu_device_id: 0,
            num_threads: default_num_threads(),
            optimize: default_optimize(),
            memory_limit: 0,
            profiling: false,
        }
    }
}

impl InferenceOptions {
    /// Tạo tùy chọn cho suy luận CPU
    pub fn cpu() -> Self {
        Self::default()
    }

    /// Tạo tùy chọn cho suy luận GPU
    pub fn gpu(device_id: usize) -> Self {
        Self {
            use_gpu: true,
            gpu_device_id: device_id,
            ..Default::default()
        }
    }

    /// Đặt kích thước lô
    pub fn with_batch_size(mut self, batch_size: usize) -> Self {
        self.batch_size = batch_size;
        self
    }

    /// Đặt số luồng
    pub fn with_threads(mut self, num_threads: usize) -> Self {
        self.num_threads = num_threads;
        self
    }
}

/// Trait backend cho các bộ suy luận khác nhau
pub trait Backend: Send + Sync {
    /// Lấy tên backend
    fn name(&self) -> &str;

    /// Kiểm tra backend có khả dụng không
    fn is_available(&self) -> bool;

    /// Lấy tên đầu vào
    fn input_names(&self) -> Vec<String>;

    /// Lấy tên đầu ra
    fn output_names(&self) -> Vec<String>;

    /// Lấy hình dạng đầu vào cho tên cho trước
    fn input_shape(&self, name: &str) -> Option<TensorShape>;

    /// Lấy hình dạng đầu ra cho tên cho trước
    fn output_shape(&self, name: &str) -> Option<TensorShape>;

    /// Chạy suy luận
    fn run(&self, inputs: HashMap<String, Tensor>) -> NnResult<HashMap<String, Tensor>>;

    /// Chạy suy luận trên một đầu vào duy nhất
    fn run_single(&self, input: &Tensor) -> NnResult<Tensor> {
        let input_names = self.input_names();
        let output_names = self.output_names();

        if input_names.is_empty() {
            return Err(NnError::inference("Không có tên đầu vào được định nghĩa"));
        }
        if output_names.is_empty() {
            return Err(NnError::inference("Không có tên đầu ra được định nghĩa"));
        }

        let mut inputs = HashMap::new();
        inputs.insert(input_names[0].clone(), input.clone());

        let outputs = self.run(inputs)?;
        outputs
            .into_iter()
            .next()
            .map(|(_, v)| v)
            .ok_or_else(|| NnError::inference("Không có đầu ra được trả về"))
    }

    /// Khởi động mô hình (chạy trước tùy chọn để tối ưu)
    fn warmup(&self) -> NnResult<()> {
        Ok(())
    }

    /// Lấy mức sử dụng bộ nhớ tính bằng byte
    fn memory_usage(&self) -> usize {
        0
    }
}

/// Backend giả lập cho kiểm thử
#[derive(Debug)]
pub struct MockBackend {
    name: String,
    input_shapes: HashMap<String, TensorShape>,
    output_shapes: HashMap<String, TensorShape>,
}

impl MockBackend {
    /// Tạo backend giả lập mới
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            input_shapes: HashMap::new(),
            output_shapes: HashMap::new(),
        }
    }

    /// Thêm định nghĩa đầu vào
    pub fn with_input(mut self, name: impl Into<String>, shape: TensorShape) -> Self {
        self.input_shapes.insert(name.into(), shape);
        self
    }

    /// Thêm định nghĩa đầu ra
    pub fn with_output(mut self, name: impl Into<String>, shape: TensorShape) -> Self {
        self.output_shapes.insert(name.into(), shape);
        self
    }
}

impl Backend for MockBackend {
    fn name(&self) -> &str {
        &self.name
    }

    fn is_available(&self) -> bool {
        true
    }

    fn input_names(&self) -> Vec<String> {
        self.input_shapes.keys().cloned().collect()
    }

    fn output_names(&self) -> Vec<String> {
        self.output_shapes.keys().cloned().collect()
    }

    fn input_shape(&self, name: &str) -> Option<TensorShape> {
        self.input_shapes.get(name).cloned()
    }

    fn output_shape(&self, name: &str) -> Option<TensorShape> {
        self.output_shapes.get(name).cloned()
    }

    fn run(&self, inputs: HashMap<String, Tensor>) -> NnResult<HashMap<String, Tensor>> {
        let mut outputs = HashMap::new();

        for (name, shape) in &self.output_shapes {
            let dims: Vec<usize> = shape.dims().to_vec();
            if dims.len() == 4 {
                outputs.insert(
                    name.clone(),
                    Tensor::zeros_4d([dims[0], dims[1], dims[2], dims[3]]),
                );
            }
        }

        Ok(outputs)
    }
}

/// Bộ suy luận thống nhất hỗ trợ nhiều backend
pub struct InferenceEngine<B: Backend> {
    backend: B,
    options: InferenceOptions,
    /// Thống kê suy luận
    stats: Arc<RwLock<InferenceStats>>,
}

/// Thống kê hiệu năng suy luận
#[derive(Debug, Default, Clone)]
pub struct InferenceStats {
    /// Tổng số lần suy luận
    pub total_inferences: u64,
    /// Tổng thời gian suy luận tính bằng mili giây
    pub total_time_ms: f64,
    /// Thời gian suy luận trung bình
    pub avg_time_ms: f64,
    /// Thời gian suy luận tối thiểu
    pub min_time_ms: f64,
    /// Thời gian suy luận tối đa
    pub max_time_ms: f64,
    /// Thời gian suy luận lần cuối
    pub last_time_ms: f64,
}

impl InferenceStats {
    /// Ghi nhận một lần đo thời gian suy luận mới
    pub fn record(&mut self, time_ms: f64) {
        self.total_inferences += 1;
        self.total_time_ms += time_ms;
        self.last_time_ms = time_ms;
        self.avg_time_ms = self.total_time_ms / self.total_inferences as f64;

        if self.total_inferences == 1 {
            self.min_time_ms = time_ms;
            self.max_time_ms = time_ms;
        } else {
            self.min_time_ms = self.min_time_ms.min(time_ms);
            self.max_time_ms = self.max_time_ms.max(time_ms);
        }
    }
}

impl<B: Backend> InferenceEngine<B> {
    /// Tạo bộ suy luận mới với backend
    pub fn new(backend: B, options: InferenceOptions) -> Self {
        Self {
            backend,
            options,
            stats: Arc::new(RwLock::new(InferenceStats::default())),
        }
    }

    /// Lấy backend
    pub fn backend(&self) -> &B {
        &self.backend
    }

    /// Lấy tùy chọn
    pub fn options(&self) -> &InferenceOptions {
        &self.options
    }

    /// Kiểm tra có đang dùng GPU không
    pub fn uses_gpu(&self) -> bool {
        self.options.use_gpu && self.backend.is_available()
    }

    /// Khởi động bộ suy luận
    pub fn warmup(&self) -> NnResult<()> {
        info!("Đang khởi động bộ suy luận: {}", self.backend.name());
        self.backend.warmup()
    }

    /// Chạy suy luận trên một đầu vào duy nhất
    #[instrument(skip(self, input))]
    pub fn infer(&self, input: &Tensor) -> NnResult<Tensor> {
        let start = std::time::Instant::now();

        let result = self.backend.run_single(input)?;

        let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
        debug!(elapsed_ms = %elapsed_ms, "Suy luận hoàn tất");

        // Cập nhật thống kê bất đồng bộ (nỗ lực tốt nhất)
        let stats = self.stats.clone();
        tokio::spawn(async move {
            let mut stats = stats.write().await;
            stats.record(elapsed_ms);
        });

        Ok(result)
    }

    /// Chạy suy luận với đầu vào có tên
    #[instrument(skip(self, inputs))]
    pub fn infer_named(&self, inputs: HashMap<String, Tensor>) -> NnResult<HashMap<String, Tensor>> {
        let start = std::time::Instant::now();

        let result = self.backend.run(inputs)?;

        let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
        debug!(elapsed_ms = %elapsed_ms, "Suy luận có tên hoàn tất");

        Ok(result)
    }

    /// Chạy suy luận theo lô
    pub fn infer_batch(&self, inputs: &[Tensor]) -> NnResult<Vec<Tensor>> {
        inputs.iter().map(|input| self.infer(input)).collect()
    }

    /// Lấy thống kê suy luận
    pub async fn stats(&self) -> InferenceStats {
        self.stats.read().await.clone()
    }

    /// Đặt lại thống kê
    pub async fn reset_stats(&self) {
        let mut stats = self.stats.write().await;
        *stats = InferenceStats::default();
    }

    /// Lấy mức sử dụng bộ nhớ
    pub fn memory_usage(&self) -> usize {
        self.backend.memory_usage()
    }
}

/// Đường ống kết hợp cho suy luận WiFi-DensePose
pub struct WiFiDensePosePipeline<B: Backend> {
    /// Backend bộ dịch phương thức
    translator_backend: B,
    /// Backend DensePose
    densepose_backend: B,
    /// Cấu hình bộ dịch
    translator_config: TranslatorConfig,
    /// Cấu hình DensePose
    densepose_config: DensePoseConfig,
    /// Tùy chọn suy luận
    options: InferenceOptions,
}

impl<B: Backend> WiFiDensePosePipeline<B> {
    /// Tạo đường ống mới
    pub fn new(
        translator_backend: B,
        densepose_backend: B,
        translator_config: TranslatorConfig,
        densepose_config: DensePoseConfig,
        options: InferenceOptions,
    ) -> Self {
        Self {
            translator_backend,
            densepose_backend,
            translator_config,
            densepose_config,
            options,
        }
    }

    /// Chạy toàn bộ đường ống: CSI -> Đặc trưng thị giác -> DensePose
    #[instrument(skip(self, csi_input))]
    pub fn run(&self, csi_input: &Tensor) -> NnResult<DensePoseOutput> {
        // Bước 1: Dịch CSI sang đặc trưng thị giác
        let visual_features = self.translator_backend.run_single(csi_input)?;

        // Bước 2: Chạy DensePose trên đặc trưng thị giác
        let mut inputs = HashMap::new();
        inputs.insert("features".to_string(), visual_features);

        let outputs = self.densepose_backend.run(inputs)?;

        // Trích xuất đầu ra
        let segmentation = outputs
            .get("segmentation")
            .cloned()
            .ok_or_else(|| NnError::inference("Thiếu đầu ra phân đoạn"))?;

        let uv_coordinates = outputs
            .get("uv_coordinates")
            .cloned()
            .ok_or_else(|| NnError::inference("Thiếu đầu ra tọa độ UV"))?;

        Ok(DensePoseOutput {
            segmentation,
            uv_coordinates,
            confidence: None,
        })
    }

    /// Lấy cấu hình bộ dịch
    pub fn translator_config(&self) -> &TranslatorConfig {
        &self.translator_config
    }

    /// Lấy cấu hình DensePose
    pub fn densepose_config(&self) -> &DensePoseConfig {
        &self.densepose_config
    }
}

/// Bộ tạo cho bộ suy luận
pub struct EngineBuilder {
    options: InferenceOptions,
    model_path: Option<String>,
}

impl EngineBuilder {
    /// Tạo bộ tạo mới
    pub fn new() -> Self {
        Self {
            options: InferenceOptions::default(),
            model_path: None,
        }
    }

    /// Đặt tùy chọn suy luận
    pub fn options(mut self, options: InferenceOptions) -> Self {
        self.options = options;
        self
    }

    /// Đặt đường dẫn mô hình
    pub fn model_path(mut self, path: impl Into<String>) -> Self {
        self.model_path = Some(path.into());
        self
    }

    /// Sử dụng GPU
    pub fn gpu(mut self, device_id: usize) -> Self {
        self.options.use_gpu = true;
        self.options.gpu_device_id = device_id;
        self
    }

    /// Sử dụng CPU
    pub fn cpu(mut self) -> Self {
        self.options.use_gpu = false;
        self
    }

    /// Đặt kích thước lô
    pub fn batch_size(mut self, size: usize) -> Self {
        self.options.batch_size = size;
        self
    }

    /// Đặt số luồng
    pub fn threads(mut self, n: usize) -> Self {
        self.options.num_threads = n;
        self
    }

    /// Xây dựng với backend giả lập (cho kiểm thử)
    pub fn build_mock(self) -> InferenceEngine<MockBackend> {
        let backend = MockBackend::new("mock")
            .with_input("input".to_string(), TensorShape::new(vec![1, 256, 64, 64]))
            .with_output("output".to_string(), TensorShape::new(vec![1, 256, 64, 64]));

        InferenceEngine::new(backend, self.options)
    }

    /// Xây dựng với backend ONNX
    #[cfg(feature = "onnx")]
    pub fn build_onnx(self) -> NnResult<InferenceEngine<crate::onnx::OnnxBackend>> {
        let model_path = self
            .model_path
            .ok_or_else(|| NnError::config("Cần đường dẫn mô hình cho backend ONNX"))?;

        let backend = crate::onnx::OnnxBackend::from_file(&model_path)?;
        Ok(InferenceEngine::new(backend, self.options))
    }
}

impl Default for EngineBuilder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_inference_options() {
        let opts = InferenceOptions::cpu().with_batch_size(4).with_threads(8);
        assert_eq!(opts.batch_size, 4);
        assert_eq!(opts.num_threads, 8);
        assert!(!opts.use_gpu);

        let gpu_opts = InferenceOptions::gpu(0);
        assert!(gpu_opts.use_gpu);
        assert_eq!(gpu_opts.gpu_device_id, 0);
    }

    #[test]
    fn test_mock_backend() {
        let backend = MockBackend::new("test")
            .with_input("input", TensorShape::new(vec![1, 3, 224, 224]))
            .with_output("output", TensorShape::new(vec![1, 1000]));

        assert_eq!(backend.name(), "test");
        assert!(backend.is_available());
        assert_eq!(backend.input_names(), vec!["input".to_string()]);
        assert_eq!(backend.output_names(), vec!["output".to_string()]);
    }

    #[test]
    fn test_engine_builder() {
        let engine = EngineBuilder::new()
            .cpu()
            .batch_size(2)
            .threads(4)
            .build_mock();

        assert_eq!(engine.options().batch_size, 2);
        assert_eq!(engine.options().num_threads, 4);
    }

    #[test]
    fn test_inference_stats() {
        let mut stats = InferenceStats::default();
        stats.record(10.0);
        stats.record(20.0);
        stats.record(15.0);

        assert_eq!(stats.total_inferences, 3);
        assert_eq!(stats.min_time_ms, 10.0);
        assert_eq!(stats.max_time_ms, 20.0);
        assert_eq!(stats.avg_time_ms, 15.0);
    }

    #[tokio::test]
    async fn test_inference_engine() {
        let engine = EngineBuilder::new().build_mock();

        let input = Tensor::zeros_4d([1, 256, 64, 64]);
        let output = engine.infer(&input).unwrap();

        assert_eq!(output.shape().dims(), &[1, 256, 64, 64]);
    }
}
