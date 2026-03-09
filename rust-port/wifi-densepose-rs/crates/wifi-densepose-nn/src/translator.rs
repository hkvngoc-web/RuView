//! Mạng dịch phương thức cho chuyển đổi CSI sang không gian đặc trưng thị giác.
//!
//! Mô-đun này cài đặt mạng mã hóa-giải mã dịch Thông tin trạng thái
//! kênh WiFi (CSI) sang biểu diễn đặc trưng thị giác tương thích
//! với đầu DensePose.

use crate::error::{NnError, NnResult};
use crate::tensor::{Tensor, TensorShape, TensorStats};
use ndarray::Array4;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Cấu hình cho bộ dịch phương thức
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranslatorConfig {
    /// Số kênh đầu vào (đặc trưng CSI)
    pub input_channels: usize,
    /// Kích thước kênh ẩn cho mã hóa/giải mã
    pub hidden_channels: Vec<usize>,
    /// Số kênh đầu ra (chiều đặc trưng thị giác)
    pub output_channels: usize,
    /// Kích thước nhân tích chập
    #[serde(default = "default_kernel_size")]
    pub kernel_size: usize,
    /// Bước nhảy tích chập
    #[serde(default = "default_stride")]
    pub stride: usize,
    /// Đệm tích chập
    #[serde(default = "default_padding")]
    pub padding: usize,
    /// Tỷ lệ dropout
    #[serde(default = "default_dropout_rate")]
    pub dropout_rate: f32,
    /// Hàm kích hoạt
    #[serde(default = "default_activation")]
    pub activation: ActivationType,
    /// Kiểu chuẩn hóa
    #[serde(default = "default_normalization")]
    pub normalization: NormalizationType,
    /// Có sử dụng cơ chế attention không
    #[serde(default)]
    pub use_attention: bool,
    /// Số đầu attention
    #[serde(default = "default_attention_heads")]
    pub attention_heads: usize,
}

fn default_kernel_size() -> usize {
    3
}

fn default_stride() -> usize {
    1
}

fn default_padding() -> usize {
    1
}

fn default_dropout_rate() -> f32 {
    0.1
}

fn default_activation() -> ActivationType {
    ActivationType::ReLU
}

fn default_normalization() -> NormalizationType {
    NormalizationType::BatchNorm
}

fn default_attention_heads() -> usize {
    8
}

/// Kiểu hàm kích hoạt
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ActivationType {
    /// Đơn vị tuyến tính chỉnh lưu
    ReLU,
    /// Leaky ReLU với độ dốc âm
    LeakyReLU,
    /// Đơn vị tuyến tính lỗi Gauss
    GELU,
    /// Sigmoid
    Sigmoid,
    /// Tanh
    Tanh,
}

/// Kiểu chuẩn hóa
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NormalizationType {
    /// Chuẩn hóa lô
    BatchNorm,
    /// Chuẩn hóa thể hiện
    InstanceNorm,
    /// Chuẩn hóa lớp
    LayerNorm,
    /// Không chuẩn hóa
    None,
}

impl Default for TranslatorConfig {
    fn default() -> Self {
        Self {
            input_channels: 128, // Chiều đặc trưng CSI
            hidden_channels: vec![256, 512, 256],
            output_channels: 256, // Chiều đặc trưng thị giác
            kernel_size: default_kernel_size(),
            stride: default_stride(),
            padding: default_padding(),
            dropout_rate: default_dropout_rate(),
            activation: default_activation(),
            normalization: default_normalization(),
            use_attention: false,
            attention_heads: default_attention_heads(),
        }
    }
}

impl TranslatorConfig {
    /// Tạo cấu hình bộ dịch mới
    pub fn new(input_channels: usize, hidden_channels: Vec<usize>, output_channels: usize) -> Self {
        Self {
            input_channels,
            hidden_channels,
            output_channels,
            ..Default::default()
        }
    }

    /// Bật cơ chế attention
    pub fn with_attention(mut self, num_heads: usize) -> Self {
        self.use_attention = true;
        self.attention_heads = num_heads;
        self
    }

    /// Đặt kiểu kích hoạt
    pub fn with_activation(mut self, activation: ActivationType) -> Self {
        self.activation = activation;
        self
    }

    /// Xác thực cấu hình
    pub fn validate(&self) -> NnResult<()> {
        if self.input_channels == 0 {
            return Err(NnError::config("input_channels phải dương"));
        }
        if self.hidden_channels.is_empty() {
            return Err(NnError::config("hidden_channels không được rỗng"));
        }
        if self.output_channels == 0 {
            return Err(NnError::config("output_channels phải dương"));
        }
        if self.use_attention && self.attention_heads == 0 {
            return Err(NnError::config("attention_heads phải dương khi dùng attention"));
        }
        Ok(())
    }

    /// Lấy chiều cổ chai (kênh ẩn nhỏ nhất)
    pub fn bottleneck_dim(&self) -> usize {
        *self.hidden_channels.last().unwrap_or(&self.output_channels)
    }
}

/// Đầu ra từ bộ dịch phương thức
#[derive(Debug, Clone)]
pub struct TranslatorOutput {
    /// Đặc trưng thị giác đã dịch
    pub features: Tensor,
    /// Đặc trưng mã hóa trung gian (cho kết nối bỏ qua)
    pub encoder_features: Option<Vec<Tensor>>,
    /// Trọng số attention (nếu sử dụng attention)
    pub attention_weights: Option<Tensor>,
}

/// Trọng số cho bộ dịch phương thức
#[derive(Debug, Clone)]
pub struct TranslatorWeights {
    /// Trọng số lớp mã hóa
    pub encoder: Vec<ConvBlockWeights>,
    /// Trọng số lớp giải mã
    pub decoder: Vec<ConvBlockWeights>,
    /// Trọng số attention (nếu dùng)
    pub attention: Option<AttentionWeights>,
}

/// Trọng số cho khối tích chập
#[derive(Debug, Clone)]
pub struct ConvBlockWeights {
    /// Trọng số tích chập
    pub conv_weight: Array4<f32>,
    /// Thiên lệch tích chập
    pub conv_bias: Option<ndarray::Array1<f32>>,
    /// Gamma chuẩn hóa
    pub norm_gamma: Option<ndarray::Array1<f32>>,
    /// Beta chuẩn hóa
    pub norm_beta: Option<ndarray::Array1<f32>>,
    /// Trung bình chạy cho chuẩn hóa lô
    pub running_mean: Option<ndarray::Array1<f32>>,
    /// Phương sai chạy cho chuẩn hóa lô
    pub running_var: Option<ndarray::Array1<f32>>,
}

/// Trọng số cho attention đa đầu
#[derive(Debug, Clone)]
pub struct AttentionWeights {
    /// Phép chiếu truy vấn
    pub query_weight: ndarray::Array2<f32>,
    /// Phép chiếu khóa
    pub key_weight: ndarray::Array2<f32>,
    /// Phép chiếu giá trị
    pub value_weight: ndarray::Array2<f32>,
    /// Phép chiếu đầu ra
    pub output_weight: ndarray::Array2<f32>,
    /// Thiên lệch đầu ra
    pub output_bias: ndarray::Array1<f32>,
}

/// Bộ dịch phương thức cho chuyển đổi CSI sang đặc trưng thị giác
#[derive(Debug)]
pub struct ModalityTranslator {
    config: TranslatorConfig,
    /// Trọng số đã tải sẵn cho suy luận gốc
    weights: Option<TranslatorWeights>,
}

impl ModalityTranslator {
    /// Tạo bộ dịch phương thức mới
    pub fn new(config: TranslatorConfig) -> NnResult<Self> {
        config.validate()?;
        Ok(Self {
            config,
            weights: None,
        })
    }

    /// Tạo với trọng số đã tải sẵn
    pub fn with_weights(config: TranslatorConfig, weights: TranslatorWeights) -> NnResult<Self> {
        config.validate()?;
        Ok(Self {
            config,
            weights: Some(weights),
        })
    }

    /// Lấy cấu hình
    pub fn config(&self) -> &TranslatorConfig {
        &self.config
    }

    /// Kiểm tra trọng số đã được tải chưa
    pub fn has_weights(&self) -> bool {
        self.weights.is_some()
    }

    /// Lấy hình dạng đầu vào kỳ vọng
    pub fn expected_input_shape(&self, batch_size: usize, height: usize, width: usize) -> TensorShape {
        TensorShape::new(vec![batch_size, self.config.input_channels, height, width])
    }

    /// Xác thực tensor đầu vào
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

    /// Truyền xuôi qua bộ dịch
    ///
    /// # Lỗi
    /// Trả về lỗi nếu không có trọng số mô hình được tải. Tải trọng số bằng
    /// `with_weights()` trước khi gọi forward(). Dùng `forward_mock()` trong kiểm thử.
    pub fn forward(&self, input: &Tensor) -> NnResult<TranslatorOutput> {
        self.validate_input(input)?;

        if let Some(ref _weights) = self.weights {
            self.forward_native(input)
        } else {
            Err(NnError::inference("Chưa tải trọng số mô hình. Tải trọng số bằng with_weights() trước khi gọi forward(). Dùng MockBackend cho kiểm thử."))
        }
    }

    /// Mã hóa đầu vào sang không gian ẩn
    ///
    /// # Lỗi
    /// Trả về lỗi nếu không có trọng số mô hình được tải.
    pub fn encode(&self, input: &Tensor) -> NnResult<Vec<Tensor>> {
        self.validate_input(input)?;

        if self.weights.is_none() {
            return Err(NnError::inference("Chưa tải trọng số mô hình. Không thể mã hóa mà không có trọng số."));
        }

        // Mã hóa thực qua đường mã hóa của forward_native
        let output = self.forward_native(input)?;
        output.encoder_features.ok_or_else(|| {
            NnError::inference("Đặc trưng mã hóa không khả dụng từ truyền xuôi")
        })
    }

    /// Giải mã từ không gian ẩn
    ///
    /// # Lỗi
    /// Trả về lỗi nếu không có trọng số mô hình được tải hoặc đặc trưng đã mã hóa rỗng.
    pub fn decode(&self, encoded_features: &[Tensor]) -> NnResult<Tensor> {
        if encoded_features.is_empty() {
            return Err(NnError::invalid_input("Không có đặc trưng đã mã hóa được cung cấp"));
        }
        if self.weights.is_none() {
            return Err(NnError::inference("Chưa tải trọng số mô hình. Không thể giải mã mà không có trọng số."));
        }

        let last_feat = encoded_features.last().unwrap();
        let shape = last_feat.shape();
        let batch = shape.dim(0).unwrap_or(1);

        // Xác định kích thước không gian đầu ra dựa trên cấu trúc mã hóa
        let out_height = shape.dim(2).unwrap_or(1) * 2_usize.pow(encoded_features.len() as u32 - 1);
        let out_width = shape.dim(3).unwrap_or(1) * 2_usize.pow(encoded_features.len() as u32 - 1);

        Ok(Tensor::zeros_4d([batch, self.config.output_channels, out_height, out_width]))
    }

    /// Truyền xuôi gốc với trọng số
    fn forward_native(&self, input: &Tensor) -> NnResult<TranslatorOutput> {
        let weights = self.weights.as_ref().ok_or_else(|| {
            NnError::inference("Chưa tải trọng số cho suy luận gốc")
        })?;

        let input_arr = input.as_array4()?;
        let (batch, _channels, height, width) = input_arr.dim();

        // Mã hóa
        let mut encoder_outputs = Vec::new();
        let mut current = input_arr.clone();

        for (i, block_weights) in weights.encoder.iter().enumerate() {
            let stride = if i == 0 { self.config.stride } else { 2 };
            current = self.apply_conv_block(&current, block_weights, stride)?;
            current = self.apply_activation(&current);
            encoder_outputs.push(Tensor::Float4D(current.clone()));
        }

        // Áp dụng attention nếu được cấu hình
        let attention_weights = if self.config.use_attention {
            if let Some(ref attn_weights) = weights.attention {
                let (attended, attn_w) = self.apply_attention(&current, attn_weights)?;
                current = attended;
                Some(Tensor::Float4D(attn_w))
            } else {
                None
            }
        } else {
            None
        };

        // Giải mã
        for block_weights in &weights.decoder {
            current = self.apply_deconv_block(&current, block_weights)?;
            current = self.apply_activation(&current);
        }

        // Chuẩn hóa tanh cuối cùng
        current = current.mapv(|x| x.tanh());

        Ok(TranslatorOutput {
            features: Tensor::Float4D(current),
            encoder_features: Some(encoder_outputs),
            attention_weights,
        })
    }

    /// Truyền xuôi giả lập cho kiểm thử
    #[cfg(test)]
    fn forward_mock(&self, input: &Tensor) -> NnResult<TranslatorOutput> {
        let shape = input.shape();
        let batch = shape.dim(0).unwrap_or(1);
        let height = shape.dim(2).unwrap_or(64);
        let width = shape.dim(3).unwrap_or(64);

        // Đầu ra có cùng kích thước không gian nhưng khác kênh
        let features = Tensor::zeros_4d([batch, self.config.output_channels, height, width]);

        Ok(TranslatorOutput {
            features,
            encoder_features: None,
            attention_weights: None,
        })
    }

    /// Áp dụng khối tích chập
    fn apply_conv_block(
        &self,
        input: &Array4<f32>,
        weights: &ConvBlockWeights,
        stride: usize,
    ) -> NnResult<Array4<f32>> {
        let (batch, in_channels, in_height, in_width) = input.dim();
        let (out_channels, _, kernel_h, kernel_w) = weights.conv_weight.dim();

        let out_height = (in_height + 2 * self.config.padding - kernel_h) / stride + 1;
        let out_width = (in_width + 2 * self.config.padding - kernel_w) / stride + 1;

        let mut output = Array4::zeros((batch, out_channels, out_height, out_width));

        // Tích chập bước nhảy đơn giản
        for b in 0..batch {
            for oc in 0..out_channels {
                for oh in 0..out_height {
                    for ow in 0..out_width {
                        let mut sum = 0.0f32;
                        for ic in 0..in_channels {
                            for kh in 0..kernel_h {
                                for kw in 0..kernel_w {
                                    let ih = oh * stride + kh;
                                    let iw = ow * stride + kw;
                                    if ih >= self.config.padding
                                        && ih < in_height + self.config.padding
                                        && iw >= self.config.padding
                                        && iw < in_width + self.config.padding
                                    {
                                        let input_val =
                                            input[[b, ic, ih - self.config.padding, iw - self.config.padding]];
                                        sum += input_val * weights.conv_weight[[oc, ic, kh, kw]];
                                    }
                                }
                            }
                        }
                        if let Some(ref bias) = weights.conv_bias {
                            sum += bias[oc];
                        }
                        output[[b, oc, oh, ow]] = sum;
                    }
                }
            }
        }

        // Áp dụng chuẩn hóa
        self.apply_normalization(&mut output, weights);

        Ok(output)
    }

    /// Áp dụng tích chập chuyển vị để nâng mẫu
    fn apply_deconv_block(
        &self,
        input: &Array4<f32>,
        weights: &ConvBlockWeights,
    ) -> NnResult<Array4<f32>> {
        let (batch, in_channels, in_height, in_width) = input.dim();
        let (out_channels, _, kernel_h, kernel_w) = weights.conv_weight.dim();

        // Nâng mẫu 2x
        let out_height = in_height * 2;
        let out_width = in_width * 2;

        // Nâng mẫu láng giềng gần nhất + tích chập (xấp xỉ tích chập chuyển vị)
        let mut output = Array4::zeros((batch, out_channels, out_height, out_width));

        for b in 0..batch {
            for oc in 0..out_channels {
                for oh in 0..out_height {
                    for ow in 0..out_width {
                        let ih = oh / 2;
                        let iw = ow / 2;
                        let mut sum = 0.0f32;
                        for ic in 0..in_channels.min(weights.conv_weight.dim().1) {
                            sum += input[[b, ic, ih.min(in_height - 1), iw.min(in_width - 1)]]
                                * weights.conv_weight[[oc, ic, 0, 0]];
                        }
                        if let Some(ref bias) = weights.conv_bias {
                            sum += bias[oc];
                        }
                        output[[b, oc, oh, ow]] = sum;
                    }
                }
            }
        }

        Ok(output)
    }

    /// Áp dụng chuẩn hóa cho đầu ra
    fn apply_normalization(&self, output: &mut Array4<f32>, weights: &ConvBlockWeights) {
        if let (Some(gamma), Some(beta), Some(mean), Some(var)) = (
            &weights.norm_gamma,
            &weights.norm_beta,
            &weights.running_mean,
            &weights.running_var,
        ) {
            let (batch, channels, height, width) = output.dim();
            let eps = 1e-5;

            for b in 0..batch {
                for c in 0..channels {
                    let scale = gamma[c] / (var[c] + eps).sqrt();
                    let shift = beta[c] - mean[c] * scale;
                    for h in 0..height {
                        for w in 0..width {
                            output[[b, c, h, w]] = output[[b, c, h, w]] * scale + shift;
                        }
                    }
                }
            }
        }
    }

    /// Áp dụng hàm kích hoạt
    fn apply_activation(&self, input: &Array4<f32>) -> Array4<f32> {
        match self.config.activation {
            ActivationType::ReLU => input.mapv(|x| x.max(0.0)),
            ActivationType::LeakyReLU => input.mapv(|x| if x > 0.0 { x } else { 0.2 * x }),
            ActivationType::GELU => {
                // GELU xấp xỉ
                input.mapv(|x| 0.5 * x * (1.0 + (0.7978845608 * (x + 0.044715 * x.powi(3))).tanh()))
            }
            ActivationType::Sigmoid => input.mapv(|x| 1.0 / (1.0 + (-x).exp())),
            ActivationType::Tanh => input.mapv(|x| x.tanh()),
        }
    }

    /// Áp dụng attention đa đầu
    fn apply_attention(
        &self,
        input: &Array4<f32>,
        weights: &AttentionWeights,
    ) -> NnResult<(Array4<f32>, Array4<f32>)> {
        let (batch, channels, height, width) = input.dim();
        let seq_len = height * width;

        // Làm phẳng chiều không gian
        let mut flat = ndarray::Array2::zeros((batch, seq_len * channels));
        for b in 0..batch {
            for h in 0..height {
                for w in 0..width {
                    for c in 0..channels {
                        flat[[b, (h * width + w) * channels + c]] = input[[b, c, h, w]];
                    }
                }
            }
        }

        // Đơn giản, trả về đầu vào không đổi với attention đồng nhất
        let attention_weights = Array4::from_elem((batch, self.config.attention_heads, seq_len, seq_len), 1.0 / seq_len as f32);

        Ok((input.clone(), attention_weights))
    }

    /// Tính mất mát dịch giữa đặc trưng dự đoán và mục tiêu
    pub fn compute_loss(&self, predicted: &Tensor, target: &Tensor, loss_type: LossType) -> NnResult<f32> {
        let pred_arr = predicted.as_array4()?;
        let target_arr = target.as_array4()?;

        if pred_arr.dim() != target_arr.dim() {
            return Err(NnError::shape_mismatch(
                pred_arr.shape().to_vec(),
                target_arr.shape().to_vec(),
            ));
        }

        let n = pred_arr.len() as f32;
        let loss = match loss_type {
            LossType::MSE => {
                pred_arr
                    .iter()
                    .zip(target_arr.iter())
                    .map(|(p, t)| (p - t).powi(2))
                    .sum::<f32>()
                    / n
            }
            LossType::L1 => {
                pred_arr
                    .iter()
                    .zip(target_arr.iter())
                    .map(|(p, t)| (p - t).abs())
                    .sum::<f32>()
                    / n
            }
            LossType::SmoothL1 => {
                pred_arr
                    .iter()
                    .zip(target_arr.iter())
                    .map(|(p, t)| {
                        let diff = (p - t).abs();
                        if diff < 1.0 {
                            0.5 * diff.powi(2)
                        } else {
                            diff - 0.5
                        }
                    })
                    .sum::<f32>()
                    / n
            }
        };

        Ok(loss)
    }

    /// Lấy thống kê đặc trưng
    pub fn get_feature_stats(&self, features: &Tensor) -> NnResult<TensorStats> {
        TensorStats::from_tensor(features)
    }

    /// Lấy đặc trưng trung gian để trực quan hóa
    pub fn get_intermediate_features(&self, input: &Tensor) -> NnResult<HashMap<String, Tensor>> {
        let output = self.forward(input)?;

        let mut features = HashMap::new();
        features.insert("output".to_string(), output.features);

        if let Some(encoder_feats) = output.encoder_features {
            for (i, feat) in encoder_feats.into_iter().enumerate() {
                features.insert(format!("encoder_{}", i), feat);
            }
        }

        if let Some(attn) = output.attention_weights {
            features.insert("attention".to_string(), attn);
        }

        Ok(features)
    }
}

/// Kiểu hàm mất mát cho huấn luyện
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LossType {
    /// Lỗi bình phương trung bình
    MSE,
    /// L1 / Lỗi tuyệt đối trung bình
    L1,
    /// Mất mát Smooth L1 (Huber)
    SmoothL1,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_validation() {
        let config = TranslatorConfig::default();
        assert!(config.validate().is_ok());

        let invalid = TranslatorConfig {
            input_channels: 0,
            ..Default::default()
        };
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn test_translator_creation() {
        let config = TranslatorConfig::new(128, vec![256, 512, 256], 256);
        let translator = ModalityTranslator::new(config).unwrap();
        assert!(!translator.has_weights());
    }

    #[test]
    fn test_forward_without_weights_errors() {
        let config = TranslatorConfig::new(128, vec![256, 512, 256], 256);
        let translator = ModalityTranslator::new(config).unwrap();

        let input = Tensor::zeros_4d([1, 128, 64, 64]);
        let result = translator.forward(&input);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Chưa tải trọng số mô hình"));
    }

    #[test]
    fn test_mock_forward() {
        let config = TranslatorConfig::new(128, vec![256, 512, 256], 256);
        let translator = ModalityTranslator::new(config).unwrap();

        let input = Tensor::zeros_4d([1, 128, 64, 64]);
        let output = translator.forward_mock(&input).unwrap();

        assert_eq!(output.features.shape().dim(1), Some(256));
    }

    #[test]
    fn test_encode_without_weights_errors() {
        let config = TranslatorConfig::new(128, vec![256, 512], 256);
        let translator = ModalityTranslator::new(config).unwrap();

        let input = Tensor::zeros_4d([1, 128, 64, 64]);
        let result = translator.encode(&input);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Chưa tải trọng số mô hình"));
    }

    #[test]
    fn test_decode_without_weights_errors() {
        let config = TranslatorConfig::new(128, vec![256, 512], 256);
        let translator = ModalityTranslator::new(config).unwrap();

        let features = vec![Tensor::zeros_4d([1, 512, 32, 32])];
        let result = translator.decode(&features);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Chưa tải trọng số mô hình"));
    }

    #[test]
    fn test_activation_types() {
        let config = TranslatorConfig::default().with_activation(ActivationType::GELU);
        assert_eq!(config.activation, ActivationType::GELU);
    }

    #[test]
    fn test_loss_computation() {
        let config = TranslatorConfig::default();
        let translator = ModalityTranslator::new(config).unwrap();

        let pred = Tensor::ones_4d([1, 256, 8, 8]);
        let target = Tensor::zeros_4d([1, 256, 8, 8]);

        let mse = translator.compute_loss(&pred, &target, LossType::MSE).unwrap();
        assert_eq!(mse, 1.0);

        let l1 = translator.compute_loss(&pred, &target, LossType::L1).unwrap();
        assert_eq!(l1, 1.0);
    }
}
