//! Chọn lọc sóng mang con nhạy
//!
//! Xếp hạng sóng mang con theo đáp ứng với chuyển động con người sử dụng tỷ lệ phương sai
//! (phương sai chuyển động / phương sai tĩnh) và chọn top-K nhạy nhất.
//! Điều này cải thiện SNR 6-10 dB so với sử dụng tất cả sóng mang con.
//!
//! # Tài liệu tham khảo
//! - WiDance (MobiCom 2017)
//! - WiGest: Using WiFi Gestures for Device-Free Sensing (SenSys 2015)

use ndarray::Array2;
use ruvector_mincut::MinCutBuilder;

/// Cấu hình cho chọn lọc sóng mang con.
#[derive(Debug, Clone)]
pub struct SubcarrierSelectionConfig {
    /// Số sóng mang con hàng đầu cần chọn
    pub top_k: usize,
    /// Tỷ lệ nhạy tối thiểu để bao gồm sóng mang con
    pub min_sensitivity: f64,
}

impl Default for SubcarrierSelectionConfig {
    fn default() -> Self {
        Self {
            top_k: 20,
            min_sensitivity: 1.5,
        }
    }
}

/// Kết quả chọn lọc sóng mang con.
#[derive(Debug, Clone)]
pub struct SubcarrierSelection {
    /// Các chỉ số sóng mang con đã chọn (sắp xếp theo độ nhạy, giảm dần)
    pub selected_indices: Vec<usize>,
    /// Điểm nhạy cho TẤT CẢ sóng mang con (tỷ lệ phương sai)
    pub sensitivity_scores: Vec<f64>,
    /// Ma trận dữ liệu đã lọc chỉ chứa cột sóng mang con đã chọn
    pub selected_data: Option<Array2<f64>>,
}

/// Chọn các sóng mang con nhạy chuyển động nhất sử dụng tỷ lệ phương sai.
///
/// `motion_data`: biên độ CSI (num_samples × num_subcarriers) trong khi chuyển động
/// `static_data`: biên độ CSI (num_samples × num_subcarriers) trong khi tĩnh
///
/// Độ nhạy = var(motion[k]) / (var(static[k]) + ε)
pub fn select_sensitive_subcarriers(
    motion_data: &Array2<f64>,
    static_data: &Array2<f64>,
    config: &SubcarrierSelectionConfig,
) -> Result<SubcarrierSelection, SelectionError> {
    let (_, n_sc_motion) = motion_data.dim();
    let (_, n_sc_static) = static_data.dim();

    if n_sc_motion != n_sc_static {
        return Err(SelectionError::SubcarrierCountMismatch {
            motion: n_sc_motion,
            statik: n_sc_static,
        });
    }
    if n_sc_motion == 0 {
        return Err(SelectionError::NoSubcarriers);
    }

    let n_sc = n_sc_motion;
    let mut scores = Vec::with_capacity(n_sc);

    for k in 0..n_sc {
        let motion_var = column_variance(motion_data, k);
        let static_var = column_variance(static_data, k);
        let sensitivity = motion_var / (static_var + 1e-12);
        scores.push(sensitivity);
    }

    // Xếp hạng theo độ nhạy (giảm dần)
    let mut ranked: Vec<(usize, f64)> = scores.iter().copied().enumerate().collect();
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Chọn top-K trên ngưỡng tối thiểu
    let selected: Vec<usize> = ranked
        .iter()
        .filter(|(_, score)| *score >= config.min_sensitivity)
        .take(config.top_k)
        .map(|(idx, _)| *idx)
        .collect();

    Ok(SubcarrierSelection {
        selected_indices: selected,
        sensitivity_scores: scores,
        selected_data: None,
    })
}

/// Chọn và trích xuất dữ liệu cho sóng mang con nhạy từ ma trận thời gian.
///
/// `data`: (num_samples × num_subcarriers) - ma trận CSI đầy đủ cần lọc
/// `selection`: kết quả chọn lọc sóng mang con đã tính trước
///
/// Trả về ma trận mới chỉ với các cột đã chọn.
pub fn extract_selected(
    data: &Array2<f64>,
    selection: &SubcarrierSelection,
) -> Result<Array2<f64>, SelectionError> {
    let (n_samples, n_sc) = data.dim();

    for &idx in &selection.selected_indices {
        if idx >= n_sc {
            return Err(SelectionError::IndexOutOfBounds { index: idx, max: n_sc });
        }
    }

    if selection.selected_indices.is_empty() {
        return Err(SelectionError::NoSubcarriersSelected);
    }

    let n_selected = selection.selected_indices.len();
    let mut result = Array2::zeros((n_samples, n_selected));

    for (col, &sc_idx) in selection.selected_indices.iter().enumerate() {
        for row in 0..n_samples {
            result[[row, col]] = data[[row, sc_idx]];
        }
    }

    Ok(result)
}

/// Chọn lọc sóng mang con trực tuyến chỉ sử dụng phương sai (không cần giai đoạn tĩnh riêng).
///
/// Xếp hạng theo phương sai tuyệt đối — sóng mang con phương sai cao mang
/// nhiều thông tin hơn về thay đổi môi trường.
pub fn select_by_variance(
    data: &Array2<f64>,
    config: &SubcarrierSelectionConfig,
) -> SubcarrierSelection {
    let (_, n_sc) = data.dim();
    let mut scores = Vec::with_capacity(n_sc);

    for k in 0..n_sc {
        scores.push(column_variance(data, k));
    }

    let mut ranked: Vec<(usize, f64)> = scores.iter().copied().enumerate().collect();
    ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    let selected: Vec<usize> = ranked
        .iter()
        .take(config.top_k)
        .map(|(idx, _)| *idx)
        .collect();

    SubcarrierSelection {
        selected_indices: selected,
        sensitivity_scores: scores,
        selected_data: None,
    }
}

/// Tính phương sai của một cột trong mảng 2D.
fn column_variance(data: &Array2<f64>, col: usize) -> f64 {
    let n = data.nrows() as f64;
    if n < 2.0 {
        return 0.0;
    }
    let col_data = data.column(col);
    let mean: f64 = col_data.sum() / n;
    col_data.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0)
}

/// Phân hoạch sóng mang con thành nhóm (nhạy, không nhạy) qua DynamicMinCut.
///
/// Xây dựng đồ thị tương đồng: sóng mang con là đỉnh, cạnh mã hóa
/// khoảng cách nghịch đảo tỷ lệ phương sai. Cắt tối thiểu phân tách sóng mang con
/// độ nhạy cao khỏi độ nhạy thấp trong thời gian O(n^1.5 log n) khấu hao.
///
/// # Tham số
/// * `sensitivity` - Điểm nhạy theo từng sóng mang con (variance_motion / variance_static)
///
/// # Trả về
/// (chỉ_số_nhạy, chỉ_số_không_nhạy) — chỉ số vào lát đầu vào
pub fn mincut_subcarrier_partition(sensitivity: &[f32]) -> (Vec<usize>, Vec<usize>) {
    let n = sensitivity.len();
    if n < 4 {
        // Quá nhỏ cho cắt có ý nghĩa — đặt tất cả vào nhóm nhạy
        return ((0..n).collect(), Vec::new());
    }

    // Xây dựng đồ thị tương đồng: trọng số cạnh = 1 / |sensitivity_i - sensitivity_j|
    // Chỉ bao gồm cạnh có trọng số > min_weight (cắt tỉa tương đồng rất yếu)
    let min_weight = 0.5_f64;
    let mut edges: Vec<(u64, u64, f64)> = Vec::new();
    for i in 0..n {
        for j in (i + 1)..n {
            let diff = (sensitivity[i] - sensitivity[j]).abs() as f64;
            let weight = if diff > 1e-9 { 1.0 / diff } else { 1e6_f64 };
            if weight > min_weight {
                edges.push((i as u64, j as u64, weight));
            }
        }
    }

    if edges.is_empty() {
        // Tất cả sóng mang con nhạy như nhau — chia theo trung vị
        let median_idx = n / 2;
        return ((0..median_idx).collect(), (median_idx..n).collect());
    }

    let mc = MinCutBuilder::new()
        .exact()
        .with_edges(edges)
        .build()
        .expect("MinCutBuilder::build thất bại");
    let (side_a, side_b) = mc.partition();

    // Phía có trung bình độ nhạy cao hơn là nhóm "nhạy"
    let mean_a: f32 = if side_a.is_empty() {
        0.0_f32
    } else {
        side_a.iter().map(|&i| sensitivity[i as usize]).sum::<f32>() / side_a.len() as f32
    };
    let mean_b: f32 = if side_b.is_empty() {
        0.0_f32
    } else {
        side_b.iter().map(|&i| sensitivity[i as usize]).sum::<f32>() / side_b.len() as f32
    };

    if mean_a >= mean_b {
        (
            side_a.into_iter().map(|x| x as usize).collect(),
            side_b.into_iter().map(|x| x as usize).collect(),
        )
    } else {
        (
            side_b.into_iter().map(|x| x as usize).collect(),
            side_a.into_iter().map(|x| x as usize).collect(),
        )
    }
}

/// Các lỗi từ chọn lọc sóng mang con.
#[derive(Debug, thiserror::Error)]
pub enum SelectionError {
    #[error("Số sóng mang con không khớp: chuyển_động={motion}, tĩnh={statik}")]
    SubcarrierCountMismatch { motion: usize, statik: usize },

    #[error("Không có sóng mang con trong đầu vào")]
    NoSubcarriers,

    #[error("Không có sóng mang con nào đạt tiêu chí chọn lọc")]
    NoSubcarriersSelected,

    #[error("Chỉ số sóng mang con {index} ngoài phạm vi (tối đa {max})")]
    IndexOutOfBounds { index: usize, max: usize },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sensitive_subcarriers_ranked() {
        // 3 sóng mang con: SC0 phương sai chuyển động cao, SC1 thấp, SC2 trung bình
        let motion = Array2::from_shape_fn((100, 3), |(t, sc)| match sc {
            0 => (t as f64 * 0.1).sin() * 5.0,  // phương sai cao
            1 => (t as f64 * 0.1).sin() * 0.1,  // phương sai thấp
            2 => (t as f64 * 0.1).sin() * 2.0,  // phương sai trung bình
            _ => 0.0,
        });
        let statik = Array2::from_shape_fn((100, 3), |(_, _)| 0.01);

        let config = SubcarrierSelectionConfig {
            top_k: 3,
            min_sensitivity: 0.0,
        };
        let result = select_sensitive_subcarriers(&motion, &statik, &config).unwrap();

        // SC0 phải được xếp hạng đầu (độ nhạy cao nhất)
        assert_eq!(result.selected_indices[0], 0);
        // SC2 phải thứ hai
        assert_eq!(result.selected_indices[1], 2);
        // SC1 phải cuối cùng
        assert_eq!(result.selected_indices[2], 1);
    }

    #[test]
    fn test_top_k_limits_output() {
        let motion = Array2::from_shape_fn((50, 20), |(t, sc)| {
            (t as f64 * 0.05).sin() * (sc as f64 + 1.0)
        });
        let statik = Array2::from_elem((50, 20), 0.01);

        let config = SubcarrierSelectionConfig {
            top_k: 5,
            min_sensitivity: 0.0,
        };
        let result = select_sensitive_subcarriers(&motion, &statik, &config).unwrap();
        assert_eq!(result.selected_indices.len(), 5);
    }

    #[test]
    fn test_min_sensitivity_filter() {
        // Tất cả sóng mang con có độ nhạy rất thấp
        let motion = Array2::from_elem((50, 10), 1.0);
        let statik = Array2::from_elem((50, 10), 1.0);

        let config = SubcarrierSelectionConfig {
            top_k: 10,
            min_sensitivity: 2.0, // Không cái nào vượt qua
        };
        let result = select_sensitive_subcarriers(&motion, &statik, &config).unwrap();
        assert!(result.selected_indices.is_empty());
    }

    #[test]
    fn test_extract_selected_columns() {
        let data = Array2::from_shape_fn((10, 5), |(r, c)| (r * 5 + c) as f64);

        let selection = SubcarrierSelection {
            selected_indices: vec![1, 3],
            sensitivity_scores: vec![0.0; 5],
            selected_data: None,
        };

        let extracted = extract_selected(&data, &selection).unwrap();
        assert_eq!(extracted.dim(), (10, 2));

        // Cột 0 đã trích xuất phải là cột 1 của gốc
        for r in 0..10 {
            assert_eq!(extracted[[r, 0]], data[[r, 1]]);
            assert_eq!(extracted[[r, 1]], data[[r, 3]]);
        }
    }

    #[test]
    fn test_variance_based_selection() {
        let data = Array2::from_shape_fn((100, 5), |(t, sc)| {
            (t as f64 * 0.1).sin() * (sc as f64 + 1.0)
        });

        let config = SubcarrierSelectionConfig {
            top_k: 3,
            min_sensitivity: 0.0,
        };
        let result = select_by_variance(&data, &config);

        assert_eq!(result.selected_indices.len(), 3);
        // SC4 (biên độ cao nhất) phải đứng đầu
        assert_eq!(result.selected_indices[0], 4);
    }

    #[test]
    fn test_mismatch_error() {
        let motion = Array2::zeros((10, 5));
        let statik = Array2::zeros((10, 3));

        assert!(matches!(
            select_sensitive_subcarriers(&motion, &statik, &SubcarrierSelectionConfig::default()),
            Err(SelectionError::SubcarrierCountMismatch { .. })
        ));
    }
}

#[cfg(test)]
mod mincut_tests {
    use super::*;

    #[test]
    fn mincut_partition_separates_high_low() {
        // Độ nhạy cao: chỉ số 0,1,2; thấp: 3,4,5
        let sensitivity = vec![0.9_f32, 0.85, 0.92, 0.1, 0.12, 0.08];
        let (sensitive, insensitive) = mincut_subcarrier_partition(&sensitivity);
        // Chỉ số độ nhạy cao phải gom nhóm với nhau
        assert!(!sensitive.is_empty());
        assert!(!insensitive.is_empty());
        let sens_mean: f32 = sensitive.iter().map(|&i| sensitivity[i]).sum::<f32>() / sensitive.len() as f32;
        let insens_mean: f32 = insensitive.iter().map(|&i| sensitivity[i]).sum::<f32>() / insensitive.len() as f32;
        assert!(sens_mean > insens_mean, "trung bình nhạy {sens_mean} phải lớn hơn trung bình không nhạy {insens_mean}");
    }

    #[test]
    fn mincut_partition_small_input() {
        let sensitivity = vec![0.5_f32, 0.8];
        let (sensitive, insensitive) = mincut_subcarrier_partition(&sensitivity);
        assert_eq!(sensitive.len() + insensitive.len(), 2);
    }
}
