//! Mô hình hô hấp vùng Fresnel
//!
//! Mô hình biến thiên tín hiệu WiFi như hàm của dịch chuyển ngực người
//! vượt qua ranh giới vùng Fresnel. Ở tần số 5 GHz (λ=60mm), dịch chuyển ngực
//! 5-10mm khi thở là phần đáng kể của độ rộng vùng Fresnel,
//! tạo ra thay đổi pha và biên độ có thể đo được.
//!
//! # Tài liệu tham khảo
//! - FarSense: Pushing the Range Limit (MobiCom 2019)
//! - Wi-Sleep: Contactless Sleep Staging (UbiComp 2021)

use ruvector_solver::neumann::NeumannSolver;
use ruvector_solver::types::CsrMatrix;
use std::f64::consts::PI;

/// Hằng số vật lý và giá trị mặc định cho cảm biến WiFi.
pub const SPEED_OF_LIGHT: f64 = 2.998e8; // m/s

/// Hình học vùng Fresnel cho cấu hình TX-RX-cơ thể.
#[derive(Debug, Clone)]
pub struct FresnelGeometry {
    /// Khoảng cách từ TX đến điểm phản xạ trên cơ thể (mét)
    pub d_tx_body: f64,
    /// Khoảng cách từ điểm phản xạ trên cơ thể đến RX (mét)
    pub d_body_rx: f64,
    /// Tần số sóng mang tính bằng Hz (ví dụ: 5.8e9 cho 5.8 GHz)
    pub frequency: f64,
}

impl FresnelGeometry {
    /// Tạo hình học cho cấu hình TX-cơ thể-RX cho trước.
    pub fn new(d_tx_body: f64, d_body_rx: f64, frequency: f64) -> Result<Self, FresnelError> {
        if d_tx_body <= 0.0 || d_body_rx <= 0.0 {
            return Err(FresnelError::InvalidDistance);
        }
        if frequency <= 0.0 {
            return Err(FresnelError::InvalidFrequency);
        }
        Ok(Self {
            d_tx_body,
            d_body_rx,
            frequency,
        })
    }

    /// Bước sóng tính bằng mét.
    pub fn wavelength(&self) -> f64 {
        SPEED_OF_LIGHT / self.frequency
    }

    /// Bán kính vùng Fresnel thứ n tại điểm cơ thể.
    ///
    /// F_n = sqrt(n * λ * d1 * d2 / (d1 + d2))
    pub fn fresnel_radius(&self, n: u32) -> f64 {
        let lambda = self.wavelength();
        let d1 = self.d_tx_body;
        let d2 = self.d_body_rx;
        (n as f64 * lambda * d1 * d2 / (d1 + d2)).sqrt()
    }

    /// Thay đổi pha gây ra bởi dịch chuyển nhỏ Δd (mét) của cơ thể.
    ///
    /// Đường phản xạ thay đổi 2*Δd (đi và về), tạo ra
    /// thay đổi pha: ΔΦ = 2π * 2Δd / λ
    pub fn phase_change(&self, displacement_m: f64) -> f64 {
        2.0 * PI * 2.0 * displacement_m / self.wavelength()
    }

    /// Biến thiên biên độ dự kiến từ dịch chuyển ngực.
    ///
    /// Biên độ tín hiệu biến thiên như |sin(ΔΦ/2)| khi điểm phản xạ
    /// vượt qua ranh giới vùng Fresnel.
    pub fn expected_amplitude_variation(&self, displacement_m: f64) -> f64 {
        let delta_phi = self.phase_change(displacement_m);
        (delta_phi / 2.0).sin().abs()
    }
}

/// Ước lượng nhịp thở sử dụng mô hình vùng Fresnel.
#[derive(Debug, Clone)]
pub struct FresnelBreathingEstimator {
    geometry: FresnelGeometry,
    /// Phạm vi dịch chuyển ngực dự kiến (mét) cho hô hấp
    min_displacement: f64,
    max_displacement: f64,
}

impl FresnelBreathingEstimator {
    /// Tạo bộ ước lượng với hình học và giới hạn dịch chuyển ngực.
    ///
    /// Dịch chuyển ngực người lớn thông thường: 4-12mm (0.004-0.012 m)
    pub fn new(geometry: FresnelGeometry) -> Self {
        Self {
            geometry,
            min_displacement: 0.003,
            max_displacement: 0.015,
        }
    }

    /// Kiểm tra biến thiên biên độ quan sát có nhất quán với hô hấp không.
    ///
    /// Trả về độ tin cậy (0.0-1.0) dựa trên việc biến thiên tín hiệu quan sát
    /// có khớp với dự đoán mô hình Fresnel cho dịch chuyển ngực
    /// trong phạm vi hô hấp hay không.
    pub fn breathing_confidence(&self, observed_amplitude_variation: f64) -> f64 {
        let min_expected = self.geometry.expected_amplitude_variation(self.min_displacement);
        let max_expected = self.geometry.expected_amplitude_variation(self.max_displacement);

        let (low, high) = if min_expected < max_expected {
            (min_expected, max_expected)
        } else {
            (max_expected, min_expected)
        };

        if observed_amplitude_variation >= low && observed_amplitude_variation <= high {
            // Trong phạm vi dự kiến: độ tin cậy cao
            1.0
        } else if observed_amplitude_variation < low {
            // Dưới phạm vi: tỷ lệ tuyến tính
            (observed_amplitude_variation / low).clamp(0.0, 1.0)
        } else {
            // Trên phạm vi: có thể là chuyển động lớn hơn (đi bộ), độ tin cậy thấp cho hô hấp
            (high / observed_amplitude_variation).clamp(0.0, 1.0)
        }
    }

    /// Ước lượng nhịp thở từ tín hiệu biên độ theo thời gian sử dụng mô hình Fresnel.
    ///
    /// Sử dụng tự tương quan để tìm tính tuần hoàn, sau đó kiểm chứng với
    /// phạm vi biên độ Fresnel dự kiến. Trả về (nhịp_bpm, độ_tin_cậy).
    pub fn estimate_breathing_rate(
        &self,
        amplitude_signal: &[f64],
        sample_rate: f64,
    ) -> Result<BreathingEstimate, FresnelError> {
        if amplitude_signal.len() < 10 {
            return Err(FresnelError::InsufficientData {
                needed: 10,
                got: amplitude_signal.len(),
            });
        }
        if sample_rate <= 0.0 {
            return Err(FresnelError::InvalidFrequency);
        }

        // Loại bỏ DC (trung bình)
        let mean: f64 = amplitude_signal.iter().sum::<f64>() / amplitude_signal.len() as f64;
        let centered: Vec<f64> = amplitude_signal.iter().map(|x| x - mean).collect();

        // Tự tương quan để tìm tính tuần hoàn
        let n = centered.len();
        let max_lag = (sample_rate * 10.0) as usize; // Tối đa 10 giây (6 BPM)
        let min_lag = (sample_rate * 1.5) as usize; // Tối thiểu 1.5 giây (40 BPM)
        let max_lag = max_lag.min(n / 2);

        if min_lag >= max_lag {
            return Err(FresnelError::InsufficientData {
                needed: (min_lag * 2 + 1),
                got: n,
            });
        }

        // Tính tự tương quan cho các trễ trong phạm vi hô hấp
        let mut best_lag = min_lag;
        let mut best_corr = f64::NEG_INFINITY;
        let norm: f64 = centered.iter().map(|x| x * x).sum();

        if norm < 1e-15 {
            return Err(FresnelError::NoSignal);
        }

        for lag in min_lag..max_lag {
            let mut corr = 0.0;
            for i in 0..(n - lag) {
                corr += centered[i] * centered[i + lag];
            }
            corr /= norm;

            if corr > best_corr {
                best_corr = corr;
                best_lag = lag;
            }
        }

        let period_seconds = best_lag as f64 / sample_rate;
        let rate_bpm = 60.0 / period_seconds;

        // Tính biến thiên biên độ cho độ tin cậy Fresnel
        let amp_var = amplitude_variation(&centered);
        let fresnel_conf = self.breathing_confidence(amp_var);

        // Chất lượng tự tương quan (>0.3 là tuần hoàn tốt)
        let autocorr_conf = best_corr.max(0.0).min(1.0);

        let confidence = fresnel_conf * 0.4 + autocorr_conf * 0.6;

        Ok(BreathingEstimate {
            rate_bpm,
            confidence,
            period_seconds,
            autocorrelation_peak: best_corr,
            fresnel_confidence: fresnel_conf,
            amplitude_variation: amp_var,
        })
    }
}

/// Kết quả ước lượng nhịp thở.
#[derive(Debug, Clone)]
pub struct BreathingEstimate {
    /// Nhịp thở ước lượng tính bằng nhịp mỗi phút
    pub rate_bpm: f64,
    /// Độ tin cậy tổng hợp (0.0-1.0)
    pub confidence: f64,
    /// Chu kỳ thở ước lượng tính bằng giây
    pub period_seconds: f64,
    /// Giá trị đỉnh tự tương quan tại chu kỳ phát hiện
    pub autocorrelation_peak: f64,
    /// Độ tin cậy từ khớp mô hình Fresnel
    pub fresnel_confidence: f64,
    /// Biến thiên biên độ quan sát
    pub amplitude_variation: f64,
}

/// Tính biến thiên biên độ đỉnh-đến-đỉnh (chuẩn hóa).
fn amplitude_variation(signal: &[f64]) -> f64 {
    if signal.is_empty() {
        return 0.0;
    }
    let max = signal.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let min = signal.iter().cloned().fold(f64::INFINITY, f64::min);
    max - min
}

/// Ước lượng khoảng cách TX-cơ thể và cơ thể-RX từ quan sát Fresnel đa sóng mang con.
///
/// Khi hình học chính xác không biết, nhiều bước sóng sóng mang con cung cấp
/// các lần vượt vùng Fresnel khác nhau cho cùng dịch chuyển ngực. Hàm này
/// giải hệ thống quá xác định kết quả để ước lượng d1 (TX→cơ thể)
/// và d2 (cơ thể→RX).
///
/// # Tham số
/// * `observations` - Vec các (bước_sóng_m, biến_thiên_biên_độ_quan_sát) từ các sóng mang con khác nhau
/// * `d_total` - Khoảng cách đường thẳng TX-RX đã biết tính bằng mét
///
/// # Trả về
/// Some((d1, d2)) nếu giải được với ≥3 quan sát, None nếu không
pub fn solve_fresnel_geometry(
    observations: &[(f32, f32)],
    d_total: f32,
) -> Option<(f32, f32)> {
    let n = observations.len();
    if n < 3 {
        return None;
    }

    // Thu thập hệ số theo bước sóng
    let inv_w_sq_sum: f32 = observations.iter().map(|(w, _)| 1.0 / (w * w)).sum();
    let a_over_w_sum: f32 = observations.iter().map(|(w, a)| a / w).sum();

    // Phương trình chuẩn cho [d1, d2]^T với chính quy hóa Tikhonov tương đối λ=0.5*inv_w_sq_sum.
    // Tỷ lệ tương đối đảm bảo ma trận lặp Jacobi có bán kính phổ ~0.667,
    // nằm trong giới hạn hội tụ yêu cầu bởi NeumannSolver.
    // (A^T A + λI) x = A^T b
    // Cho hệ tuyến tính hóa: coefficient[0] = 1/w, coefficient[1] = -1/w
    // Vậy A^T A = [[inv_w_sq_sum, -inv_w_sq_sum], [-inv_w_sq_sum, inv_w_sq_sum]] + λI
    let lambda = 0.5 * inv_w_sq_sum;
    let a00 = inv_w_sq_sum + lambda;
    let a11 = inv_w_sq_sum + lambda;
    let a01 = -inv_w_sq_sum;

    let ata = CsrMatrix::<f32>::from_coo(
        2,
        2,
        vec![(0, 0, a00), (0, 1, a01), (1, 0, a01), (1, 1, a11)],
    );
    let atb = vec![a_over_w_sum, -a_over_w_sum];

    let solver = NeumannSolver::new(1e-5, 300);
    match solver.solve(&ata, &atb) {
        Ok(result) => {
            let d1 = result.solution[0].abs().clamp(0.1, d_total - 0.1);
            let d2 = (d_total - d1).clamp(0.1, d_total - 0.1);
            Some((d1, d2))
        }
        Err(_) => None,
    }
}

#[cfg(test)]
mod solver_fresnel_tests {
    use super::*;

    #[test]
    fn fresnel_geometry_insufficient_obs() {
        // < 3 quan sát → None
        let obs = vec![(0.06_f32, 0.5_f32), (0.05, 0.4)];
        assert!(solve_fresnel_geometry(&obs, 5.0).is_none());
    }

    #[test]
    fn fresnel_geometry_returns_valid_distances() {
        let obs = vec![
            (0.06_f32, 0.3_f32),
            (0.055, 0.25),
            (0.05, 0.35),
            (0.045, 0.2),
        ];
        let result = solve_fresnel_geometry(&obs, 5.0);
        assert!(result.is_some(), "phải giải được với 4 quan sát");
        let (d1, d2) = result.unwrap();
        assert!(d1 > 0.0 && d1 < 5.0, "d1={d1} ngoài phạm vi");
        assert!(d2 > 0.0 && d2 < 5.0, "d2={d2} ngoài phạm vi");
        assert!((d1 + d2 - 5.0).abs() < 0.01, "d1+d2 phải ≈ d_total");
    }
}

/// Các lỗi từ tính toán Fresnel.
#[derive(Debug, thiserror::Error)]
pub enum FresnelError {
    #[error("Khoảng cách phải dương")]
    InvalidDistance,

    #[error("Tần số phải dương")]
    InvalidFrequency,

    #[error("Không đủ dữ liệu: cần {needed}, có {got}")]
    InsufficientData { needed: usize, got: usize },

    #[error("Không phát hiện tín hiệu (phương sai bằng 0)")]
    NoSignal,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_geometry() -> FresnelGeometry {
        // TX cách cơ thể 3m, cơ thể cách RX 2m, WiFi 5 GHz
        FresnelGeometry::new(3.0, 2.0, 5.0e9).unwrap()
    }

    #[test]
    fn test_wavelength() {
        let g = test_geometry();
        let lambda = g.wavelength();
        assert!((lambda - 0.06).abs() < 0.001); // 5 GHz → 60mm
    }

    #[test]
    fn test_fresnel_radius() {
        let g = test_geometry();
        let f1 = g.fresnel_radius(1);
        // F1 = sqrt(λ * d1 * d2 / (d1 + d2))
        let lambda = g.wavelength(); // thực tế: 2.998e8 / 5e9 = 0.05996
        let expected = (lambda * 3.0 * 2.0 / 5.0_f64).sqrt();
        assert!((f1 - expected).abs() < 1e-6);
        assert!(f1 > 0.1 && f1 < 0.5); // Phạm vi hợp lý
    }

    #[test]
    fn test_phase_change_from_displacement() {
        let g = test_geometry();
        // Dịch chuyển ngực 5mm ở 5 GHz
        let delta_phi = g.phase_change(0.005);
        // ΔΦ = 2π * 2 * 0.005 / λ
        let lambda = g.wavelength();
        let expected = 2.0 * PI * 2.0 * 0.005 / lambda;
        assert!((delta_phi - expected).abs() < 1e-6);
    }

    #[test]
    fn test_amplitude_variation_breathing_range() {
        let g = test_geometry();
        // Dịch chuyển 5mm phải tạo biến thiên có thể phát hiện
        let var_5mm = g.expected_amplitude_variation(0.005);
        assert!(var_5mm > 0.01, "5mm phải tạo biến thiên có thể đo được");

        // 10mm phải tạo biến thiên lớn hơn
        let var_10mm = g.expected_amplitude_variation(0.010);
        assert!(var_10mm > var_5mm || (var_10mm - var_5mm).abs() < 0.1);
    }

    #[test]
    fn test_breathing_confidence() {
        let g = test_geometry();
        let estimator = FresnelBreathingEstimator::new(g.clone());

        // Tín hiệu khớp phạm vi hô hấp dự kiến → độ tin cậy cao
        let expected_var = g.expected_amplitude_variation(0.007);
        let conf = estimator.breathing_confidence(expected_var);
        assert!(conf > 0.5, "Biến thiên hô hấp dự kiến phải cho độ tin cậy cao");

        // Biến thiên bằng 0 → độ tin cậy thấp
        let conf_zero = estimator.breathing_confidence(0.0);
        assert!(conf_zero < 0.5);
    }

    #[test]
    fn test_breathing_rate_estimation() {
        let g = test_geometry();
        let estimator = FresnelBreathingEstimator::new(g);

        // Sinh 30 giây tín hiệu hô hấp ở 16 BPM (0.267 Hz)
        let sample_rate = 100.0; // Hz
        let duration = 30.0;
        let n = (sample_rate * duration) as usize;
        let breathing_freq = 0.267; // 16 BPM

        let signal: Vec<f64> = (0..n)
            .map(|i| {
                let t = i as f64 / sample_rate;
                0.5 + 0.1 * (2.0 * PI * breathing_freq * t).sin()
            })
            .collect();

        let result = estimator
            .estimate_breathing_rate(&signal, sample_rate)
            .unwrap();

        // Phải phát hiện ~16 BPM (trong dung sai 2 BPM)
        assert!(
            (result.rate_bpm - 16.0).abs() < 2.0,
            "Kỳ vọng ~16 BPM, nhận được {:.1}",
            result.rate_bpm
        );
        assert!(result.confidence > 0.3);
        assert!(result.autocorrelation_peak > 0.5);
    }

    #[test]
    fn test_invalid_geometry() {
        assert!(FresnelGeometry::new(-1.0, 2.0, 5e9).is_err());
        assert!(FresnelGeometry::new(1.0, 0.0, 5e9).is_err());
        assert!(FresnelGeometry::new(1.0, 2.0, 0.0).is_err());
    }

    #[test]
    fn test_insufficient_data() {
        let g = test_geometry();
        let estimator = FresnelBreathingEstimator::new(g);
        let short_signal = vec![1.0; 5];
        assert!(matches!(
            estimator.estimate_breathing_rate(&short_signal, 100.0),
            Err(FresnelError::InsufficientData { .. })
        ));
    }
}
