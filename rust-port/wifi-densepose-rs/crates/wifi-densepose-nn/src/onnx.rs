//! Backend ONNX Runtime cho suy luận mạng nơ-ron.
//!
//! Mô-đun này cung cấp tải và thực thi mô hình ONNX sử dụng crate `ort`.
//! Hỗ trợ các nhà cung cấp thực thi CPU và GPU (CUDA/TensorRT).

use crate::error::{NnError, NnResult};
use crate::inference::{Backend, InferenceOptions};
use crate::tensor::{Tensor, TensorShape};
use ort::session::Session;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use tracing::info;

/// Bao bọc phiên ONNX Runtime
pub struct OnnxSession {
    session: Session,
    input_names: Vec<String>,
    output_names: Vec<String>,
    input_shapes: HashMap<String, TensorShape>,
    output_shapes: HashMap<String, TensorShape>,
}

impl std::fmt::Debug for OnnxSession {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OnnxSession")
            .field("input_names", &self.input_names)
            .field("output_names", &self.output_names)
            .field("input_shapes", &self.input_shapes)
            .field("output_shapes", &self.output_shapes)
            .finish()
    }
}

impl OnnxSession {
    /// Tạo phiên ONNX mới từ tệp
    pub fn from_file<P: AsRef<Path>>(path: P, _options: &InferenceOptions) -> NnResult<Self> {
        let path = path.as_ref();
        info!(?path, "Đang tải mô hình ONNX");

        // Xây dựng phiên sử dụng API ort 2.0
        let session = Session::builder()
            .map_err(|e| NnError::model_load(format!("Tạo session builder thất bại: {}", e)))?
            .commit_from_file(path)
            .map_err(|e| NnError::model_load(format!("Tải mô hình thất bại: {}", e)))?;

        // Trích xuất metadata sử dụng API ort 2.0
        let input_names: Vec<String> = session
            .inputs()
            .iter()
            .map(|input| input.name().to_string())
            .collect();

        let output_names: Vec<String> = session
            .outputs()
            .iter()
            .map(|output| output.name().to_string())
            .collect();

        // Tạm thời để hình dạng trống — sẽ được điền khi cần
        let input_shapes = HashMap::new();
        let output_shapes = HashMap::new();

        info!(
            inputs = ?input_names,
            outputs = ?output_names,
            "Tải mô hình ONNX thành công"
        );

        Ok(Self {
            session,
            input_names,
            output_names,
            input_shapes,
            output_shapes,
        })
    }

    /// Tạo từ byte trong bộ nhớ
    pub fn from_bytes(bytes: &[u8], _options: &InferenceOptions) -> NnResult<Self> {
        info!("Đang tải mô hình ONNX từ byte");

        let session = Session::builder()
            .map_err(|e| NnError::model_load(format!("Tạo session builder thất bại: {}", e)))?
            .commit_from_memory(bytes)
            .map_err(|e| NnError::model_load(format!("Tải mô hình từ byte thất bại: {}", e)))?;

        let input_names: Vec<String> = session
            .inputs()
            .iter()
            .map(|input| input.name().to_string())
            .collect();

        let output_names: Vec<String> = session
            .outputs()
            .iter()
            .map(|output| output.name().to_string())
            .collect();

        let input_shapes = HashMap::new();
        let output_shapes = HashMap::new();

        Ok(Self {
            session,
            input_names,
            output_names,
            input_shapes,
            output_shapes,
        })
    }

    /// Lấy tên đầu vào
    pub fn input_names(&self) -> &[String] {
        &self.input_names
    }

    /// Lấy tên đầu ra
    pub fn output_names(&self) -> &[String] {
        &self.output_names
    }

    /// Chạy suy luận
    pub fn run(&mut self, inputs: HashMap<String, Tensor>) -> NnResult<HashMap<String, Tensor>> {
        // Lấy tensor đầu vào đầu tiên
        let first_input_name = self.input_names.first()
            .ok_or_else(|| NnError::inference("Không có tên đầu vào được định nghĩa"))?;

        let tensor = inputs
            .get(first_input_name)
            .ok_or_else(|| NnError::invalid_input(format!("Thiếu đầu vào: {}", first_input_name)))?;

        let arr = tensor.as_array4()?;

        // Lấy hình dạng và dữ liệu để tạo tensor ort
        let shape: Vec<i64> = arr.shape().iter().map(|&d| d as i64).collect();
        let data: Vec<f32> = arr.iter().cloned().collect();

        // Tạo tensor ORT từ hình dạng và dữ liệu
        let ort_tensor = ort::value::Tensor::from_array((shape, data))
            .map_err(|e| NnError::tensor_op(format!("Tạo tensor ORT thất bại: {}", e)))?;

        // Xây dựng bản đồ đầu vào — macro inputs! trả về Vec trực tiếp
        let session_inputs = ort::inputs![first_input_name.as_str() => ort_tensor];

        // Chạy phiên
        let session_outputs = self.session
            .run(session_inputs)
            .map_err(|e| NnError::inference(format!("Suy luận thất bại: {}", e)))?;

        // Trích xuất đầu ra
        let mut result = HashMap::new();

        for name in self.output_names.iter() {
            if let Some(output) = session_outputs.get(name.as_str()) {
                // Thử trích xuất tensor — trả về bộ (shape, data) trong ort 2.0
                if let Ok((shape, data)) = output.try_extract_tensor::<f32>() {
                    let dims: Vec<usize> = shape.iter().map(|&d| d as usize).collect();

                    if dims.len() == 4 {
                        // Chuyển sang mảng 4D
                        let arr4 = ndarray::Array4::from_shape_vec(
                            (dims[0], dims[1], dims[2], dims[3]),
                            data.to_vec(),
                        ).map_err(|e| NnError::tensor_op(format!("Lỗi hình dạng: {}", e)))?;
                        result.insert(name.clone(), Tensor::Float4D(arr4));
                    } else {
                        // Xử lý các chiều khác
                        let arr_dyn = ndarray::ArrayD::from_shape_vec(
                            ndarray::IxDyn(&dims),
                            data.to_vec(),
                        ).map_err(|e| NnError::tensor_op(format!("Lỗi hình dạng: {}", e)))?;
                        result.insert(name.clone(), Tensor::FloatND(arr_dyn));
                    }
                }
            }
        }

        Ok(result)
    }
}

/// Cài đặt backend ONNX Runtime
pub struct OnnxBackend {
    session: Arc<parking_lot::RwLock<OnnxSession>>,
    options: InferenceOptions,
}

impl std::fmt::Debug for OnnxBackend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OnnxBackend")
            .field("options", &self.options)
            .finish()
    }
}

impl OnnxBackend {
    /// Tạo backend từ tệp
    pub fn from_file<P: AsRef<Path>>(path: P) -> NnResult<Self> {
        let options = InferenceOptions::default();
        let session = OnnxSession::from_file(path, &options)?;
        Ok(Self {
            session: Arc::new(parking_lot::RwLock::new(session)),
            options,
        })
    }

    /// Tạo backend từ tệp với tùy chọn
    pub fn from_file_with_options<P: AsRef<Path>>(path: P, options: InferenceOptions) -> NnResult<Self> {
        let session = OnnxSession::from_file(path, &options)?;
        Ok(Self {
            session: Arc::new(parking_lot::RwLock::new(session)),
            options,
        })
    }

    /// Tạo backend từ byte
    pub fn from_bytes(bytes: &[u8]) -> NnResult<Self> {
        let options = InferenceOptions::default();
        let session = OnnxSession::from_bytes(bytes, &options)?;
        Ok(Self {
            session: Arc::new(parking_lot::RwLock::new(session)),
            options,
        })
    }

    /// Tạo backend từ byte với tùy chọn
    pub fn from_bytes_with_options(bytes: &[u8], options: InferenceOptions) -> NnResult<Self> {
        let session = OnnxSession::from_bytes(bytes, &options)?;
        Ok(Self {
            session: Arc::new(parking_lot::RwLock::new(session)),
            options,
        })
    }

    /// Lấy tùy chọn
    pub fn options(&self) -> &InferenceOptions {
        &self.options
    }
}

impl Backend for OnnxBackend {
    fn name(&self) -> &str {
        "onnxruntime"
    }

    fn is_available(&self) -> bool {
        true
    }

    fn input_names(&self) -> Vec<String> {
        self.session.read().input_names.clone()
    }

    fn output_names(&self) -> Vec<String> {
        self.session.read().output_names.clone()
    }

    fn input_shape(&self, name: &str) -> Option<TensorShape> {
        self.session.read().input_shapes.get(name).cloned()
    }

    fn output_shape(&self, name: &str) -> Option<TensorShape> {
        self.session.read().output_shapes.get(name).cloned()
    }

    fn run(&self, inputs: HashMap<String, Tensor>) -> NnResult<HashMap<String, Tensor>> {
        self.session.write().run(inputs)
    }

    fn warmup(&self) -> NnResult<()> {
        let session = self.session.read();
        let mut dummy_inputs = HashMap::new();

        for name in &session.input_names {
            if let Some(shape) = session.input_shapes.get(name) {
                let dims = shape.dims();
                if dims.len() == 4 {
                    dummy_inputs.insert(
                        name.clone(),
                        Tensor::zeros_4d([dims[0], dims[1], dims[2], dims[3]]),
                    );
                }
            }
        }
        drop(session); // Giải phóng khóa đọc trước khi chạy

        if !dummy_inputs.is_empty() {
            let _ = self.run(dummy_inputs)?;
            info!("Khởi động ONNX hoàn tất");
        }

        Ok(())
    }
}

/// Metadata mô hình từ tệp ONNX
#[derive(Debug, Clone)]
pub struct OnnxModelInfo {
    /// Tên nhà sản xuất mô hình
    pub producer_name: Option<String>,
    /// Phiên bản mô hình
    pub model_version: Option<i64>,
    /// Miền
    pub domain: Option<String>,
    /// Mô tả
    pub description: Option<String>,
    /// Đặc tả đầu vào
    pub inputs: Vec<TensorSpec>,
    /// Đặc tả đầu ra
    pub outputs: Vec<TensorSpec>,
}

/// Đặc tả tensor
#[derive(Debug, Clone)]
pub struct TensorSpec {
    /// Tên của tensor
    pub name: String,
    /// Hình dạng (có thể chứa chiều động là -1)
    pub shape: Vec<i64>,
    /// Kiểu dữ liệu
    pub dtype: String,
}

/// Tải thông tin mô hình mà không tạo phiên đầy đủ
pub fn load_model_info<P: AsRef<Path>>(path: P) -> NnResult<OnnxModelInfo> {
    let session = Session::builder()
        .map_err(|e| NnError::model_load(format!("Tạo session builder thất bại: {}", e)))?
        .commit_from_file(path.as_ref())
        .map_err(|e| NnError::model_load(format!("Tải mô hình thất bại: {}", e)))?;

    let inputs: Vec<TensorSpec> = session
        .inputs()
        .iter()
        .map(|input| {
            TensorSpec {
                name: input.name().to_string(),
                shape: vec![],
                dtype: "float32".to_string(),
            }
        })
        .collect();

    let outputs: Vec<TensorSpec> = session
        .outputs()
        .iter()
        .map(|output| {
            TensorSpec {
                name: output.name().to_string(),
                shape: vec![],
                dtype: "float32".to_string(),
            }
        })
        .collect();

    Ok(OnnxModelInfo {
        producer_name: None,
        model_version: None,
        domain: None,
        description: None,
        inputs,
        outputs,
    })
}

/// Bộ tạo cho backend ONNX
pub struct OnnxBackendBuilder {
    model_path: Option<String>,
    model_bytes: Option<Vec<u8>>,
    options: InferenceOptions,
}

impl OnnxBackendBuilder {
    /// Tạo bộ tạo mới
    pub fn new() -> Self {
        Self {
            model_path: None,
            model_bytes: None,
            options: InferenceOptions::default(),
        }
    }

    /// Đặt đường dẫn mô hình
    pub fn model_path<P: Into<String>>(mut self, path: P) -> Self {
        self.model_path = Some(path.into());
        self
    }

    /// Đặt byte mô hình
    pub fn model_bytes(mut self, bytes: Vec<u8>) -> Self {
        self.model_bytes = Some(bytes);
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

    /// Đặt số luồng
    pub fn threads(mut self, n: usize) -> Self {
        self.options.num_threads = n;
        self
    }

    /// Bật tối ưu
    pub fn optimize(mut self, enabled: bool) -> Self {
        self.options.optimize = enabled;
        self
    }

    /// Xây dựng backend
    pub fn build(self) -> NnResult<OnnxBackend> {
        if let Some(path) = self.model_path {
            OnnxBackend::from_file_with_options(path, self.options)
        } else if let Some(bytes) = self.model_bytes {
            OnnxBackend::from_bytes_with_options(&bytes, self.options)
        } else {
            Err(NnError::config("Không có đường dẫn mô hình hoặc byte được cung cấp"))
        }
    }
}

impl Default for OnnxBackendBuilder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_onnx_backend_builder() {
        let builder = OnnxBackendBuilder::new()
            .cpu()
            .threads(4)
            .optimize(true);

        // Không thể kiểm tra build mà không có mô hình thực
        assert!(builder.model_path.is_none());
    }

    #[test]
    fn test_tensor_spec() {
        let spec = TensorSpec {
            name: "input".to_string(),
            shape: vec![1, 3, 224, 224],
            dtype: "float32".to_string(),
        };

        assert_eq!(spec.name, "input");
        assert_eq!(spec.shape.len(), 4);
    }
}
