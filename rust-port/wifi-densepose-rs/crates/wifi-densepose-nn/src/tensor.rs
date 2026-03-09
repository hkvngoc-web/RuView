//! Các kiểu tensor và thao tác cho suy luận mạng nơ-ron.
//!
//! Mô-đun này cung cấp trừu tượng tensor thống nhất hoạt động trên
//! các backend khác nhau (ONNX, tch, Candle).

use crate::error::{NnError, NnResult};
use ndarray::{Array1, Array2, Array3, Array4, ArrayD};
// num_traits có sẵn nếu cần cho các thao tác tensor nâng cao
use serde::{Deserialize, Serialize};
use std::fmt;

/// Hình dạng của tensor
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TensorShape(Vec<usize>);

impl TensorShape {
    /// Tạo hình dạng tensor mới
    pub fn new(dims: Vec<usize>) -> Self {
        Self(dims)
    }

    /// Tạo hình dạng từ lát
    pub fn from_slice(dims: &[usize]) -> Self {
        Self(dims.to_vec())
    }

    /// Lấy số chiều
    pub fn ndim(&self) -> usize {
        self.0.len()
    }

    /// Lấy các chiều
    pub fn dims(&self) -> &[usize] {
        &self.0
    }

    /// Lấy tổng số phần tử
    pub fn numel(&self) -> usize {
        self.0.iter().product()
    }

    /// Lấy chiều tại chỉ số
    pub fn dim(&self, idx: usize) -> Option<usize> {
        self.0.get(idx).copied()
    }

    /// Kiểm tra hình dạng có tương thích broadcast không
    pub fn is_broadcast_compatible(&self, other: &TensorShape) -> bool {
        let max_dims = self.ndim().max(other.ndim());
        for i in 0..max_dims {
            let d1 = self.0.get(self.ndim().saturating_sub(i + 1)).unwrap_or(&1);
            let d2 = other.0.get(other.ndim().saturating_sub(i + 1)).unwrap_or(&1);
            if *d1 != *d2 && *d1 != 1 && *d2 != 1 {
                return false;
            }
        }
        true
    }
}

impl fmt::Display for TensorShape {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "[")?;
        for (i, d) in self.0.iter().enumerate() {
            if i > 0 {
                write!(f, ", ")?;
            }
            write!(f, "{}", d)?;
        }
        write!(f, "]")
    }
}

impl From<Vec<usize>> for TensorShape {
    fn from(dims: Vec<usize>) -> Self {
        Self::new(dims)
    }
}

impl From<&[usize]> for TensorShape {
    fn from(dims: &[usize]) -> Self {
        Self::from_slice(dims)
    }
}

impl<const N: usize> From<[usize; N]> for TensorShape {
    fn from(dims: [usize; N]) -> Self {
        Self::new(dims.to_vec())
    }
}

/// Kiểu dữ liệu cho phần tử tensor
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DataType {
    /// Số thực dấu phẩy động 32-bit
    Float32,
    /// Số thực dấu phẩy động 64-bit
    Float64,
    /// Số nguyên 32-bit
    Int32,
    /// Số nguyên 64-bit
    Int64,
    /// Số nguyên không dấu 8-bit
    Uint8,
    /// Boolean
    Bool,
}

impl DataType {
    /// Lấy kích thước kiểu dữ liệu tính bằng byte
    pub fn size_bytes(&self) -> usize {
        match self {
            DataType::Float32 => 4,
            DataType::Float64 => 8,
            DataType::Int32 => 4,
            DataType::Int64 => 8,
            DataType::Uint8 => 1,
            DataType::Bool => 1,
        }
    }
}

/// Bao bọc tensor trừu tượng hóa các kiểu mảng khác nhau
#[derive(Debug, Clone)]
pub enum Tensor {
    /// Tensor thực 1D
    Float1D(Array1<f32>),
    /// Tensor thực 2D
    Float2D(Array2<f32>),
    /// Tensor thực 3D
    Float3D(Array3<f32>),
    /// Tensor thực 4D (lô, kênh, chiều cao, chiều rộng)
    Float4D(Array4<f32>),
    /// Tensor thực nhiều chiều động
    FloatND(ArrayD<f32>),
    /// Tensor nguyên 1D
    Int1D(Array1<i64>),
    /// Tensor nguyên 2D
    Int2D(Array2<i64>),
    /// Tensor nguyên nhiều chiều động
    IntND(ArrayD<i64>),
}

impl Tensor {
    /// Tạo tensor thực 4D mới chứa toàn số không
    pub fn zeros_4d(shape: [usize; 4]) -> Self {
        Tensor::Float4D(Array4::zeros(shape))
    }

    /// Tạo tensor thực 4D mới chứa toàn số một
    pub fn ones_4d(shape: [usize; 4]) -> Self {
        Tensor::Float4D(Array4::ones(shape))
    }

    /// Tạo tensor từ mảng ndarray 4D
    pub fn from_array4(array: Array4<f32>) -> Self {
        Tensor::Float4D(array)
    }

    /// Tạo tensor từ mảng ndarray nhiều chiều động
    pub fn from_arrayd(array: ArrayD<f32>) -> Self {
        Tensor::FloatND(array)
    }

    /// Lấy hình dạng của tensor
    pub fn shape(&self) -> TensorShape {
        match self {
            Tensor::Float1D(a) => TensorShape::from_slice(a.shape()),
            Tensor::Float2D(a) => TensorShape::from_slice(a.shape()),
            Tensor::Float3D(a) => TensorShape::from_slice(a.shape()),
            Tensor::Float4D(a) => TensorShape::from_slice(a.shape()),
            Tensor::FloatND(a) => TensorShape::from_slice(a.shape()),
            Tensor::Int1D(a) => TensorShape::from_slice(a.shape()),
            Tensor::Int2D(a) => TensorShape::from_slice(a.shape()),
            Tensor::IntND(a) => TensorShape::from_slice(a.shape()),
        }
    }

    /// Lấy kiểu dữ liệu
    pub fn dtype(&self) -> DataType {
        match self {
            Tensor::Float1D(_)
            | Tensor::Float2D(_)
            | Tensor::Float3D(_)
            | Tensor::Float4D(_)
            | Tensor::FloatND(_) => DataType::Float32,
            Tensor::Int1D(_) | Tensor::Int2D(_) | Tensor::IntND(_) => DataType::Int64,
        }
    }

    /// Lấy số phần tử
    pub fn numel(&self) -> usize {
        self.shape().numel()
    }

    /// Lấy số chiều
    pub fn ndim(&self) -> usize {
        self.shape().ndim()
    }

    /// Thử chuyển đổi sang mảng thực 4D
    pub fn as_array4(&self) -> NnResult<&Array4<f32>> {
        match self {
            Tensor::Float4D(a) => Ok(a),
            _ => Err(NnError::tensor_op("Không thể chuyển đổi sang mảng 4D")),
        }
    }

    /// Thử chuyển đổi sang mảng thực 4D có thể thay đổi
    pub fn as_array4_mut(&mut self) -> NnResult<&mut Array4<f32>> {
        match self {
            Tensor::Float4D(a) => Ok(a),
            _ => Err(NnError::tensor_op("Không thể chuyển đổi sang mảng 4D có thể thay đổi")),
        }
    }

    /// Lấy dữ liệu bên dưới dạng lát
    pub fn as_slice(&self) -> NnResult<&[f32]> {
        match self {
            Tensor::Float1D(a) => a.as_slice().ok_or_else(|| NnError::tensor_op("Mảng không liền kề")),
            Tensor::Float2D(a) => a.as_slice().ok_or_else(|| NnError::tensor_op("Mảng không liền kề")),
            Tensor::Float3D(a) => a.as_slice().ok_or_else(|| NnError::tensor_op("Mảng không liền kề")),
            Tensor::Float4D(a) => a.as_slice().ok_or_else(|| NnError::tensor_op("Mảng không liền kề")),
            Tensor::FloatND(a) => a.as_slice().ok_or_else(|| NnError::tensor_op("Mảng không liền kề")),
            _ => Err(NnError::tensor_op("Không thể lấy lát thực từ tensor nguyên")),
        }
    }

    /// Chuyển đổi tensor sang Vec sở hữu
    pub fn to_vec(&self) -> NnResult<Vec<f32>> {
        match self {
            Tensor::Float1D(a) => Ok(a.iter().copied().collect()),
            Tensor::Float2D(a) => Ok(a.iter().copied().collect()),
            Tensor::Float3D(a) => Ok(a.iter().copied().collect()),
            Tensor::Float4D(a) => Ok(a.iter().copied().collect()),
            Tensor::FloatND(a) => Ok(a.iter().copied().collect()),
            _ => Err(NnError::tensor_op("Không thể chuyển tensor nguyên sang vec thực")),
        }
    }

    /// Áp dụng hàm kích hoạt ReLU
    pub fn relu(&self) -> NnResult<Tensor> {
        match self {
            Tensor::Float4D(a) => Ok(Tensor::Float4D(a.mapv(|x| x.max(0.0)))),
            Tensor::FloatND(a) => Ok(Tensor::FloatND(a.mapv(|x| x.max(0.0)))),
            _ => Err(NnError::tensor_op("ReLU không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Áp dụng hàm kích hoạt sigmoid
    pub fn sigmoid(&self) -> NnResult<Tensor> {
        match self {
            Tensor::Float4D(a) => Ok(Tensor::Float4D(a.mapv(|x| 1.0 / (1.0 + (-x).exp())))),
            Tensor::FloatND(a) => Ok(Tensor::FloatND(a.mapv(|x| 1.0 / (1.0 + (-x).exp())))),
            _ => Err(NnError::tensor_op("Sigmoid không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Áp dụng hàm kích hoạt tanh
    pub fn tanh(&self) -> NnResult<Tensor> {
        match self {
            Tensor::Float4D(a) => Ok(Tensor::Float4D(a.mapv(|x| x.tanh()))),
            Tensor::FloatND(a) => Ok(Tensor::FloatND(a.mapv(|x| x.tanh()))),
            _ => Err(NnError::tensor_op("Tanh không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Áp dụng softmax theo trục
    pub fn softmax(&self, axis: usize) -> NnResult<Tensor> {
        match self {
            Tensor::Float4D(a) => {
                let max = a.fold(f32::NEG_INFINITY, |acc, &x| acc.max(x));
                let exp = a.mapv(|x| (x - max).exp());
                let sum = exp.sum();
                Ok(Tensor::Float4D(exp / sum))
            }
            _ => Err(NnError::tensor_op("Softmax không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Lấy argmax theo trục
    pub fn argmax(&self, axis: usize) -> NnResult<Tensor> {
        match self {
            Tensor::Float4D(a) => {
                let result = a.map_axis(ndarray::Axis(axis), |row| {
                    row.iter()
                        .enumerate()
                        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
                        .map(|(i, _)| i as i64)
                        .unwrap_or(0)
                });
                Ok(Tensor::IntND(result.into_dyn()))
            }
            _ => Err(NnError::tensor_op("Argmax không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Tính trung bình
    pub fn mean(&self) -> NnResult<f32> {
        match self {
            Tensor::Float4D(a) => Ok(a.mean().unwrap_or(0.0)),
            Tensor::FloatND(a) => Ok(a.mean().unwrap_or(0.0)),
            _ => Err(NnError::tensor_op("Trung bình không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Tính độ lệch chuẩn
    pub fn std(&self) -> NnResult<f32> {
        match self {
            Tensor::Float4D(a) => {
                let mean = a.mean().unwrap_or(0.0);
                let variance = a.mapv(|x| (x - mean).powi(2)).mean().unwrap_or(0.0);
                Ok(variance.sqrt())
            }
            Tensor::FloatND(a) => {
                let mean = a.mean().unwrap_or(0.0);
                let variance = a.mapv(|x| (x - mean).powi(2)).mean().unwrap_or(0.0);
                Ok(variance.sqrt())
            }
            _ => Err(NnError::tensor_op("Độ lệch chuẩn không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Lấy giá trị nhỏ nhất
    pub fn min(&self) -> NnResult<f32> {
        match self {
            Tensor::Float4D(a) => Ok(a.fold(f32::INFINITY, |acc, &x| acc.min(x))),
            Tensor::FloatND(a) => Ok(a.fold(f32::INFINITY, |acc, &x| acc.min(x))),
            _ => Err(NnError::tensor_op("Min không được hỗ trợ cho kiểu tensor này")),
        }
    }

    /// Lấy giá trị lớn nhất
    pub fn max(&self) -> NnResult<f32> {
        match self {
            Tensor::Float4D(a) => Ok(a.fold(f32::NEG_INFINITY, |acc, &x| acc.max(x))),
            Tensor::FloatND(a) => Ok(a.fold(f32::NEG_INFINITY, |acc, &x| acc.max(x))),
            _ => Err(NnError::tensor_op("Max không được hỗ trợ cho kiểu tensor này")),
        }
    }
}

/// Thống kê về một tensor
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TensorStats {
    /// Giá trị trung bình
    pub mean: f32,
    /// Độ lệch chuẩn
    pub std: f32,
    /// Giá trị nhỏ nhất
    pub min: f32,
    /// Giá trị lớn nhất
    pub max: f32,
    /// Độ thưa (tỷ lệ phần tử bằng 0)
    pub sparsity: f32,
}

impl TensorStats {
    /// Tính thống kê cho một tensor
    pub fn from_tensor(tensor: &Tensor) -> NnResult<Self> {
        let mean = tensor.mean()?;
        let std = tensor.std()?;
        let min = tensor.min()?;
        let max = tensor.max()?;

        // Tính độ thưa
        let sparsity = match tensor {
            Tensor::Float4D(a) => {
                let zeros = a.iter().filter(|&&x| x == 0.0).count();
                zeros as f32 / a.len() as f32
            }
            Tensor::FloatND(a) => {
                let zeros = a.iter().filter(|&&x| x == 0.0).count();
                zeros as f32 / a.len() as f32
            }
            _ => 0.0,
        };

        Ok(TensorStats {
            mean,
            std,
            min,
            max,
            sparsity,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tensor_shape() {
        let shape = TensorShape::new(vec![1, 3, 224, 224]);
        assert_eq!(shape.ndim(), 4);
        assert_eq!(shape.numel(), 1 * 3 * 224 * 224);
        assert_eq!(shape.dim(0), Some(1));
        assert_eq!(shape.dim(1), Some(3));
    }

    #[test]
    fn test_tensor_zeros() {
        let tensor = Tensor::zeros_4d([1, 256, 64, 64]);
        assert_eq!(tensor.shape().dims(), &[1, 256, 64, 64]);
        assert_eq!(tensor.dtype(), DataType::Float32);
    }

    #[test]
    fn test_tensor_activations() {
        let arr = Array4::from_elem([1, 2, 2, 2], -1.0f32);
        let tensor = Tensor::Float4D(arr);

        let relu = tensor.relu().unwrap();
        assert_eq!(relu.max().unwrap(), 0.0);

        let sigmoid = tensor.sigmoid().unwrap();
        assert!(sigmoid.min().unwrap() > 0.0);
        assert!(sigmoid.max().unwrap() < 1.0);
    }

    #[test]
    fn test_broadcast_compatible() {
        let a = TensorShape::new(vec![1, 3, 224, 224]);
        let b = TensorShape::new(vec![1, 1, 224, 224]);
        assert!(a.is_broadcast_compatible(&b));

        // [1, 3, 224, 224] và [2, 3, 224, 224] CÓ tương thích broadcast (1 broadcast thành 2)
        let c = TensorShape::new(vec![2, 3, 224, 224]);
        assert!(a.is_broadcast_compatible(&c));

        // [2, 3, 224, 224] và [3, 3, 224, 224] KHÔNG tương thích (2 != 3, cả hai đều không phải 1)
        let d = TensorShape::new(vec![3, 3, 224, 224]);
        assert!(!c.is_broadcast_compatible(&d));
    }
}
