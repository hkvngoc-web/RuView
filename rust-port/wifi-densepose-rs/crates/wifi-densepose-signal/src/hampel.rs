//! Bộ lọc Hampel cho phát hiện và loại bỏ ngoại lai bền vững.
//!
//! Sử dụng trung vị trượt và MAD (Độ lệch tuyệt đối trung vị) thay vì
//! trung bình/độ lệch chuẩn, giúp chống chịu được đến 50% nhiễm bẩn — không giống
//! phương pháp Z-score nơi ngoại lai làm hỏng trung bình và che giấu chính mình.
//!
//! # Tài liệu tham khảo
//! - Hampel (1974), "The Influence Curve and its Role in Robust Estimation"
//! - Sử dụng trong WiGest (SenSys 2015), WiDance (MobiCom 2017)

/// Cấu hình cho bộ lọc Hampel.
#[derive(Debug, Clone)]
pub struct HampelConfig {
    /// Nửa kích thước cửa sổ (tổng cửa sổ = 2*half_window + 1)
    pub half_window: usize,
    /// Ngưỡng tính bằng đơn vị σ ước lượng (thường là 3.0)
    pub threshold: f64,
}

impl Default for HampelConfig {
    fn default() -> Self {
        Self {
            half_window: 3,
            threshold: 3.0,
        }
    }
}

/// Kết quả lọc Hampel.
#[derive(Debug, Clone)]
pub struct HampelResult {
    /// Tín hiệu đã lọc (ngoại lai được thay bằng trung vị cục bộ)
    pub filtered: Vec<f64>,
    /// Các chỉ số nơi ngoại lai được phát hiện
    pub outlier_indices: Vec<usize>,
    /// Giá trị trung vị cục bộ tại mỗi mẫu
    pub medians: Vec<f64>,
    /// σ cục bộ ước lượng tại mỗi mẫu
    pub sigma_estimates: Vec<f64>,
}

/// Hệ số tỷ lệ chuyển đổi MAD sang σ cho phân phối Gauss.
/// MAD = 0.6745 * σ → σ = MAD / 0.6745 = 1.4826 * MAD
const MAD_SCALE: f64 = 1.4826;

/// Áp dụng bộ lọc Hampel cho tín hiệu 1D.
///
/// Với mỗi mẫu, tính trung vị và MAD của cửa sổ xung quanh.
/// Nếu mẫu lệch khỏi trung vị nhiều hơn `threshold * σ_est`,
/// nó được thay bằng trung vị.
pub fn hampel_filter(signal: &[f64], config: &HampelConfig) -> Result<HampelResult, HampelError> {
    if signal.is_empty() {
        return Err(HampelError::EmptySignal);
    }
    if config.half_window == 0 {
        return Err(HampelError::InvalidWindow);
    }

    let n = signal.len();
    let mut filtered = signal.to_vec();
    let mut outlier_indices = Vec::new();
    let mut medians = Vec::with_capacity(n);
    let mut sigma_estimates = Vec::with_capacity(n);

    for i in 0..n {
        let start = i.saturating_sub(config.half_window);
        let end = (i + config.half_window + 1).min(n);
        let window: Vec<f64> = signal[start..end].to_vec();

        let med = median(&window);
        let mad = median_absolute_deviation(&window, med);
        let sigma = MAD_SCALE * mad;

        medians.push(med);
        sigma_estimates.push(sigma);

        let deviation = (signal[i] - med).abs();
        let is_outlier = if sigma > 1e-15 {
            // Trường hợp bình thường: so sánh độ lệch với threshold * sigma
            deviation > config.threshold * sigma
        } else {
            // Trường hợp MAD bằng 0: tất cả giá trị cửa sổ giống nhau trừ có thể mẫu này.
            // Bất kỳ độ lệch khác 0 nào so với trung vị là ngoại lai.
            deviation > 1e-15
        };

        if is_outlier {
            filtered[i] = med;
            outlier_indices.push(i);
        }
    }

    Ok(HampelResult {
        filtered,
        outlier_indices,
        medians,
        sigma_estimates,
    })
}

/// Áp dụng bộ lọc Hampel cho mỗi hàng của mảng 2D (ví dụ: CSI theo từng anten).
pub fn hampel_filter_2d(
    data: &[Vec<f64>],
    config: &HampelConfig,
) -> Result<Vec<HampelResult>, HampelError> {
    data.iter().map(|row| hampel_filter(row, config)).collect()
}

/// Tính trung vị của một lát (sắp xếp bản sao).
fn median(data: &[f64]) -> f64 {
    if data.is_empty() {
        return 0.0;
    }
    let mut sorted = data.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mid = sorted.len() / 2;
    if sorted.len() % 2 == 0 {
        (sorted[mid - 1] + sorted[mid]) / 2.0
    } else {
        sorted[mid]
    }
}

/// Tính MAD (Độ lệch tuyệt đối trung vị) với trung vị đã tính sẵn.
fn median_absolute_deviation(data: &[f64], med: f64) -> f64 {
    let deviations: Vec<f64> = data.iter().map(|x| (x - med).abs()).collect();
    median(&deviations)
}

/// Các lỗi từ bộ lọc Hampel.
#[derive(Debug, thiserror::Error)]
pub enum HampelError {
    #[error("Tín hiệu rỗng")]
    EmptySignal,
    #[error("Nửa cửa sổ phải > 0")]
    InvalidWindow,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clean_signal_unchanged() {
        // Sóng sin mượt không nên có ngoại lai
        let signal: Vec<f64> = (0..100)
            .map(|i| (i as f64 * 0.1).sin())
            .collect();

        let result = hampel_filter(&signal, &HampelConfig::default()).unwrap();
        assert!(result.outlier_indices.is_empty());

        for i in 0..signal.len() {
            assert!(
                (result.filtered[i] - signal[i]).abs() < 1e-10,
                "Tín hiệu sạch bị thay đổi tại chỉ số {}",
                i
            );
        }
    }

    #[test]
    fn test_single_spike_detected() {
        let mut signal: Vec<f64> = vec![1.0; 50];
        signal[25] = 100.0; // Đỉnh nhọn lớn

        let result = hampel_filter(&signal, &HampelConfig::default()).unwrap();
        assert!(result.outlier_indices.contains(&25));
        assert!((result.filtered[25] - 1.0).abs() < 1e-10); // Được thay bằng trung vị
    }

    #[test]
    fn test_multiple_spikes() {
        let mut signal: Vec<f64> = (0..200)
            .map(|i| (i as f64 * 0.05).sin())
            .collect();

        // Chèn đỉnh nhọn
        signal[30] = 50.0;
        signal[100] = -50.0;
        signal[170] = 80.0;

        let config = HampelConfig {
            half_window: 5,
            threshold: 3.0,
        };
        let result = hampel_filter(&signal, &config).unwrap();

        assert!(result.outlier_indices.contains(&30));
        assert!(result.outlier_indices.contains(&100));
        assert!(result.outlier_indices.contains(&170));
    }

    #[test]
    fn test_z_score_masking_resistance() {
        // 50 mẫu sạch + nhiều ngoại lai: Z-score sẽ thất bại, Hampel phải hoạt động
        let mut signal: Vec<f64> = vec![0.0; 100];
        // Chèn 30% nhiễm bẩn (Z-score sẽ bị nhầm lẫn)
        for i in (0..100).step_by(3) {
            signal[i] = 50.0;
        }

        let config = HampelConfig {
            half_window: 5,
            threshold: 3.0,
        };
        let result = hampel_filter(&signal, &config).unwrap();

        // Các mẫu bị nhiễm phải được phát hiện là ngoại lai
        assert!(!result.outlier_indices.is_empty());
    }

    #[test]
    fn test_2d_filtering() {
        let rows = vec![
            vec![1.0, 1.0, 100.0, 1.0, 1.0, 1.0, 1.0],
            vec![2.0, 2.0, 2.0, 2.0, -80.0, 2.0, 2.0],
        ];

        let results = hampel_filter_2d(&rows, &HampelConfig::default()).unwrap();
        assert_eq!(results.len(), 2);
        assert!(results[0].outlier_indices.contains(&2));
        assert!(results[1].outlier_indices.contains(&4));
    }

    #[test]
    fn test_median_computation() {
        assert!((median(&[1.0, 3.0, 2.0]) - 2.0).abs() < 1e-10);
        assert!((median(&[1.0, 2.0, 3.0, 4.0]) - 2.5).abs() < 1e-10);
        assert!((median(&[5.0]) - 5.0).abs() < 1e-10);
    }

    #[test]
    fn test_empty_signal_error() {
        assert!(matches!(
            hampel_filter(&[], &HampelConfig::default()),
            Err(HampelError::EmptySignal)
        ));
    }
}
