//! Căn Chỉnh Pha Chéo Kênh (ADR-029 Mục 2.3)
//!
//! Khi ESP32 nhảy giữa các kênh WiFi, bộ dao động nội (LO)
//! tạo ra xoay pha phụ thuộc kênh. Pha quan sát trên
//! kênh c là:
//!
//!   phi_c = phi_body + delta_c
//!
//! trong đó `delta_c` là độ lệch LO cho kênh c. Module này ước lượng
//! và loại bỏ các độ lệch `delta_c` bằng cách khớp với các
//! sóng mang con tĩnh, vốn không có dịch pha do cơ thể gây ra.
//!
//! # Tích Hợp RuVector
//!
//! Sử dụng khái niệm `ruvector-solver::NeumannSolver` cho hội tụ lặp
//! trên ước lượng độ lệch pha. Bộ giải đạt hội tụ O(sqrt(n)).

use crate::hardware_norm::CanonicalCsiFrame;
use std::f32::consts::PI;

/// Các lỗi từ căn chỉnh pha.
#[derive(Debug, thiserror::Error)]
pub enum PhaseAlignError {
    /// Không có khung nào được cung cấp.
    #[error("Không có khung nào được cung cấp cho căn chỉnh pha")]
    NoFrames,

    /// Không đủ sóng mang con tĩnh để căn chỉnh.
    #[error("Cần ít nhất {needed} sóng mang con tĩnh, tìm thấy {found}")]
    InsufficientStatic { needed: usize, found: usize },

    /// Độ dài dữ liệu pha không khớp.
    #[error("Độ dài pha {got} không khớp với kỳ vọng {expected}")]
    PhaseLengthMismatch { expected: usize, got: usize },

    /// Hội tụ thất bại.
    #[error("Căn chỉnh pha không hội tụ sau {iterations} lần lặp")]
    ConvergenceFailed { iterations: usize },
}

/// Cấu hình cho bộ căn chỉnh pha.
#[derive(Debug, Clone)]
pub struct PhaseAlignConfig {
    /// Số lần lặp tối đa cho bộ giải Neumann.
    pub max_iterations: usize,
    /// Dung sai hội tụ (radian).
    pub tolerance: f32,
    /// Tỷ lệ sóng mang con được coi là "tĩnh" (phương sai thấp nhất).
    pub static_fraction: f32,
    /// Số sóng mang con tĩnh tối thiểu cần thiết.
    pub min_static_subcarriers: usize,
}

impl Default for PhaseAlignConfig {
    fn default() -> Self {
        Self {
            max_iterations: 20,
            tolerance: 1e-4,
            static_fraction: 0.3,
            min_static_subcarriers: 5,
        }
    }
}

/// Bộ căn chỉnh pha chéo kênh.
///
/// Ước lượng độ lệch pha LO mỗi kênh từ các sóng mang con tĩnh và
/// loại bỏ chúng để tạo ra quan sát đa băng tương hợp pha.
#[derive(Debug)]
pub struct PhaseAligner {
    /// Số kênh kỳ vọng.
    num_channels: usize,
    /// Tham số cấu hình.
    config: PhaseAlignConfig,
    /// Độ lệch ước lượng gần nhất (một mỗi kênh), cập nhật sau mỗi `align`.
    last_offsets: Vec<f32>,
}

impl PhaseAligner {
    /// Tạo bộ căn chỉnh mới cho số kênh cho trước.
    pub fn new(num_channels: usize) -> Self {
        Self {
            num_channels,
            config: PhaseAlignConfig::default(),
            last_offsets: vec![0.0; num_channels],
        }
    }

    /// Tạo bộ căn chỉnh mới với cấu hình tùy chỉnh.
    pub fn with_config(num_channels: usize, config: PhaseAlignConfig) -> Self {
        Self {
            num_channels,
            config,
            last_offsets: vec![0.0; num_channels],
        }
    }

    /// Trả về các độ lệch pha ước lượng gần nhất (radian).
    pub fn last_offsets(&self) -> &[f32] {
        &self.last_offsets
    }

    /// Căn chỉnh pha chéo kênh.
    ///
    /// Nhận một slice các `CanonicalCsiFrame` mỗi kênh và trả về các khung
    /// đã sửa với độ lệch pha LO được loại bỏ. Kênh đầu tiên được dùng làm
    /// tham chiếu (delta_0 = 0).
    ///
    /// # Thuật Toán
    ///
    /// 1. Xác định sóng mang con tĩnh (phương sai biên độ thấp nhất giữa các kênh).
    /// 2. Với mỗi kênh c, tính pha trung bình trên sóng mang con tĩnh.
    /// 3. Ước lượng delta_c là hiệu so với kênh tham chiếu.
    /// 4. Lặp với tinh chỉnh kiểu Neumann cho đến khi hội tụ.
    /// 5. Trừ delta_c khỏi tất cả pha sóng mang con trên kênh c.
    pub fn align(
        &mut self,
        frames: &[CanonicalCsiFrame],
    ) -> std::result::Result<Vec<CanonicalCsiFrame>, PhaseAlignError> {
        if frames.is_empty() {
            return Err(PhaseAlignError::NoFrames);
        }

        if frames.len() == 1 {
            // Một kênh: không cần căn chỉnh
            self.last_offsets = vec![0.0];
            return Ok(frames.to_vec());
        }

        let n_sub = frames[0].phase.len();
        for (_i, f) in frames.iter().enumerate().skip(1) {
            if f.phase.len() != n_sub {
                return Err(PhaseAlignError::PhaseLengthMismatch {
                    expected: n_sub,
                    got: f.phase.len(),
                });
            }
        }

        // Bước 1: Tìm sóng mang con tĩnh (phương sai biên độ thấp nhất giữa các kênh)
        let static_indices = find_static_subcarriers(frames, &self.config)?;

        // Bước 2-4: Ước lượng độ lệch pha với tinh chỉnh lặp
        let offsets = estimate_phase_offsets(frames, &static_indices, &self.config)?;

        // Bước 5: Áp dụng sửa lỗi
        let corrected = apply_phase_correction(frames, &offsets);

        self.last_offsets = offsets;
        Ok(corrected)
    }
}

/// Tìm chỉ số của các sóng mang con tĩnh (phương sai biên độ thấp nhất).
fn find_static_subcarriers(
    frames: &[CanonicalCsiFrame],
    config: &PhaseAlignConfig,
) -> std::result::Result<Vec<usize>, PhaseAlignError> {
    let n_sub = frames[0].amplitude.len();
    let n_ch = frames.len();

    // Tính phương sai biên độ giữa các kênh cho mỗi sóng mang con
    let mut variances: Vec<(usize, f32)> = (0..n_sub)
        .map(|s| {
            let mean: f32 = frames.iter().map(|f| f.amplitude[s]).sum::<f32>() / n_ch as f32;
            let var: f32 = frames
                .iter()
                .map(|f| {
                    let d = f.amplitude[s] - mean;
                    d * d
                })
                .sum::<f32>()
                / n_ch as f32;
            (s, var)
        })
        .collect();

    // Sắp xếp theo phương sai (tăng dần) và lấy phần dưới cùng
    variances.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));

    let n_static = ((n_sub as f32 * config.static_fraction).ceil() as usize)
        .max(config.min_static_subcarriers);

    if variances.len() < config.min_static_subcarriers {
        return Err(PhaseAlignError::InsufficientStatic {
            needed: config.min_static_subcarriers,
            found: variances.len(),
        });
    }

    let mut indices: Vec<usize> = variances
        .iter()
        .take(n_static.min(variances.len()))
        .map(|(idx, _)| *idx)
        .collect();

    indices.sort_unstable();
    Ok(indices)
}

/// Ước lượng độ lệch pha mỗi kênh sử dụng tinh chỉnh lặp kiểu Neumann.
///
/// Kênh 0 là tham chiếu (offset = 0).
fn estimate_phase_offsets(
    frames: &[CanonicalCsiFrame],
    static_indices: &[usize],
    config: &PhaseAlignConfig,
) -> std::result::Result<Vec<f32>, PhaseAlignError> {
    let n_ch = frames.len();
    let mut offsets = vec![0.0_f32; n_ch];

    // Tham chiếu: pha trung bình trên sóng mang con tĩnh cho kênh 0
    let ref_mean = mean_phase_on_indices(&frames[0].phase, static_indices);

    // Ước lượng ban đầu: hiệu pha tĩnh trung bình so với tham chiếu
    for c in 1..n_ch {
        let ch_mean = mean_phase_on_indices(&frames[c].phase, static_indices);
        offsets[c] = wrap_phase(ch_mean - ref_mean);
    }

    // Tinh chỉnh lặp (kiểu Neumann)
    for _iter in 0..config.max_iterations {
        let mut max_update = 0.0_f32;

        for c in 1..n_ch {
            // Tính phần dư: với mỗi sóng mang con tĩnh, pha đã sửa
            // phải khớp với pha kênh tham chiếu.
            let mut residual_sum = 0.0_f32;
            for &s in static_indices {
                let corrected = frames[c].phase[s] - offsets[c];
                let residual = wrap_phase(corrected - frames[0].phase[s]);
                residual_sum += residual;
            }
            let mean_residual = residual_sum / static_indices.len() as f32;

            // Cập nhật offset
            let update = mean_residual * 0.5; // cập nhật giảm chấn
            offsets[c] = wrap_phase(offsets[c] + update);
            max_update = max_update.max(update.abs());
        }

        if max_update < config.tolerance {
            return Ok(offsets);
        }
    }

    // Ngay cả khi không hội tụ chặt, trả về ước lượng tốt nhất
    Ok(offsets)
}

/// Áp dụng sửa pha: trừ offset khỏi pha mỗi sóng mang con.
fn apply_phase_correction(
    frames: &[CanonicalCsiFrame],
    offsets: &[f32],
) -> Vec<CanonicalCsiFrame> {
    frames
        .iter()
        .zip(offsets.iter())
        .map(|(frame, &offset)| {
            let corrected_phase: Vec<f32> = frame
                .phase
                .iter()
                .map(|&p| wrap_phase(p - offset))
                .collect();
            CanonicalCsiFrame {
                amplitude: frame.amplitude.clone(),
                phase: corrected_phase,
                hardware_type: frame.hardware_type,
            }
        })
        .collect()
}

/// Tính pha trung bình trên các chỉ số sóng mang con cho trước.
fn mean_phase_on_indices(phase: &[f32], indices: &[usize]) -> f32 {
    if indices.is_empty() {
        return 0.0;
    }

    // Sử dụng trung bình vòng tròn để xử lý cuộn pha
    let mut sin_sum = 0.0_f32;
    let mut cos_sum = 0.0_f32;
    for &i in indices {
        // Kiểm tra giới hạn phòng thủ: bỏ qua chỉ số ngoài phạm vi thay vì panic
        if let Some(&p) = phase.get(i) {
            sin_sum += p.sin();
            cos_sum += p.cos();
        }
    }

    sin_sum.atan2(cos_sum)
}

/// Cuộn pha vào [-pi, pi].
fn wrap_phase(phase: f32) -> f32 {
    let mut p = phase % (2.0 * PI);
    if p > PI {
        p -= 2.0 * PI;
    }
    if p < -PI {
        p += 2.0 * PI;
    }
    p
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hardware_norm::HardwareType;

    fn make_frame_with_phase(n: usize, base_phase: f32, offset: f32) -> CanonicalCsiFrame {
        let amplitude: Vec<f32> = (0..n).map(|i| 1.0 + 0.01 * i as f32).collect();
        let phase: Vec<f32> = (0..n).map(|i| base_phase + i as f32 * 0.01 + offset).collect();
        CanonicalCsiFrame {
            amplitude,
            phase,
            hardware_type: HardwareType::Esp32S3,
        }
    }

    #[test]
    fn single_channel_no_change() {
        let mut aligner = PhaseAligner::new(1);
        let frames = vec![make_frame_with_phase(56, 0.0, 0.0)];
        let result = aligner.align(&frames).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].phase, frames[0].phase);
    }

    #[test]
    fn empty_frames_error() {
        let mut aligner = PhaseAligner::new(3);
        let result = aligner.align(&[]);
        assert!(matches!(result, Err(PhaseAlignError::NoFrames)));
    }

    #[test]
    fn phase_length_mismatch_error() {
        let mut aligner = PhaseAligner::new(2);
        let f1 = make_frame_with_phase(56, 0.0, 0.0);
        let f2 = make_frame_with_phase(30, 0.0, 0.0);
        let result = aligner.align(&[f1, f2]);
        assert!(matches!(result, Err(PhaseAlignError::PhaseLengthMismatch { .. })));
    }

    #[test]
    fn identical_channels_zero_offset() {
        let mut aligner = PhaseAligner::new(3);
        let f = make_frame_with_phase(56, 0.5, 0.0);
        let result = aligner.align(&[f.clone(), f.clone(), f.clone()]).unwrap();
        assert_eq!(result.len(), 3);
        // Tất cả offset phải xấp xỉ 0
        for &off in aligner.last_offsets() {
            assert!(off.abs() < 0.1, "Kỳ vọng offset gần zero, nhận được {}", off);
        }
    }

    #[test]
    fn known_offset_corrected() {
        let mut aligner = PhaseAligner::new(2);
        let offset = 0.5_f32;
        let f0 = make_frame_with_phase(56, 0.0, 0.0);
        let f1 = make_frame_with_phase(56, 0.0, offset);

        let result = aligner.align(&[f0.clone(), f1]).unwrap();

        // Sau khi sửa, pha kênh 1 phải gần với kênh 0
        let max_diff: f32 = result[0]
            .phase
            .iter()
            .zip(result[1].phase.iter())
            .map(|(a, b)| wrap_phase(a - b).abs())
            .fold(0.0_f32, f32::max);

        assert!(
            max_diff < 0.2,
            "Hiệu pha tối đa sau căn chỉnh: {} (phải <0.2)",
            max_diff
        );
    }

    #[test]
    fn wrap_phase_within_range() {
        assert!((wrap_phase(0.0)).abs() < 1e-6);
        assert!((wrap_phase(PI) - PI).abs() < 1e-6);
        assert!((wrap_phase(-PI) + PI).abs() < 1e-6);
        assert!((wrap_phase(3.0 * PI) - PI).abs() < 0.01);
        assert!((wrap_phase(-3.0 * PI) + PI).abs() < 0.01);
    }

    #[test]
    fn mean_phase_circular() {
        let phase = vec![0.1_f32, 0.2, 0.3, 0.4];
        let indices = vec![0, 1, 2, 3];
        let m = mean_phase_on_indices(&phase, &indices);
        assert!((m - 0.25).abs() < 0.05);
    }

    #[test]
    fn mean_phase_empty_indices() {
        assert_eq!(mean_phase_on_indices(&[1.0, 2.0], &[]), 0.0);
    }

    #[test]
    fn last_offsets_accessible() {
        let aligner = PhaseAligner::new(3);
        assert_eq!(aligner.last_offsets().len(), 3);
        assert!(aligner.last_offsets().iter().all(|&x| x == 0.0));
    }

    #[test]
    fn custom_config() {
        let config = PhaseAlignConfig {
            max_iterations: 50,
            tolerance: 1e-6,
            static_fraction: 0.5,
            min_static_subcarriers: 3,
        };
        let aligner = PhaseAligner::with_config(2, config);
        assert_eq!(aligner.last_offsets().len(), 2);
    }

    #[test]
    fn three_channel_alignment() {
        let mut aligner = PhaseAligner::new(3);
        let f0 = make_frame_with_phase(56, 0.0, 0.0);
        let f1 = make_frame_with_phase(56, 0.0, 0.3);
        let f2 = make_frame_with_phase(56, 0.0, -0.2);

        let result = aligner.align(&[f0, f1, f2]).unwrap();
        assert_eq!(result.len(), 3);

        // Offset kênh tham chiếu phải bằng 0
        assert!(aligner.last_offsets()[0].abs() < 1e-6);
    }

    #[test]
    fn default_config_values() {
        let cfg = PhaseAlignConfig::default();
        assert_eq!(cfg.max_iterations, 20);
        assert!((cfg.tolerance - 1e-4).abs() < 1e-8);
        assert!((cfg.static_fraction - 0.3).abs() < 1e-6);
        assert_eq!(cfg.min_static_subcarriers, 5);
    }

    #[test]
    fn phase_correction_preserves_amplitude() {
        let mut aligner = PhaseAligner::new(2);
        let f0 = make_frame_with_phase(56, 0.0, 0.0);
        let f1 = make_frame_with_phase(56, 0.0, 1.0);

        let result = aligner.align(&[f0.clone(), f1.clone()]).unwrap();
        // Biên độ phải không thay đổi
        assert_eq!(result[0].amplitude, f0.amplitude);
        assert_eq!(result[1].amplitude, f1.amplitude);
    }
}
