//! Các hàm tiện ích dùng chung cho hệ thống WiFi-DensePose.
//!
//! Module này cung cấp các hàm trợ giúp được sử dụng xuyên suốt crate.

use ndarray::{Array1, Array2};
use num_complex::Complex64;

/// Tính độ lớn (giá trị tuyệt đối) của số phức.
#[must_use]
pub fn complex_magnitude(data: &Array2<Complex64>) -> Array2<f64> {
    data.mapv(num_complex::Complex::norm)
}

/// Tính pha (đối số) của số phức tính bằng radian.
#[must_use]
pub fn complex_phase(data: &Array2<Complex64>) -> Array2<f64> {
    data.mapv(num_complex::Complex::arg)
}

/// Tháo cuộn giá trị pha để loại bỏ gián đoạn.
///
/// Tháo cuộn pha sửa các bước nhảy 2*pi xảy ra khi giá trị pha
/// cuộn vòng từ pi sang -pi.
#[must_use]
pub fn unwrap_phase(phase: &Array1<f64>) -> Array1<f64> {
    let mut unwrapped = phase.clone();
    let pi = std::f64::consts::PI;
    let two_pi = 2.0 * pi;

    for i in 1..unwrapped.len() {
        let diff = unwrapped[i] - unwrapped[i - 1];
        if diff > pi {
            for j in i..unwrapped.len() {
                unwrapped[j] -= two_pi;
            }
        } else if diff < -pi {
            for j in i..unwrapped.len() {
                unwrapped[j] += two_pi;
            }
        }
    }

    unwrapped
}

/// Chuẩn hoá giá trị về phạm vi [0, 1].
#[must_use]
pub fn normalize_min_max(data: &Array1<f64>) -> Array1<f64> {
    let min = data.iter().copied().fold(f64::INFINITY, f64::min);
    let max = data.iter().copied().fold(f64::NEG_INFINITY, f64::max);

    if (max - min).abs() < f64::EPSILON {
        return Array1::zeros(data.len());
    }

    data.mapv(|x| (x - min) / (max - min))
}

/// Chuẩn hoá giá trị sử dụng chuẩn hoá z-score.
#[must_use]
pub fn normalize_zscore(data: &Array1<f64>) -> Array1<f64> {
    let mean = data.mean().unwrap_or(0.0);
    let std = data.std(0.0);

    if std.abs() < f64::EPSILON {
        return Array1::zeros(data.len());
    }

    data.mapv(|x| (x - mean) / std)
}

/// Tính Tỷ số Tín hiệu trên Nhiễu tính bằng dB.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn calculate_snr_db(signal: &Array1<f64>, noise: &Array1<f64>) -> f64 {
    let signal_power: f64 = signal.iter().map(|x| x * x).sum::<f64>() / signal.len() as f64;
    let noise_power: f64 = noise.iter().map(|x| x * x).sum::<f64>() / noise.len() as f64;

    if noise_power.abs() < f64::EPSILON {
        return f64::INFINITY;
    }

    10.0 * (signal_power / noise_power).log10()
}

/// Áp dụng bộ lọc trung bình trượt.
///
/// # Panic
///
/// Panic nếu mảng dữ liệu không liên tục trong bộ nhớ.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn moving_average(data: &Array1<f64>, window_size: usize) -> Array1<f64> {
    if window_size == 0 || window_size > data.len() {
        return data.clone();
    }

    let mut result = Array1::zeros(data.len());
    let half_window = window_size / 2;

    // ndarray Array1 luôn liên tục, nhưng xử lý mượt mà nếu không
    let slice = match data.as_slice() {
        Some(s) => s,
        None => return data.clone(),
    };

    for i in 0..data.len() {
        let start = i.saturating_sub(half_window);
        let end = (i + half_window + 1).min(data.len());
        let window = &slice[start..end];
        result[i] = window.iter().sum::<f64>() / window.len() as f64;
    }

    result
}

/// Kẹp giá trị vào một phạm vi.
#[must_use]
pub fn clamp<T: PartialOrd>(value: T, min: T, max: T) -> T {
    if value < min {
        min
    } else if value > max {
        max
    } else {
        value
    }
}

/// Nội suy tuyến tính giữa hai giá trị.
#[must_use]
pub fn lerp(a: f64, b: f64, t: f64) -> f64 {
    (b - a).mul_add(t, a)
}

/// Chuyển đổi độ sang radian.
#[must_use]
pub fn deg_to_rad(degrees: f64) -> f64 {
    degrees.to_radians()
}

/// Chuyển đổi radian sang độ.
#[must_use]
pub fn rad_to_deg(radians: f64) -> f64 {
    radians.to_degrees()
}

/// Tính khoảng cách Euclid giữa hai điểm.
#[must_use]
pub fn euclidean_distance(p1: (f64, f64), p2: (f64, f64)) -> f64 {
    let dx = p2.0 - p1.0;
    let dy = p2.1 - p1.1;
    dx.hypot(dy)
}

/// Tính khoảng cách Euclid trong không gian 3D.
#[must_use]
pub fn euclidean_distance_3d(p1: (f64, f64, f64), p2: (f64, f64, f64)) -> f64 {
    let dx = p2.0 - p1.0;
    let dy = p2.1 - p1.1;
    let dz = p2.2 - p1.2;
    (dx.mul_add(dx, dy.mul_add(dy, dz * dz))).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::array;

    #[test]
    fn test_normalize_min_max() {
        let data = array![0.0, 5.0, 10.0];
        let normalized = normalize_min_max(&data);

        assert!((normalized[0] - 0.0).abs() < 1e-10);
        assert!((normalized[1] - 0.5).abs() < 1e-10);
        assert!((normalized[2] - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_normalize_zscore() {
        let data = array![1.0, 2.0, 3.0, 4.0, 5.0];
        let normalized = normalize_zscore(&data);

        // Trung bình phải xấp xỉ 0
        assert!(normalized.mean().unwrap().abs() < 1e-10);
    }

    #[test]
    fn test_moving_average() {
        let data = array![1.0, 2.0, 3.0, 4.0, 5.0];
        let smoothed = moving_average(&data, 3);

        // Giá trị giữa phải là trung bình của 2, 3, 4
        assert!((smoothed[2] - 3.0).abs() < 1e-10);
    }

    #[test]
    fn test_clamp() {
        assert_eq!(clamp(5, 0, 10), 5);
        assert_eq!(clamp(-5, 0, 10), 0);
        assert_eq!(clamp(15, 0, 10), 10);
    }

    #[test]
    fn test_lerp() {
        assert!((lerp(0.0, 10.0, 0.5) - 5.0).abs() < 1e-10);
        assert!((lerp(0.0, 10.0, 0.0) - 0.0).abs() < 1e-10);
        assert!((lerp(0.0, 10.0, 1.0) - 10.0).abs() < 1e-10);
    }

    #[test]
    fn test_deg_rad_conversion() {
        let degrees = 180.0;
        let radians = deg_to_rad(degrees);
        assert!((radians - std::f64::consts::PI).abs() < 1e-10);

        let back = rad_to_deg(radians);
        assert!((back - degrees).abs() < 1e-10);
    }

    #[test]
    fn test_euclidean_distance() {
        let dist = euclidean_distance((0.0, 0.0), (3.0, 4.0));
        assert!((dist - 5.0).abs() < 1e-10);
    }

    #[test]
    fn test_unwrap_phase() {
        let pi = std::f64::consts::PI;
        // Mô phỏng cuộn pha
        let phase = array![0.0, pi / 2.0, pi, -pi + 0.1, -pi / 2.0];
        let unwrapped = unwrap_phase(&phase);

        // Sau khi tháo cuộn, pha phải tăng đơn điệu
        for i in 1..unwrapped.len() {
            // Cho phép dung sai cho việc sửa gián đoạn
            assert!(
                unwrapped[i] >= unwrapped[i - 1] - 0.5,
                "Pha phải tăng dần sau khi tháo cuộn"
            );
        }
    }

    #[test]
    fn test_snr_calculation() {
        let signal = array![1.0, 1.0, 1.0, 1.0];
        let noise = array![0.1, 0.1, 0.1, 0.1];

        let snr = calculate_snr_db(&signal, &noise);
        // SNR phải là 20 dB (10 * log10(1/0.01) = 10 * log10(100) = 20)
        assert!((snr - 20.0).abs() < 1e-10);
    }
}
