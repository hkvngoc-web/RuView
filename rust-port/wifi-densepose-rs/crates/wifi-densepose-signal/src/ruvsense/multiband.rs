//! Kết Hợp Khung CSI Đa Băng (ADR-029 Mục 2.3)
//!
//! Tổng hợp các khung CSI theo kênh từ nhảy kênh thành ảnh chụp
//! ảo băng rộng. Một ESP32-S3 luân chuyển qua kênh 1/6/11 với thời gian
//! dừng 50 ms mỗi kênh cho ra 3 hàng CSI chuẩn-56 mỗi chu kỳ cảm biến.
//! Module này kết hợp chúng thành một `MultiBandCsiFrame` duy nhất được ghi chú
//! với tần số trung tâm và tương hợp chéo kênh.
//!
//! # Tích Hợp RuVector
//!
//! - `ruvector-attention` cho trọng số đặc trưng chéo kênh (tương lai)

use crate::hardware_norm::CanonicalCsiFrame;

/// Các lỗi từ kết hợp khung đa băng.
#[derive(Debug, thiserror::Error)]
pub enum MultiBandError {
    /// Không có khung kênh nào được cung cấp.
    #[error("Không có khung kênh nào được cung cấp cho kết hợp đa băng")]
    NoFrames,

    /// Số sóng mang con không khớp giữa các kênh.
    #[error("Số sóng mang con không khớp: kênh {channel_idx} có {got}, kỳ vọng {expected}")]
    SubcarrierMismatch {
        channel_idx: usize,
        expected: usize,
        got: usize,
    },

    /// Độ dài danh sách tần số không khớp với số khung.
    #[error("Số tần số ({freq_count}) không khớp với số khung ({frame_count})")]
    FrequencyCountMismatch { freq_count: usize, frame_count: usize },

    /// Trùng tần số trong danh sách kênh.
    #[error("Trùng tần số {freq_mhz} MHz tại chỉ số {idx}")]
    DuplicateFrequency { freq_mhz: u32, idx: usize },
}

/// CSI đa băng đã kết hợp từ một node tại một khe thời gian.
///
/// Chứa một hàng CSI chuẩn-56 mỗi kênh, sắp xếp theo tần số trung tâm.
/// Trường `coherence` đo mức độ đồng thuận giữa các kênh (0.0-1.0).
#[derive(Debug, Clone)]
pub struct MultiBandCsiFrame {
    /// Định danh node gốc (0-255).
    pub node_id: u8,
    /// Dấu thời gian chu kỳ cảm biến tính bằng micro giây.
    pub timestamp_us: u64,
    /// Một khung CSI chuẩn-56 mỗi kênh, sắp xếp theo tần số trung tâm.
    pub channel_frames: Vec<CanonicalCsiFrame>,
    /// Tần số trung tâm (MHz) cho mỗi hàng kênh.
    pub frequencies_mhz: Vec<u32>,
    /// Điểm tương hợp chéo kênh (0.0-1.0).
    pub coherence: f32,
}

/// Cấu hình cho quá trình kết hợp đa băng.
#[derive(Debug, Clone)]
pub struct MultiBandConfig {
    /// Cửa sổ thời gian tính bằng micro giây trong đó các khung được coi là
    /// thuộc cùng chu kỳ cảm biến.
    pub window_us: u64,
    /// Số kênh kỳ vọng mỗi chu kỳ.
    pub expected_channels: usize,
    /// Tương hợp tối thiểu để chấp nhận khung đã kết hợp.
    pub min_coherence: f32,
}

impl Default for MultiBandConfig {
    fn default() -> Self {
        Self {
            window_us: 200_000, // cửa sổ mặc định 200 ms
            expected_channels: 3,
            min_coherence: 0.3,
        }
    }
}

/// Bộ xây dựng để tạo `MultiBandCsiFrame` từ các quan sát theo kênh.
#[derive(Debug)]
pub struct MultiBandBuilder {
    node_id: u8,
    timestamp_us: u64,
    frames: Vec<CanonicalCsiFrame>,
    frequencies: Vec<u32>,
}

impl MultiBandBuilder {
    /// Tạo bộ xây dựng mới cho node và dấu thời gian cho trước.
    pub fn new(node_id: u8, timestamp_us: u64) -> Self {
        Self {
            node_id,
            timestamp_us,
            frames: Vec::new(),
            frequencies: Vec::new(),
        }
    }

    /// Thêm quan sát kênh tại tần số trung tâm cho trước.
    pub fn add_channel(
        mut self,
        frame: CanonicalCsiFrame,
        freq_mhz: u32,
    ) -> Self {
        self.frames.push(frame);
        self.frequencies.push(freq_mhz);
        self
    }

    /// Xây dựng khung đa băng đã kết hợp.
    ///
    /// Xác thực đầu vào, sắp xếp theo tần số, và tính tương hợp chéo kênh.
    pub fn build(mut self) -> std::result::Result<MultiBandCsiFrame, MultiBandError> {
        if self.frames.is_empty() {
            return Err(MultiBandError::NoFrames);
        }

        if self.frequencies.len() != self.frames.len() {
            return Err(MultiBandError::FrequencyCountMismatch {
                freq_count: self.frequencies.len(),
                frame_count: self.frames.len(),
            });
        }

        // Kiểm tra tần số trùng lặp
        for i in 0..self.frequencies.len() {
            for j in (i + 1)..self.frequencies.len() {
                if self.frequencies[i] == self.frequencies[j] {
                    return Err(MultiBandError::DuplicateFrequency {
                        freq_mhz: self.frequencies[i],
                        idx: j,
                    });
                }
            }
        }

        // Xác thực số sóng mang con nhất quán
        let expected_len = self.frames[0].amplitude.len();
        for (i, frame) in self.frames.iter().enumerate().skip(1) {
            if frame.amplitude.len() != expected_len {
                return Err(MultiBandError::SubcarrierMismatch {
                    channel_idx: i,
                    expected: expected_len,
                    got: frame.amplitude.len(),
                });
            }
        }

        // Sắp xếp các khung theo tần số
        let mut indices: Vec<usize> = (0..self.frames.len()).collect();
        indices.sort_by_key(|&i| self.frequencies[i]);

        let sorted_frames: Vec<CanonicalCsiFrame> =
            indices.iter().map(|&i| self.frames[i].clone()).collect();
        let sorted_freqs: Vec<u32> =
            indices.iter().map(|&i| self.frequencies[i]).collect();

        self.frames = sorted_frames;
        self.frequencies = sorted_freqs;

        // Tính tương hợp chéo kênh
        let coherence = compute_cross_channel_coherence(&self.frames);

        Ok(MultiBandCsiFrame {
            node_id: self.node_id,
            timestamp_us: self.timestamp_us,
            channel_frames: self.frames,
            frequencies_mhz: self.frequencies,
            coherence,
        })
    }
}

/// Tính tương hợp chéo kênh bằng tương quan Pearson trung bình theo cặp
/// của các vector biên độ giữa tất cả các cặp kênh.
///
/// Trả về giá trị trong [0.0, 1.0] trong đó 1.0 nghĩa là tương quan hoàn hảo.
fn compute_cross_channel_coherence(frames: &[CanonicalCsiFrame]) -> f32 {
    if frames.len() < 2 {
        return 1.0; // một kênh tương hợp tầm thường
    }

    let mut total_corr = 0.0_f64;
    let mut pair_count = 0u32;

    for i in 0..frames.len() {
        for j in (i + 1)..frames.len() {
            let corr = pearson_correlation_f32(
                &frames[i].amplitude,
                &frames[j].amplitude,
            );
            total_corr += corr as f64;
            pair_count += 1;
        }
    }

    if pair_count == 0 {
        return 1.0;
    }

    // Ánh xạ tương quan [-1, 1] sang tương hợp [0, 1]
    let mean_corr = total_corr / pair_count as f64;
    ((mean_corr + 1.0) / 2.0).clamp(0.0, 1.0) as f32
}

/// Hệ số tương quan Pearson giữa hai slice f32.
fn pearson_correlation_f32(a: &[f32], b: &[f32]) -> f32 {
    let n = a.len().min(b.len());
    if n == 0 {
        return 0.0;
    }

    let n_f = n as f32;
    let mean_a: f32 = a[..n].iter().sum::<f32>() / n_f;
    let mean_b: f32 = b[..n].iter().sum::<f32>() / n_f;

    let mut cov = 0.0_f32;
    let mut var_a = 0.0_f32;
    let mut var_b = 0.0_f32;

    for i in 0..n {
        let da = a[i] - mean_a;
        let db = b[i] - mean_b;
        cov += da * db;
        var_a += da * da;
        var_b += db * db;
    }

    let denom = (var_a * var_b).sqrt();
    if denom < 1e-12 {
        return 0.0;
    }

    (cov / denom).clamp(-1.0, 1.0)
}

/// Nối các vector biên độ từ tất cả kênh thành một vector biên độ
/// băng rộng duy nhất. Hữu ích cho các mô hình phía sau kỳ vọng
/// vector đặc trưng phẳng.
pub fn concatenate_amplitudes(frame: &MultiBandCsiFrame) -> Vec<f32> {
    let total_len: usize = frame.channel_frames.iter().map(|f| f.amplitude.len()).sum();
    let mut out = Vec::with_capacity(total_len);
    for cf in &frame.channel_frames {
        out.extend_from_slice(&cf.amplitude);
    }
    out
}

/// Tính biên độ trung bình giữa tất cả kênh, tạo ra một vector
/// có độ dài chuẩn lấy trung bình các quan sát đa băng.
pub fn mean_amplitude(frame: &MultiBandCsiFrame) -> Vec<f32> {
    if frame.channel_frames.is_empty() {
        return Vec::new();
    }

    let n_sub = frame.channel_frames[0].amplitude.len();
    let n_ch = frame.channel_frames.len() as f32;
    let mut mean = vec![0.0_f32; n_sub];

    for cf in &frame.channel_frames {
        for (i, &val) in cf.amplitude.iter().enumerate() {
            if i < n_sub {
                mean[i] += val;
            }
        }
    }

    for v in &mut mean {
        *v /= n_ch;
    }

    mean
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hardware_norm::HardwareType;

    fn make_canonical(amplitude: Vec<f32>, phase: Vec<f32>) -> CanonicalCsiFrame {
        CanonicalCsiFrame {
            amplitude,
            phase,
            hardware_type: HardwareType::Esp32S3,
        }
    }

    fn make_frame(n_sub: usize, scale: f32) -> CanonicalCsiFrame {
        let amp: Vec<f32> = (0..n_sub).map(|i| scale * (i as f32 * 0.1).sin()).collect();
        let phase: Vec<f32> = (0..n_sub).map(|i| (i as f32 * 0.05).cos()).collect();
        make_canonical(amp, phase)
    }

    #[test]
    fn build_single_channel() {
        let frame = MultiBandBuilder::new(0, 1000)
            .add_channel(make_frame(56, 1.0), 2412)
            .build()
            .unwrap();
        assert_eq!(frame.node_id, 0);
        assert_eq!(frame.timestamp_us, 1000);
        assert_eq!(frame.channel_frames.len(), 1);
        assert_eq!(frame.frequencies_mhz, vec![2412]);
        assert!((frame.coherence - 1.0).abs() < f32::EPSILON);
    }

    #[test]
    fn build_three_channels_sorted_by_freq() {
        let frame = MultiBandBuilder::new(1, 2000)
            .add_channel(make_frame(56, 1.0), 2462) // kênh 11
            .add_channel(make_frame(56, 1.0), 2412) // kênh 1
            .add_channel(make_frame(56, 1.0), 2437) // kênh 6
            .build()
            .unwrap();
        assert_eq!(frame.frequencies_mhz, vec![2412, 2437, 2462]);
        assert_eq!(frame.channel_frames.len(), 3);
    }

    #[test]
    fn empty_frames_error() {
        let result = MultiBandBuilder::new(0, 0).build();
        assert!(matches!(result, Err(MultiBandError::NoFrames)));
    }

    #[test]
    fn subcarrier_mismatch_error() {
        let result = MultiBandBuilder::new(0, 0)
            .add_channel(make_frame(56, 1.0), 2412)
            .add_channel(make_frame(30, 1.0), 2437)
            .build();
        assert!(matches!(result, Err(MultiBandError::SubcarrierMismatch { .. })));
    }

    #[test]
    fn duplicate_frequency_error() {
        let result = MultiBandBuilder::new(0, 0)
            .add_channel(make_frame(56, 1.0), 2412)
            .add_channel(make_frame(56, 1.0), 2412)
            .build();
        assert!(matches!(result, Err(MultiBandError::DuplicateFrequency { .. })));
    }

    #[test]
    fn coherence_identical_channels() {
        let f = make_frame(56, 1.0);
        let frame = MultiBandBuilder::new(0, 0)
            .add_channel(f.clone(), 2412)
            .add_channel(f.clone(), 2437)
            .build()
            .unwrap();
        // Các kênh giống hệt phải có tương hợp == 1.0
        assert!((frame.coherence - 1.0).abs() < 0.01);
    }

    #[test]
    fn coherence_orthogonal_channels() {
        let n = 56;
        let amp_a: Vec<f32> = (0..n).map(|i| (i as f32 * 0.3).sin()).collect();
        let amp_b: Vec<f32> = (0..n).map(|i| (i as f32 * 0.3).cos()).collect();
        let ph = vec![0.0_f32; n];

        let frame = MultiBandBuilder::new(0, 0)
            .add_channel(make_canonical(amp_a, ph.clone()), 2412)
            .add_channel(make_canonical(amp_b, ph), 2437)
            .build()
            .unwrap();
        // Tín hiệu trực giao phải có tương hợp thấp hơn
        assert!(frame.coherence < 0.9);
    }

    #[test]
    fn concatenate_amplitudes_correct_length() {
        let frame = MultiBandBuilder::new(0, 0)
            .add_channel(make_frame(56, 1.0), 2412)
            .add_channel(make_frame(56, 2.0), 2437)
            .add_channel(make_frame(56, 3.0), 2462)
            .build()
            .unwrap();
        let concat = concatenate_amplitudes(&frame);
        assert_eq!(concat.len(), 56 * 3);
    }

    #[test]
    fn mean_amplitude_correct() {
        let n = 4;
        let f1 = make_canonical(vec![1.0, 2.0, 3.0, 4.0], vec![0.0; n]);
        let f2 = make_canonical(vec![3.0, 4.0, 5.0, 6.0], vec![0.0; n]);
        let frame = MultiBandBuilder::new(0, 0)
            .add_channel(f1, 2412)
            .add_channel(f2, 2437)
            .build()
            .unwrap();
        let m = mean_amplitude(&frame);
        assert_eq!(m.len(), 4);
        assert!((m[0] - 2.0).abs() < 1e-6);
        assert!((m[1] - 3.0).abs() < 1e-6);
        assert!((m[2] - 4.0).abs() < 1e-6);
        assert!((m[3] - 5.0).abs() < 1e-6);
    }

    #[test]
    fn mean_amplitude_empty() {
        let frame = MultiBandCsiFrame {
            node_id: 0,
            timestamp_us: 0,
            channel_frames: vec![],
            frequencies_mhz: vec![],
            coherence: 1.0,
        };
        assert!(mean_amplitude(&frame).is_empty());
    }

    #[test]
    fn pearson_correlation_perfect() {
        let a = vec![1.0_f32, 2.0, 3.0, 4.0, 5.0];
        let b = vec![2.0_f32, 4.0, 6.0, 8.0, 10.0];
        let r = pearson_correlation_f32(&a, &b);
        assert!((r - 1.0).abs() < 1e-5);
    }

    #[test]
    fn pearson_correlation_negative() {
        let a = vec![1.0_f32, 2.0, 3.0, 4.0, 5.0];
        let b = vec![5.0_f32, 4.0, 3.0, 2.0, 1.0];
        let r = pearson_correlation_f32(&a, &b);
        assert!((r + 1.0).abs() < 1e-5);
    }

    #[test]
    fn pearson_correlation_empty() {
        assert_eq!(pearson_correlation_f32(&[], &[]), 0.0);
    }

    #[test]
    fn default_config() {
        let cfg = MultiBandConfig::default();
        assert_eq!(cfg.expected_channels, 3);
        assert_eq!(cfg.window_us, 200_000);
        assert!((cfg.min_coherence - 0.3).abs() < f32::EPSILON);
    }
}
