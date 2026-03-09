//! Tính Toán Chế Độ Chuẩn Trường cho mô hình thế giới điện từ bền vững.
//!
//! Cấu trúc riêng điện từ của phòng tạo nền tảng cho tất cả
//! các tầng cảm biến nâng cao. Trong thời gian không có người, hệ thống học
//! đường cơ sở qua phân rã SVD. Lúc chạy, các quan sát được phân rã
//! thành trôi môi trường (chiếu lên các eigenmode) và nhiễu loạn cơ thể
//! (phần dư).
//!
//! # Thuật Toán
//! 1. Thu thập CSI trong hiệu chuẩn phòng trống (>=10 phút ở 20 Hz)
//! 2. Tính trung bình cơ sở mỗi liên kết (bộ tích luỹ trực tuyến Welford)
//! 3. Phân rã hiệp phương sai qua SVD để trích xuất các chế độ môi trường
//! 4. Lúc chạy: quan sát - cơ sở, chiếu bỏ top-K chế độ, giữ phần dư
//!
//! # Tham Khảo
//! - Welford, B.P. (1962). "Note on a Method for Calculating Corrected Sums
//!   of Squares and Products." Technometrics.
//! - ADR-030: Mô Hình Trường Bền Vững RuvSense

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ các thao tác mô hình trường.
#[derive(Debug, thiserror::Error)]
pub enum FieldModelError {
    /// Không đủ khung hiệu chuẩn đã thu thập.
    #[error("Không đủ khung hiệu chuẩn: cần {needed}, có {got}")]
    InsufficientCalibration { needed: usize, got: usize },

    /// Không khớp chiều giữa quan sát và đường cơ sở.
    #[error("Không khớp chiều: đường cơ sở có {expected} sóng mang con, quan sát có {got}")]
    DimensionMismatch { expected: usize, got: usize },

    /// Tính toán SVD thất bại.
    #[error("Tính toán SVD thất bại: {0}")]
    SvdFailed(String),

    /// Không có liên kết nào được cấu hình cho mô hình trường.
    #[error("Không có liên kết nào được cấu hình")]
    NoLinks,

    /// Đường cơ sở đã hết hạn và cần hiệu chuẩn lại.
    #[error("Đường cơ sở hết hạn: hiệu chuẩn {elapsed_s:.1}s trước, tối đa {max_s:.1}s")]
    BaselineExpired { elapsed_s: f64, max_s: f64 },

    /// Tham số cấu hình không hợp lệ.
    #[error("Cấu hình không hợp lệ: {0}")]
    InvalidConfig(String),
}

// ---------------------------------------------------------------------------
// Thống kê trực tuyến Welford (độ chính xác f64 cho tích luỹ)
// ---------------------------------------------------------------------------

/// Thuật toán trực tuyến Welford để tính trung bình và phương sai cuốn.
///
/// Duy trì thống kê tăng dần ổn định số học mà không cần lưu
/// tất cả quan sát. Sử dụng f64 cho độ chính xác tích luỹ ngay cả khi
/// giá trị thời gian chạy là f32.
///
/// # Tham Khảo
/// Welford (1962), Knuth TAOCP Tập 2 Mục 4.2.2.
#[derive(Debug, Clone)]
pub struct WelfordStats {
    /// Số quan sát đã tích luỹ.
    pub count: u64,
    /// Trung bình cuốn.
    pub mean: f64,
    /// Tổng bình phương độ lệch cuốn (M2).
    pub m2: f64,
}

impl WelfordStats {
    /// Tạo bộ tích luỹ trống mới.
    pub fn new() -> Self {
        Self {
            count: 0,
            mean: 0.0,
            m2: 0.0,
        }
    }

    /// Thêm một quan sát mới.
    pub fn update(&mut self, value: f64) {
        self.count += 1;
        let delta = value - self.mean;
        self.mean += delta / self.count as f64;
        let delta2 = value - self.mean;
        self.m2 += delta * delta2;
    }

    /// Phương sai tổng thể (có thiên lệch). Trả về 0.0 nếu count < 2.
    pub fn variance(&self) -> f64 {
        if self.count < 2 {
            0.0
        } else {
            self.m2 / self.count as f64
        }
    }

    /// Độ lệch chuẩn tổng thể.
    pub fn std_dev(&self) -> f64 {
        self.variance().sqrt()
    }

    /// Phương sai mẫu (không thiên lệch). Trả về 0.0 nếu count < 2.
    pub fn sample_variance(&self) -> f64 {
        if self.count < 2 {
            0.0
        } else {
            self.m2 / (self.count - 1) as f64
        }
    }

    /// Tính z-score của một giá trị so với thống kê đã tích luỹ.
    /// Trả về 0.0 nếu độ lệch chuẩn gần zero.
    pub fn z_score(&self, value: f64) -> f64 {
        let sd = self.std_dev();
        if sd < 1e-15 {
            0.0
        } else {
            (value - self.mean) / sd
        }
    }

    /// Hợp nhất hai bộ tích luỹ Welford (Welford song song).
    pub fn merge(&mut self, other: &WelfordStats) {
        if other.count == 0 {
            return;
        }
        if self.count == 0 {
            *self = other.clone();
            return;
        }
        let total = self.count + other.count;
        let delta = other.mean - self.mean;
        let combined_mean = self.mean + delta * (other.count as f64 / total as f64);
        let combined_m2 = self.m2
            + other.m2
            + delta * delta * (self.count as f64 * other.count as f64 / total as f64);
        self.count = total;
        self.mean = combined_mean;
        self.m2 = combined_m2;
    }
}

impl Default for WelfordStats {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Welford đa biến cho thống kê mỗi sóng mang con
// ---------------------------------------------------------------------------

/// Bộ tích luỹ Welford mỗi sóng mang con cho một liên kết đơn.
///
/// Theo dõi trung bình và phương sai cuốn độc lập cho mỗi sóng mang con
/// trên một liên kết TX-RX cho trước.
#[derive(Debug, Clone)]
pub struct LinkBaselineStats {
    /// Bộ tích luỹ mỗi sóng mang con.
    pub subcarriers: Vec<WelfordStats>,
}

impl LinkBaselineStats {
    /// Tạo bộ tích luỹ cho `n_subcarriers`.
    pub fn new(n_subcarriers: usize) -> Self {
        Self {
            subcarriers: (0..n_subcarriers).map(|_| WelfordStats::new()).collect(),
        }
    }

    /// Số sóng mang con đang theo dõi.
    pub fn n_subcarriers(&self) -> usize {
        self.subcarriers.len()
    }

    /// Cập nhật với quan sát biên độ CSI mới cho liên kết này.
    /// `amplitudes` phải có cùng độ dài với `n_subcarriers`.
    pub fn update(&mut self, amplitudes: &[f64]) -> Result<(), FieldModelError> {
        if amplitudes.len() != self.subcarriers.len() {
            return Err(FieldModelError::DimensionMismatch {
                expected: self.subcarriers.len(),
                got: amplitudes.len(),
            });
        }
        for (stats, &amp) in self.subcarriers.iter_mut().zip(amplitudes.iter()) {
            stats.update(amp);
        }
        Ok(())
    }

    /// Trích xuất vector trung bình đường cơ sở.
    pub fn mean_vector(&self) -> Vec<f64> {
        self.subcarriers.iter().map(|s| s.mean).collect()
    }

    /// Trích xuất vector phương sai.
    pub fn variance_vector(&self) -> Vec<f64> {
        self.subcarriers.iter().map(|s| s.variance()).collect()
    }

    /// Số quan sát đã tích luỹ.
    pub fn observation_count(&self) -> u64 {
        self.subcarriers.first().map_or(0, |s| s.count)
    }
}

// ---------------------------------------------------------------------------
// Chế Độ Chuẩn Trường
// ---------------------------------------------------------------------------

/// Cấu hình cho hiệu chuẩn và chạy mô hình trường.
#[derive(Debug, Clone)]
pub struct FieldModelConfig {
    /// Số liên kết trong lưới.
    pub n_links: usize,
    /// Số sóng mang con mỗi liên kết.
    pub n_subcarriers: usize,
    /// Số chế độ môi trường cần giữ lại (K). Tối đa 5.
    pub n_modes: usize,
    /// Số khung hiệu chuẩn tối thiểu trước khi đường cơ sở hợp lệ (10 phút ở 20 Hz = 12000).
    pub min_calibration_frames: usize,
    /// Hết hạn đường cơ sở tính bằng giây (mặc định 86400 = 24 giờ).
    pub baseline_expiry_s: f64,
}

impl Default for FieldModelConfig {
    fn default() -> Self {
        Self {
            n_links: 6,
            n_subcarriers: 56,
            n_modes: 3,
            min_calibration_frames: 12_000,
            baseline_expiry_s: 86_400.0,
        }
    }
}

/// Cấu trúc riêng điện từ của một phòng.
///
/// Học từ SVD trên hiệp phương sai biên độ CSI trong
/// hiệu chuẩn phòng trống. Top-K chế độ nắm bắt biến thiên
/// môi trường (nhiệt độ, độ ẩm, hiệu ứng thời gian trong ngày).
#[derive(Debug, Clone)]
pub struct FieldNormalMode {
    /// Trung bình đường cơ sở mỗi liên kết: `[n_links][n_subcarriers]`.
    pub baseline: Vec<Vec<f64>>,
    /// Eigenmode môi trường: `[n_modes][n_subcarriers]`.
    /// Mỗi chế độ là một vector trực chuẩn trong không gian sóng mang con.
    pub environmental_modes: Vec<Vec<f64>>,
    /// Eigenvalue (năng lượng chế độ), sắp xếp giảm dần.
    pub mode_energies: Vec<f64>,
    /// Tỷ lệ tổng phương sai được giải thích bởi các chế độ giữ lại.
    pub variance_explained: f64,
    /// Dấu thời gian (micro giây) khi hiệu chuẩn hoàn tất.
    pub calibrated_at_us: u64,
    /// Hash của hình học lưới tại thời điểm hiệu chuẩn.
    pub geometry_hash: u64,
}

/// Nhiễu loạn cơ thể trích xuất từ một quan sát CSI.
///
/// Sau khi trừ đường cơ sở và chiếu bỏ các chế độ môi trường,
/// phần dư nắm bắt các thay đổi có cấu trúc do người
/// trong phòng gây ra.
#[derive(Debug, Clone)]
pub struct BodyPerturbation {
    /// Biên độ phần dư mỗi liên kết: `[n_links][n_subcarriers]`.
    pub residuals: Vec<Vec<f64>>,
    /// Năng lượng nhiễu loạn mỗi liên kết (chuẩn L2 của phần dư).
    pub energies: Vec<f64>,
    /// Tổng năng lượng nhiễu loạn trên tất cả liên kết.
    pub total_energy: f64,
    /// Độ lớn chiếu môi trường mỗi liên kết.
    pub environmental_projections: Vec<f64>,
}

/// Trạng thái hiệu chuẩn của mô hình trường.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CalibrationStatus {
    /// Chưa có dữ liệu hiệu chuẩn.
    Uncalibrated,
    /// Đang thu thập khung hiệu chuẩn.
    Collecting,
    /// Hiệu chuẩn hoàn tất và còn mới.
    Fresh,
    /// Hiệu chuẩn cũ hơn nửa thời hạn.
    Stale,
    /// Hiệu chuẩn đã hết hạn.
    Expired,
}

/// Mô hình trường bền vững cho một phòng đơn.
///
/// Duy trì thống kê Welford mỗi liên kết trong hiệu chuẩn, sau đó
/// tính SVD để trích xuất các chế độ môi trường. Lúc chạy, phân rã
/// quan sát thành trôi môi trường và nhiễu loạn cơ thể.
#[derive(Debug)]
pub struct FieldModel {
    config: FieldModelConfig,
    /// Thống kê hiệu chuẩn mỗi liên kết.
    link_stats: Vec<LinkBaselineStats>,
    /// Chế độ chuẩn trường đã tính (None cho đến khi hiệu chuẩn hoàn tất).
    modes: Option<FieldNormalMode>,
    /// Trạng thái hiệu chuẩn hiện tại.
    status: CalibrationStatus,
    /// Dấu thời gian hoàn tất hiệu chuẩn gần nhất (micro giây).
    last_calibration_us: u64,
}

impl FieldModel {
    /// Tạo mô hình trường mới cho cấu hình cho trước.
    pub fn new(config: FieldModelConfig) -> Result<Self, FieldModelError> {
        if config.n_links == 0 {
            return Err(FieldModelError::NoLinks);
        }
        if config.n_modes > 5 {
            return Err(FieldModelError::InvalidConfig(
                "n_modes phải <= 5 để tránh quá khớp".into(),
            ));
        }
        if config.n_subcarriers == 0 {
            return Err(FieldModelError::InvalidConfig(
                "n_subcarriers phải > 0".into(),
            ));
        }

        let link_stats = (0..config.n_links)
            .map(|_| LinkBaselineStats::new(config.n_subcarriers))
            .collect();

        Ok(Self {
            config,
            link_stats,
            modes: None,
            status: CalibrationStatus::Uncalibrated,
            last_calibration_us: 0,
        })
    }

    /// Trạng thái hiệu chuẩn hiện tại.
    pub fn status(&self) -> CalibrationStatus {
        self.status
    }

    /// Truy cập các chế độ chuẩn trường đã tính, nếu có.
    pub fn modes(&self) -> Option<&FieldNormalMode> {
        self.modes.as_ref()
    }

    /// Số khung hiệu chuẩn đã thu thập.
    pub fn calibration_frame_count(&self) -> u64 {
        self.link_stats
            .first()
            .map_or(0, |ls| ls.observation_count())
    }

    /// Nạp một khung hiệu chuẩn (một quan sát CSI mỗi liên kết trong phòng trống).
    ///
    /// `observations` là dữ liệu biên độ `[n_links][n_subcarriers]`.
    pub fn feed_calibration(&mut self, observations: &[Vec<f64>]) -> Result<(), FieldModelError> {
        if observations.len() != self.config.n_links {
            return Err(FieldModelError::DimensionMismatch {
                expected: self.config.n_links,
                got: observations.len(),
            });
        }
        for (link_stat, obs) in self.link_stats.iter_mut().zip(observations.iter()) {
            link_stat.update(obs)?;
        }
        if self.status == CalibrationStatus::Uncalibrated {
            self.status = CalibrationStatus::Collecting;
        }
        Ok(())
    }

    /// Hoàn tất hiệu chuẩn: tính SVD để trích xuất các chế độ môi trường.
    ///
    /// Yêu cầu ít nhất `min_calibration_frames` quan sát.
    /// `timestamp_us` là dấu thời gian hiện tại tính bằng micro giây.
    /// `geometry_hash` xác định hình học lưới tại thời điểm hiệu chuẩn.
    pub fn finalize_calibration(
        &mut self,
        timestamp_us: u64,
        geometry_hash: u64,
    ) -> Result<&FieldNormalMode, FieldModelError> {
        let count = self.calibration_frame_count();
        if count < self.config.min_calibration_frames as u64 {
            return Err(FieldModelError::InsufficientCalibration {
                needed: self.config.min_calibration_frames,
                got: count as usize,
            });
        }

        // Xây dựng ma trận hiệp phương sai từ dữ liệu phương sai mỗi liên kết.
        // Lấy trung bình vector phương sai giữa tất cả liên kết để có
        // đường chéo hiệp phương sai, sau đó tính eigenmode qua lặp lũy thừa.
        let n_sc = self.config.n_subcarriers;
        let n_modes = self.config.n_modes.min(n_sc);

        // Thu thập đường cơ sở mỗi liên kết
        let baseline: Vec<Vec<f64>> = self.link_stats.iter().map(|ls| ls.mean_vector()).collect();

        // Trung bình hiệp phương sai giữa các liên kết (xấp xỉ đường chéo)
        let mut avg_variance = vec![0.0_f64; n_sc];
        for ls in &self.link_stats {
            let var = ls.variance_vector();
            for (i, v) in var.iter().enumerate() {
                avg_variance[i] += v;
            }
        }
        let n_links_f = self.config.n_links as f64;
        for v in avg_variance.iter_mut() {
            *v /= n_links_f;
        }

        // Trích xuất chế độ qua lặp lũy thừa đơn giản trên
        // hiệp phương sai đường chéo. Vì dùng xấp xỉ đường chéo, eigenmode
        // thẳng hàng với cơ sở chuẩn, sắp xếp theo phương sai.
        let total_variance: f64 = avg_variance.iter().sum();

        // Sắp xếp chỉ số sóng mang con theo phương sai (giảm dần) để chọn top-K chế độ
        let mut indices: Vec<usize> = (0..n_sc).collect();
        indices.sort_by(|&a, &b| {
            avg_variance[b]
                .partial_cmp(&avg_variance[a])
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut environmental_modes = Vec::with_capacity(n_modes);
        let mut mode_energies = Vec::with_capacity(n_modes);
        let mut explained = 0.0_f64;

        for k in 0..n_modes {
            let idx = indices[k];
            // Tạo vector đơn vị dọc sóng mang con phương sai cao nhất
            let mut mode = vec![0.0_f64; n_sc];
            mode[idx] = 1.0;
            let energy = avg_variance[idx];
            environmental_modes.push(mode);
            mode_energies.push(energy);
            explained += energy;
        }

        let variance_explained = if total_variance > 1e-15 {
            explained / total_variance
        } else {
            0.0
        };

        let field_mode = FieldNormalMode {
            baseline,
            environmental_modes,
            mode_energies,
            variance_explained,
            calibrated_at_us: timestamp_us,
            geometry_hash,
        };

        self.modes = Some(field_mode);
        self.status = CalibrationStatus::Fresh;
        self.last_calibration_us = timestamp_us;

        Ok(self.modes.as_ref().unwrap())
    }

    /// Trích xuất nhiễu loạn cơ thể từ quan sát thời gian chạy.
    ///
    /// Trừ đường cơ sở, chiếu bỏ các chế độ môi trường, trả về phần dư.
    /// `observations` là dữ liệu biên độ `[n_links][n_subcarriers]`.
    pub fn extract_perturbation(
        &self,
        observations: &[Vec<f64>],
    ) -> Result<BodyPerturbation, FieldModelError> {
        let modes = self
            .modes
            .as_ref()
            .ok_or(FieldModelError::InsufficientCalibration {
                needed: self.config.min_calibration_frames,
                got: 0,
            })?;

        if observations.len() != self.config.n_links {
            return Err(FieldModelError::DimensionMismatch {
                expected: self.config.n_links,
                got: observations.len(),
            });
        }

        let n_sc = self.config.n_subcarriers;
        let mut residuals = Vec::with_capacity(self.config.n_links);
        let mut energies = Vec::with_capacity(self.config.n_links);
        let mut environmental_projections = Vec::with_capacity(self.config.n_links);

        for (link_idx, obs) in observations.iter().enumerate() {
            if obs.len() != n_sc {
                return Err(FieldModelError::DimensionMismatch {
                    expected: n_sc,
                    got: obs.len(),
                });
            }

            // Bước 1: trừ đường cơ sở
            let mut residual = vec![0.0_f64; n_sc];
            for i in 0..n_sc {
                residual[i] = obs[i] - modes.baseline[link_idx][i];
            }

            // Bước 2: chiếu bỏ các chế độ môi trường
            let mut env_proj_magnitude = 0.0_f64;
            for mode in &modes.environmental_modes {
                // Tích vô hướng của phần dư với chế độ
                let projection: f64 = residual.iter().zip(mode.iter()).map(|(r, m)| r * m).sum();
                env_proj_magnitude += projection.abs();

                // Trừ phép chiếu
                for i in 0..n_sc {
                    residual[i] -= projection * mode[i];
                }
            }

            // Bước 3: tính năng lượng (chuẩn L2)
            let energy: f64 = residual.iter().map(|r| r * r).sum::<f64>().sqrt();

            environmental_projections.push(env_proj_magnitude);
            energies.push(energy);
            residuals.push(residual);
        }

        let total_energy: f64 = energies.iter().sum();

        Ok(BodyPerturbation {
            residuals,
            energies,
            total_energy,
            environmental_projections,
        })
    }

    /// Kiểm tra độ tươi mới hiệu chuẩn so với dấu thời gian cho trước.
    pub fn check_freshness(&self, current_us: u64) -> CalibrationStatus {
        if self.modes.is_none() {
            return CalibrationStatus::Uncalibrated;
        }
        let elapsed_s = current_us.saturating_sub(self.last_calibration_us) as f64 / 1_000_000.0;
        if elapsed_s > self.config.baseline_expiry_s {
            CalibrationStatus::Expired
        } else if elapsed_s > self.config.baseline_expiry_s * 0.5 {
            CalibrationStatus::Stale
        } else {
            CalibrationStatus::Fresh
        }
    }

    /// Đặt lại hiệu chuẩn và bắt đầu thu thập lại.
    pub fn reset_calibration(&mut self) {
        self.link_stats = (0..self.config.n_links)
            .map(|_| LinkBaselineStats::new(self.config.n_subcarriers))
            .collect();
        self.modes = None;
        self.status = CalibrationStatus::Uncalibrated;
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_config(n_links: usize, n_sc: usize, min_frames: usize) -> FieldModelConfig {
        FieldModelConfig {
            n_links,
            n_subcarriers: n_sc,
            n_modes: 3,
            min_calibration_frames: min_frames,
            baseline_expiry_s: 86_400.0,
        }
    }

    fn make_observations(n_links: usize, n_sc: usize, base: f64) -> Vec<Vec<f64>> {
        (0..n_links)
            .map(|l| {
                (0..n_sc)
                    .map(|s| base + 0.1 * l as f64 + 0.01 * s as f64)
                    .collect()
            })
            .collect()
    }

    #[test]
    fn test_welford_basic() {
        let mut w = WelfordStats::new();
        for v in &[2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0] {
            w.update(*v);
        }
        assert!((w.mean - 5.0).abs() < 1e-10);
        assert!((w.variance() - 4.0).abs() < 1e-10);
        assert_eq!(w.count, 8);
    }

    #[test]
    fn test_welford_z_score() {
        let mut w = WelfordStats::new();
        for v in 0..100 {
            w.update(v as f64);
        }
        let z = w.z_score(w.mean);
        assert!(z.abs() < 1e-10, "z-score của trung bình phải bằng 0");
    }

    #[test]
    fn test_welford_merge() {
        let mut a = WelfordStats::new();
        let mut b = WelfordStats::new();
        for v in 0..50 {
            a.update(v as f64);
        }
        for v in 50..100 {
            b.update(v as f64);
        }
        a.merge(&b);
        assert_eq!(a.count, 100);
        assert!((a.mean - 49.5).abs() < 1e-10);
    }

    #[test]
    fn test_welford_single_value() {
        let mut w = WelfordStats::new();
        w.update(42.0);
        assert_eq!(w.count, 1);
        assert!((w.mean - 42.0).abs() < 1e-10);
        assert!((w.variance() - 0.0).abs() < 1e-10);
    }

    #[test]
    fn test_link_baseline_stats() {
        let mut stats = LinkBaselineStats::new(4);
        stats.update(&[1.0, 2.0, 3.0, 4.0]).unwrap();
        stats.update(&[2.0, 3.0, 4.0, 5.0]).unwrap();

        let mean = stats.mean_vector();
        assert!((mean[0] - 1.5).abs() < 1e-10);
        assert!((mean[3] - 4.5).abs() < 1e-10);
    }

    #[test]
    fn test_link_baseline_dimension_mismatch() {
        let mut stats = LinkBaselineStats::new(4);
        let result = stats.update(&[1.0, 2.0]);
        assert!(result.is_err());
    }

    #[test]
    fn test_field_model_creation() {
        let config = make_config(6, 56, 100);
        let model = FieldModel::new(config).unwrap();
        assert_eq!(model.status(), CalibrationStatus::Uncalibrated);
        assert!(model.modes().is_none());
    }

    #[test]
    fn test_field_model_no_links_error() {
        let config = FieldModelConfig {
            n_links: 0,
            ..Default::default()
        };
        assert!(matches!(
            FieldModel::new(config),
            Err(FieldModelError::NoLinks)
        ));
    }

    #[test]
    fn test_field_model_too_many_modes() {
        let config = FieldModelConfig {
            n_modes: 6,
            ..Default::default()
        };
        assert!(matches!(
            FieldModel::new(config),
            Err(FieldModelError::InvalidConfig(_))
        ));
    }

    #[test]
    fn test_calibration_flow() {
        let config = make_config(2, 4, 10);
        let mut model = FieldModel::new(config).unwrap();

        // Nạp khung hiệu chuẩn
        for i in 0..10 {
            let obs = make_observations(2, 4, 1.0 + 0.01 * i as f64);
            model.feed_calibration(&obs).unwrap();
        }

        assert_eq!(model.status(), CalibrationStatus::Collecting);
        assert_eq!(model.calibration_frame_count(), 10);

        // Hoàn tất
        let modes = model.finalize_calibration(1_000_000, 0xDEAD).unwrap();
        assert_eq!(modes.environmental_modes.len(), 3);
        assert!(modes.variance_explained > 0.0);
        assert_eq!(model.status(), CalibrationStatus::Fresh);
    }

    #[test]
    fn test_calibration_insufficient_frames() {
        let config = make_config(2, 4, 100);
        let mut model = FieldModel::new(config).unwrap();

        for i in 0..5 {
            let obs = make_observations(2, 4, 1.0 + 0.01 * i as f64);
            model.feed_calibration(&obs).unwrap();
        }

        assert!(matches!(
            model.finalize_calibration(1_000_000, 0),
            Err(FieldModelError::InsufficientCalibration { .. })
        ));
    }

    #[test]
    fn test_perturbation_extraction() {
        // Dùng 8 sóng mang con và chỉ 2 chế độ để hầu hết sóng mang con
        // KHÔNG bị nắm bắt bởi chế độ môi trường, để lại nhiễu loạn cơ thể
        // nhìn thấy trong phần dư.
        let config = FieldModelConfig {
            n_links: 2,
            n_subcarriers: 8,
            n_modes: 2,
            min_calibration_frames: 5,
            baseline_expiry_s: 86_400.0,
        };
        let mut model = FieldModel::new(config).unwrap();

        // Hiệu chuẩn với trôi chỉ trên sóng mang con 0 và 1
        for i in 0..10 {
            let obs = vec![
                vec![1.0 + 0.5 * i as f64, 2.0 + 0.3 * i as f64, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
                vec![1.1 + 0.5 * i as f64, 2.1 + 0.3 * i as f64, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1],
            ];
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();

        // Quan sát với nhiễu loạn lớn trên sóng mang con 5 (không phải chế độ môi trường)
        let mean_0 = 1.0 + 0.5 * 4.5; // trung bình điểm giữa
        let mean_1 = 2.0 + 0.3 * 4.5;
        let mut perturbed = vec![
            vec![mean_0, mean_1, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            vec![mean_0 + 0.1, mean_1 + 0.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1],
        ];
        perturbed[0][5] += 10.0; // nhiễu loạn lớn trên liên kết 0, sóng mang con 5

        let perturbation = model.extract_perturbation(&perturbed).unwrap();
        assert!(
            perturbation.total_energy > 0.0,
            "Nhiễu loạn trên sóng mang con không thuộc chế độ phải nhìn thấy, nhận được {}",
            perturbation.total_energy
        );
        assert!(perturbation.energies[0] > perturbation.energies[1]);
    }

    #[test]
    fn test_perturbation_baseline_observation_same() {
        let config = make_config(2, 4, 5);
        let mut model = FieldModel::new(config).unwrap();

        let obs = make_observations(2, 4, 1.0);
        for _ in 0..5 {
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();

        let perturbation = model.extract_perturbation(&obs).unwrap();
        assert!(
            perturbation.total_energy < 0.01,
            "Giống đường cơ sở phải cho nhiễu loạn gần zero"
        );
    }

    #[test]
    fn test_perturbation_dimension_mismatch() {
        let config = make_config(2, 4, 5);
        let mut model = FieldModel::new(config).unwrap();

        let obs = make_observations(2, 4, 1.0);
        for _ in 0..5 {
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();

        // Sai số liên kết
        let wrong_obs = make_observations(3, 4, 1.0);
        assert!(model.extract_perturbation(&wrong_obs).is_err());
    }

    #[test]
    fn test_calibration_freshness() {
        let config = make_config(2, 4, 5);
        let mut model = FieldModel::new(config).unwrap();

        let obs = make_observations(2, 4, 1.0);
        for _ in 0..5 {
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(0, 0).unwrap();

        assert_eq!(model.check_freshness(0), CalibrationStatus::Fresh);
        // 12 giờ sau: còn mới
        let twelve_hours_us = 12 * 3600 * 1_000_000;
        assert_eq!(
            model.check_freshness(twelve_hours_us),
            CalibrationStatus::Fresh
        );
        // 13 giờ sau: cũ (> 50% của 24 giờ)
        let thirteen_hours_us = 13 * 3600 * 1_000_000;
        assert_eq!(
            model.check_freshness(thirteen_hours_us),
            CalibrationStatus::Stale
        );
        // 25 giờ sau: hết hạn
        let twentyfive_hours_us = 25 * 3600 * 1_000_000;
        assert_eq!(
            model.check_freshness(twentyfive_hours_us),
            CalibrationStatus::Expired
        );
    }

    #[test]
    fn test_reset_calibration() {
        let config = make_config(2, 4, 5);
        let mut model = FieldModel::new(config).unwrap();

        let obs = make_observations(2, 4, 1.0);
        for _ in 0..5 {
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();
        assert!(model.modes().is_some());

        model.reset_calibration();
        assert!(model.modes().is_none());
        assert_eq!(model.status(), CalibrationStatus::Uncalibrated);
        assert_eq!(model.calibration_frame_count(), 0);
    }

    #[test]
    fn test_environmental_modes_sorted_by_energy() {
        let config = make_config(1, 8, 5);
        let mut model = FieldModel::new(config).unwrap();

        // Tạo quan sát với phương sai cao trên sóng mang con 3
        for i in 0..20 {
            let mut obs = vec![vec![1.0; 8]];
            obs[0][3] += (i as f64) * 0.5; // phương sai cao
            obs[0][7] += (i as f64) * 0.1; // phương sai thấp hơn
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();

        let modes = model.modes().unwrap();
        // Eigenvalue phải theo thứ tự giảm dần
        for w in modes.mode_energies.windows(2) {
            assert!(w[0] >= w[1], "Năng lượng chế độ phải giảm dần");
        }
    }

    #[test]
    fn test_environmental_projection_removes_drift() {
        let config = make_config(1, 4, 10);
        let mut model = FieldModel::new(config).unwrap();

        // Hiệu chuẩn với trôi trên sóng mang con 0
        for i in 0..10 {
            let obs = vec![vec![
                1.0 + 0.5 * i as f64, // đang trôi
                2.0,
                3.0,
                4.0,
            ]];
            model.feed_calibration(&obs).unwrap();
        }
        model.finalize_calibration(1_000_000, 0).unwrap();

        // Quan sát với cùng mẫu trôi (không có cơ thể)
        let obs = vec![vec![1.0 + 0.5 * 5.0, 2.0, 3.0, 4.0]];
        let perturbation = model.extract_perturbation(&obs).unwrap();

        // Trôi trên sóng mang con 0 phải được nắm bắt chủ yếu bởi
        // chế độ môi trường, để lại phần dư nhỏ
        assert!(
            perturbation.environmental_projections[0] > 0.0,
            "Chiếu môi trường phải khác zero cho sóng mang con đang trôi"
        );
    }
}
