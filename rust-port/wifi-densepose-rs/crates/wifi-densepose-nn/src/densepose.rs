//! Đầu DensePose cho phân đoạn bộ phận cơ thể và hồi quy tọa độ UV.
//!
//! Mô-đun này cài đặt đầu dự đoán DensePose lấy bản đồ đặc trưng
//! từ mạng xương sống và tạo ra mặt nạ phân đoạn bộ phận cơ thể cùng
//! dự đoán tọa độ UV cho mỗi pixel.

use crate::error::{NnError, NnResult};
use crate::tensor::{Tensor, TensorShape, TensorStats};
use ndarray::Array4;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Cấu hình cho đầu DensePose
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DensePoseConfig {
    /// Số kênh đầu vào từ xương sống
    pub input_channels: usize,
    /// Số bộ phận cơ thể cần dự đoán (không bao gồm nền)
    pub num_body_parts: usize,
    /// Số tọa độ UV (thường là 2 cho U và V)
    pub num_uv_coordinates: usize,
    /// Kích thước kênh ẩn cho tích chập chia sẻ
    #[serde(default = "default_hidden_channels")]
    pub hidden_channels: Vec<usize>,
    /// Kích thước nhân tích chập
    #[serde(default = "default_kernel_size")]
    pub kernel_size: usize,
    /// Đệm tích chập
    #[serde(default = "default_padding")]
    pub padding: usize,
    /// Tỷ lệ dropout
    #[serde(default = "default_dropout_rate")]
    pub dropout_rate: f32,
    /// Có sử dụng Mạng Kim tự tháp Đặc trưng không
    #[serde(default)]
    pub use_fpn: bool,
    /// Các mức FPN sử dụng
    #[serde(default = "default_fpn_levels")]
    pub fpn_levels: Vec<usize>,
    /// Bước đầu ra
    #[serde(default = "default_output_stride")]
    pub output_stride: usize,
}

fn default_hidden_channels() -> Vec<usize> {
    vec![128, 64]
}

fn default_kernel_size() -> usize {
    3
}

fn default_padding() -> usize {
    1
}

fn default_dropout_rate() -> f32 {
    0.1
}

fn default_fpn_levels() -> Vec<usize> {
    vec![2, 3, 4, 5]
}

fn default_output_stride() -> usize {
    4
}

impl Default for DensePoseConfig {
    fn default() -> Self {
        Self {
            input_channels: 256,
            num_body_parts: 24,
            num_uv_coordinates: 2,
            hidden_channels: default_hidden_channels(),
            kernel_size: default_kernel_size(),
            padding: default_padding(),
            dropout_rate: default_dropout_rate(),
            use_fpn: false,
            fpn_levels: default_fpn_levels(),
            output_stride: default_output_stride(),
        }
    }
}

impl DensePoseConfig {
    /// Tạo cấu hình mới với các tham số bắt buộc
    pub fn new(input_channels: usize, num_body_parts: usize, num_uv_coordinates: usize) -> Self {
        Self {
            input_channels,
            num_body_parts,
            num_uv_coordinates,
            ..Default::default()
        }
    }

    /// Xác thực cấu hình
    pub fn validate(&self) -> NnResult<()> {
        if self.input_channels == 0 {
            return Err(NnError::config("input_channels phải dương"));
        }
        if self.num_body_parts == 0 {
            return Err(NnError::config("num_body_parts phải dương"));
        }
        if self.num_uv_coordinates == 0 {
            return Err(NnError::config("num_uv_coordinates phải dương"));
        }
        if self.hidden_channels.is_empty() {
            return Err(NnError::config("hidden_channels không được rỗng"));
        }
        Ok(())
    }

    /// Lấy số kênh đầu ra cho phân đoạn (bao gồm nền)
    pub fn segmentation_channels(&self) -> usize {
        self.num_body_parts + 1 // +1 cho lớp nền
    }
}

/// Đầu ra từ đầu DensePose
#[derive(Debug, Clone)]
pub struct DensePoseOutput {
    /// Logit phân đoạn bộ phận cơ thể: (lô, số_phần+1, chiều_cao, chiều_rộng)
    pub segmentation: Tensor,
    /// Tọa độ UV: (lô, 2, chiều_cao, chiều_rộng)
    pub uv_coordinates: Tensor,
    /// Điểm tin cậy tùy chọn
    pub confidence: Option<ConfidenceScores>,
}

/// Điểm tin cậy cho dự đoán
#[derive(Debug, Clone)]
pub struct ConfidenceScores {
    /// Tin cậy phân đoạn theo pixel
    pub segmentation_confidence: Tensor,
    /// Tin cậy UV theo pixel
    pub uv_confidence: Tensor,
}

/// Đầu DensePose cho phân đoạn bộ phận cơ thể và hồi quy UV
///
/// Đây là cài đặt suy luận thuần sử dụng trọng số đã huấn luyện trước
/// được lưu trữ ở các định dạng khác nhau (ONNX, SafeTensors, v.v.)
#[derive(Debug)]
pub struct DensePoseHead {
    config: DensePoseConfig,
    /// Trọng số đã lưu đệm cho suy luận gốc (tùy chọn)
    weights: Option<DensePoseWeights>,
}

/// Trọng số đã huấn luyện trước cho suy luận Rust gốc
#[derive(Debug, Clone)]
pub struct DensePoseWeights {
    /// Trọng số tích chập chia sẻ: Vec gồm (trọng_số, thiên_lệch) cho mỗi lớp
    pub shared_conv: Vec<ConvLayerWeights>,
    /// Trọng số đầu phân đoạn
    pub segmentation_head: Vec<ConvLayerWeights>,
    /// Trọng số đầu hồi quy UV
    pub uv_head: Vec<ConvLayerWeights>,
}

/// Trọng số cho một lớp tích chập
#[derive(Debug, Clone)]
pub struct ConvLayerWeights {
    /// Trọng số tích chập: (kênh_ra, kênh_vào, chiều_cao_nhân, chiều_rộng_nhân)
    pub weight: Array4<f32>,
    /// Thiên lệch: (kênh_ra,)
    pub bias: Option<ndarray::Array1<f32>>,
    /// Gamma chuẩn hóa lô
    pub bn_gamma: Option<ndarray::Array1<f32>>,
    /// Beta chuẩn hóa lô
    pub bn_beta: Option<ndarray::Array1<f32>>,
    /// Trung bình chạy chuẩn hóa lô
    pub bn_mean: Option<ndarray::Array1<f32>>,
    /// Phương sai chạy chuẩn hóa lô
    pub bn_var: Option<ndarray::Array1<f32>>,
}

impl DensePoseHead {
    /// Tạo đầu DensePose mới với cấu hình
    pub fn new(config: DensePoseConfig) -> NnResult<Self> {
        config.validate()?;
        Ok(Self {
            config,
            weights: None,
        })
    }

    /// Tạo với trọng số đã tải sẵn cho suy luận gốc
    pub fn with_weights(config: DensePoseConfig, weights: DensePoseWeights) -> NnResult<Self> {
        config.validate()?;
        Ok(Self {
            config,
            weights: Some(weights),
        })
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &DensePoseConfig {
        &self.config
    }

    /// Kiểm tra trọng số đã được tải chưa cho suy luận gốc
    pub fn has_weights(&self) -> bool {
        self.weights.is_some()
    }

    /// Lấy hình dạng đầu vào kỳ vọng cho kích thước lô cho trước
    pub fn expected_input_shape(&self, batch_size: usize, height: usize, width: usize) -> TensorShape {
        TensorShape::new(vec![batch_size, self.config.input_channels, height, width])
    }

    /// Xác thực hình dạng tensor đầu vào
    pub fn validate_input(&self, input: &Tensor) -> NnResult<()> {
        let shape = input.shape();
        if shape.ndim() != 4 {
            return Err(NnError::shape_mismatch(
                vec![0, self.config.input_channels, 0, 0],
                shape.dims().to_vec(),
            ));
        }
        if shape.dim(1) != Some(self.config.input_channels) {
            return Err(NnError::invalid_input(format!(
                "Kỳ vọng {} kênh đầu vào, nhận được {:?}",
                self.config.input_channels,
                shape.dim(1)
            )));
        }
        Ok(())
    }

    /// Truyền xuôi qua đầu DensePose (cài đặt Rust gốc)
    ///
    /// Thực hiện suy luận sử dụng trọng số đã tải. Cho suy luận dựa ONNX,
    /// sử dụng trực tiếp backend ONNX.
    ///
    /// # Lỗi
    /// Trả về lỗi nếu không có trọng số mô hình được tải. Tải trọng số bằng
    /// `with_weights()` trước khi gọi forward(). Dùng `forward_mock()` trong kiểm thử.
    pub fn forward(&self, input: &Tensor) -> NnResult<DensePoseOutput> {
        self.validate_input(input)?;

        if let Some(ref _weights) = self.weights {
            self.forward_native(input)
        } else {
            Err(NnError::inference("Chưa tải trọng số mô hình. Tải trọng số bằng with_weights() trước khi gọi forward(). Dùng MockBackend cho kiểm thử."))
        }
    }

    /// Truyền xuôi gốc sử dụng trọng số đã tải
    fn forward_native(&self, input: &Tensor) -> NnResult<DensePoseOutput> {
        let weights = self.weights.as_ref().ok_or_else(|| {
            NnError::inference("Chưa tải trọng số cho suy luận gốc")
        })?;

        let input_arr = input.as_array4()?;
        let (batch, _channels, height, width) = input_arr.dim();

        // Áp dụng tích chập chia sẻ
        let mut current = input_arr.clone();
        for layer_weights in &weights.shared_conv {
            current = self.apply_conv_layer(&current, layer_weights)?;
            current = self.apply_relu(&current);
        }

        // Nhánh phân đoạn
        let mut seg_features = current.clone();
        for layer_weights in &weights.segmentation_head {
            seg_features = self.apply_conv_layer(&seg_features, layer_weights)?;
        }

        // Nhánh hồi quy UV
        let mut uv_features = current;
        for layer_weights in &weights.uv_head {
            uv_features = self.apply_conv_layer(&uv_features, layer_weights)?;
        }
        // Áp dụng sigmoid để chuẩn hóa UV về [0, 1]
        uv_features = self.apply_sigmoid(&uv_features);

        Ok(DensePoseOutput {
            segmentation: Tensor::Float4D(seg_features),
            uv_coordinates: Tensor::Float4D(uv_features),
            confidence: None,
        })
    }

    /// Truyền xuôi giả lập cho kiểm thử
    #[cfg(test)]
    fn forward_mock(&self, input: &Tensor) -> NnResult<DensePoseOutput> {
        let shape = input.shape();
        let batch = shape.dim(0).unwrap_or(1);
        let height = shape.dim(2).unwrap_or(64);
        let width = shape.dim(3).unwrap_or(64);

        // Kích thước đầu ra sau nâng mẫu (2x)
        let out_height = height * 2;
        let out_width = width * 2;

        // Tạo đầu ra phân đoạn giả lập
        let seg_shape = [batch, self.config.segmentation_channels(), out_height, out_width];
        let segmentation = Tensor::zeros_4d(seg_shape);

        // Tạo đầu ra UV giả lập
        let uv_shape = [batch, self.config.num_uv_coordinates, out_height, out_width];
        let uv_coordinates = Tensor::zeros_4d(uv_shape);

        Ok(DensePoseOutput {
            segmentation,
            uv_coordinates,
            confidence: None,
        })
    }

    /// Áp dụng lớp tích chập
    fn apply_conv_layer(&self, input: &Array4<f32>, weights: &ConvLayerWeights) -> NnResult<Array4<f32>> {
        let (batch, in_channels, in_height, in_width) = input.dim();
        let (out_channels, _, kernel_h, kernel_w) = weights.weight.dim();

        let pad_h = self.config.padding;
        let pad_w = self.config.padding;
        let out_height = in_height + 2 * pad_h - kernel_h + 1;
        let out_width = in_width + 2 * pad_w - kernel_w + 1;

        let mut output = Array4::zeros((batch, out_channels, out_height, out_width));

        // Cài đặt tích chập đơn giản (chưa tối ưu)
        for b in 0..batch {
            for oc in 0..out_channels {
                for oh in 0..out_height {
                    for ow in 0..out_width {
                        let mut sum = 0.0f32;
                        for ic in 0..in_channels {
                            for kh in 0..kernel_h {
                                for kw in 0..kernel_w {
                                    let ih = oh + kh;
                                    let iw = ow + kw;
                                    if ih >= pad_h && ih < in_height + pad_h
                                        && iw >= pad_w && iw < in_width + pad_w
                                    {
                                        let input_val = input[[b, ic, ih - pad_h, iw - pad_w]];
                                        sum += input_val * weights.weight[[oc, ic, kh, kw]];
                                    }
                                }
                            }
                        }
                        if let Some(ref bias) = weights.bias {
                            sum += bias[oc];
                        }
                        output[[b, oc, oh, ow]] = sum;
                    }
                }
            }
        }

        // Áp dụng chuẩn hóa lô nếu có trọng số
        if let (Some(gamma), Some(beta), Some(mean), Some(var)) = (
            &weights.bn_gamma,
            &weights.bn_beta,
            &weights.bn_mean,
            &weights.bn_var,
        ) {
            let eps = 1e-5;
            for b in 0..batch {
                for c in 0..out_channels {
                    let scale = gamma[c] / (var[c] + eps).sqrt();
                    let shift = beta[c] - mean[c] * scale;
                    for h in 0..out_height {
                        for w in 0..out_width {
                            output[[b, c, h, w]] = output[[b, c, h, w]] * scale + shift;
                        }
                    }
                }
            }
        }

        Ok(output)
    }

    /// Áp dụng hàm kích hoạt ReLU
    fn apply_relu(&self, input: &Array4<f32>) -> Array4<f32> {
        input.mapv(|x| x.max(0.0))
    }

    /// Áp dụng hàm kích hoạt sigmoid
    fn apply_sigmoid(&self, input: &Array4<f32>) -> Array4<f32> {
        input.mapv(|x| 1.0 / (1.0 + (-x).exp()))
    }

    /// Hậu xử lý dự đoán để lấy đầu ra cuối cùng
    pub fn post_process(&self, output: &DensePoseOutput) -> NnResult<PostProcessedOutput> {
        // Lấy dự đoán bộ phận cơ thể (argmax theo kênh)
        let body_parts = output.segmentation.argmax(1)?;

        // Tính điểm tin cậy
        let seg_confidence = self.compute_segmentation_confidence(&output.segmentation)?;
        let uv_confidence = self.compute_uv_confidence(&output.uv_coordinates)?;

        Ok(PostProcessedOutput {
            body_parts,
            uv_coordinates: output.uv_coordinates.clone(),
            segmentation_confidence: seg_confidence,
            uv_confidence,
        })
    }

    /// Tính tin cậy phân đoạn từ logit
    fn compute_segmentation_confidence(&self, logits: &Tensor) -> NnResult<Tensor> {
        // Áp dụng softmax và lấy xác suất tối đa
        let probs = logits.softmax(1)?;
        // Đơn giản, trả về đầu ra softmax
        // Trong cài đặt đầy đủ, chúng ta sẽ tính max theo trục kênh
        Ok(probs)
    }

    /// Tính tin cậy UV từ dự đoán
    fn compute_uv_confidence(&self, uv: &Tensor) -> NnResult<Tensor> {
        // Tin cậy UV dựa trên phương sai dự đoán
        // Tin cậy cao hơn khi dự đoán nhất quán hơn
        let std = uv.std()?;
        let confidence_val = 1.0 / (1.0 + std);

        // Trả về tensor với tin cậy hằng số tạm thời
        let shape = uv.shape();
        let arr = Array4::from_elem(
            (shape.dim(0).unwrap_or(1), 1, shape.dim(2).unwrap_or(1), shape.dim(3).unwrap_or(1)),
            confidence_val,
        );
        Ok(Tensor::Float4D(arr))
    }

    /// Lấy thống kê đặc trưng cho gỡ lỗi
    pub fn get_output_stats(&self, output: &DensePoseOutput) -> NnResult<HashMap<String, TensorStats>> {
        let mut stats = HashMap::new();
        stats.insert("segmentation".to_string(), TensorStats::from_tensor(&output.segmentation)?);
        stats.insert("uv_coordinates".to_string(), TensorStats::from_tensor(&output.uv_coordinates)?);
        Ok(stats)
    }
}

/// Đầu ra đã hậu xử lý với dự đoán cuối cùng
#[derive(Debug, Clone)]
pub struct PostProcessedOutput {
    /// Nhãn bộ phận cơ thể theo pixel
    pub body_parts: Tensor,
    /// Tọa độ UV
    pub uv_coordinates: Tensor,
    /// Tin cậy phân đoạn
    pub segmentation_confidence: Tensor,
    /// Tin cậy UV
    pub uv_confidence: Tensor,
}

/// Nhãn bộ phận cơ thể theo đặc tả DensePose
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum BodyPart {
    /// Nền (không phải cơ thể)
    Background = 0,
    /// Thân
    Torso = 1,
    /// Tay phải
    RightHand = 2,
    /// Tay trái
    LeftHand = 3,
    /// Bàn chân trái
    LeftFoot = 4,
    /// Bàn chân phải
    RightFoot = 5,
    /// Đùi phải
    UpperLegRight = 6,
    /// Đùi trái
    UpperLegLeft = 7,
    /// Cẳng chân phải
    LowerLegRight = 8,
    /// Cẳng chân trái
    LowerLegLeft = 9,
    /// Bắp tay trái
    UpperArmLeft = 10,
    /// Bắp tay phải
    UpperArmRight = 11,
    /// Cẳng tay trái
    LowerArmLeft = 12,
    /// Cẳng tay phải
    LowerArmRight = 13,
    /// Đầu
    Head = 14,
}

impl BodyPart {
    /// Lấy bộ phận cơ thể từ chỉ số
    pub fn from_index(idx: u8) -> Option<Self> {
        match idx {
            0 => Some(BodyPart::Background),
            1 => Some(BodyPart::Torso),
            2 => Some(BodyPart::RightHand),
            3 => Some(BodyPart::LeftHand),
            4 => Some(BodyPart::LeftFoot),
            5 => Some(BodyPart::RightFoot),
            6 => Some(BodyPart::UpperLegRight),
            7 => Some(BodyPart::UpperLegLeft),
            8 => Some(BodyPart::LowerLegRight),
            9 => Some(BodyPart::LowerLegLeft),
            10 => Some(BodyPart::UpperArmLeft),
            11 => Some(BodyPart::UpperArmRight),
            12 => Some(BodyPart::LowerArmLeft),
            13 => Some(BodyPart::LowerArmRight),
            14 => Some(BodyPart::Head),
            _ => None,
        }
    }

    /// Lấy tên hiển thị
    pub fn name(&self) -> &'static str {
        match self {
            BodyPart::Background => "Nền",
            BodyPart::Torso => "Thân",
            BodyPart::RightHand => "Tay phải",
            BodyPart::LeftHand => "Tay trái",
            BodyPart::LeftFoot => "Bàn chân trái",
            BodyPart::RightFoot => "Bàn chân phải",
            BodyPart::UpperLegRight => "Đùi phải",
            BodyPart::UpperLegLeft => "Đùi trái",
            BodyPart::LowerLegRight => "Cẳng chân phải",
            BodyPart::LowerLegLeft => "Cẳng chân trái",
            BodyPart::UpperArmLeft => "Bắp tay trái",
            BodyPart::UpperArmRight => "Bắp tay phải",
            BodyPart::LowerArmLeft => "Cẳng tay trái",
            BodyPart::LowerArmRight => "Cẳng tay phải",
            BodyPart::Head => "Đầu",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_validation() {
        let config = DensePoseConfig::default();
        assert!(config.validate().is_ok());

        let invalid_config = DensePoseConfig {
            input_channels: 0,
            ..Default::default()
        };
        assert!(invalid_config.validate().is_err());
    }

    #[test]
    fn test_densepose_head_creation() {
        let config = DensePoseConfig::new(256, 24, 2);
        let head = DensePoseHead::new(config).unwrap();
        assert!(!head.has_weights());
    }

    #[test]
    fn test_forward_without_weights_errors() {
        let config = DensePoseConfig::new(256, 24, 2);
        let head = DensePoseHead::new(config).unwrap();

        let input = Tensor::zeros_4d([1, 256, 64, 64]);
        let result = head.forward(&input);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Chưa tải trọng số mô hình"));
    }

    #[test]
    fn test_mock_forward_pass() {
        let config = DensePoseConfig::new(256, 24, 2);
        let head = DensePoseHead::new(config).unwrap();

        let input = Tensor::zeros_4d([1, 256, 64, 64]);
        let output = head.forward_mock(&input).unwrap();

        // Kiểm tra hình dạng đầu ra
        assert_eq!(output.segmentation.shape().dim(1), Some(25)); // 24 + 1 nền
        assert_eq!(output.uv_coordinates.shape().dim(1), Some(2));
    }

    #[test]
    fn test_body_part_enum() {
        assert_eq!(BodyPart::from_index(0), Some(BodyPart::Background));
        assert_eq!(BodyPart::from_index(14), Some(BodyPart::Head));
        assert_eq!(BodyPart::from_index(100), None);

        assert_eq!(BodyPart::Torso.name(), "Thân");
    }
}
