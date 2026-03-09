//! Chụp cắt lớp RF thô từ suy hao trên các liên kết.
//!
//! Tạo ra thể tích chiếm dụng 3D độ phân giải thấp bằng cách nghịch đảo
//! các phép đo suy hao trên từng liên kết. Mỗi voxel nhận một xác suất
//! chiếm dụng dựa trên số liên kết xuyên qua nó và mức suy hao mà
//! các liên kết đó quan sát được.
//!
//! # Thuật toán
//! 1. Định nghĩa lưới voxel bao phủ thể tích giám sát
//! 2. Với mỗi liên kết, xác định các voxel nằm dọc đường truyền sóng
//! 3. Giải bài toán nghịch đảo chụp cắt lớp thưa: suy hao = tổng(mật_độ_voxel * trọng_số_đường)
//! 4. Áp dụng chính quy hóa L1 để đảm bảo tính thưa (hầu hết voxel không bị chiếm dụng)
//!
//! # Tài liệu tham khảo
//! - ADR-030 Tier 2: Chụp cắt lớp RF thô
//! - Wilson & Patwari (2010), "Radio Tomographic Imaging"

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ thao tác chụp cắt lớp.
#[derive(Debug, thiserror::Error)]
pub enum TomographyError {
    /// Không đủ liên kết cho nghịch đảo chụp cắt lớp.
    #[error("Không đủ liên kết: cần >= {needed}, có {got}")]
    InsufficientLinks { needed: usize, got: usize },

    /// Kích thước lưới không hợp lệ.
    #[error("Kích thước lưới không hợp lệ: {0}")]
    InvalidGrid(String),

    /// Không có voxel nào bị giao cắt bởi liên kết.
    #[error("Không có voxel nào bị giao cắt bởi liên kết — kiểm tra hình học")]
    NoIntersections,

    /// Độ dài vector quan sát không khớp.
    #[error("Độ dài quan sát không khớp: kỳ vọng {expected}, nhận được {got}")]
    ObservationMismatch { expected: usize, got: usize },
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho lưới voxel và bộ giải chụp cắt lớp.
#[derive(Debug, Clone)]
pub struct TomographyConfig {
    /// Số voxel theo trục X.
    pub nx: usize,
    /// Số voxel theo trục Y.
    pub ny: usize,
    /// Số voxel theo trục Z.
    pub nz: usize,
    /// Phạm vi vật lý của lưới: `[x_min, y_min, z_min, x_max, y_max, z_max]`.
    pub bounds: [f64; 6],
    /// Trọng số chính quy hóa L1 (cao hơn = nghiệm thưa hơn).
    pub lambda: f64,
    /// Số vòng lặp tối đa cho bộ giải.
    pub max_iterations: usize,
    /// Ngưỡng hội tụ.
    pub tolerance: f64,
    /// Số liên kết tối thiểu cần cho nghịch đảo (mặc định 8).
    pub min_links: usize,
}

impl Default for TomographyConfig {
    fn default() -> Self {
        Self {
            nx: 8,
            ny: 8,
            nz: 4,
            bounds: [0.0, 0.0, 0.0, 6.0, 6.0, 3.0],
            lambda: 0.1,
            max_iterations: 100,
            tolerance: 1e-4,
            min_links: 8,
        }
    }
}

// ---------------------------------------------------------------------------
// Kiểu hình học
// ---------------------------------------------------------------------------

/// Vị trí 3D.
#[derive(Debug, Clone, Copy)]
pub struct Position3D {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

/// Một liên kết giữa máy phát và máy thu.
#[derive(Debug, Clone)]
pub struct LinkGeometry {
    /// Vị trí máy phát.
    pub tx: Position3D,
    /// Vị trí máy thu.
    pub rx: Position3D,
    /// Định danh liên kết.
    pub link_id: usize,
}

impl LinkGeometry {
    /// Khoảng cách Euclid giữa TX và RX.
    pub fn distance(&self) -> f64 {
        let dx = self.rx.x - self.tx.x;
        let dy = self.rx.y - self.tx.y;
        let dz = self.rx.z - self.tx.z;
        (dx * dx + dy * dy + dz * dz).sqrt()
    }
}

// ---------------------------------------------------------------------------
// Thể tích chiếm dụng
// ---------------------------------------------------------------------------

/// Lưới chiếm dụng 3D kết quả từ nghịch đảo chụp cắt lớp.
#[derive(Debug, Clone)]
pub struct OccupancyVolume {
    /// Mật độ voxel theo thứ tự hàng chính `[nz][ny][nx]`.
    pub densities: Vec<f64>,
    /// Kích thước lưới.
    pub nx: usize,
    pub ny: usize,
    pub nz: usize,
    /// Giới hạn vật lý.
    pub bounds: [f64; 6],
    /// Số voxel bị chiếm dụng (mật độ > ngưỡng).
    pub occupied_count: usize,
    /// Tổng số voxel.
    pub total_voxels: usize,
    /// Phần dư của bộ giải tại hội tụ.
    pub residual: f64,
    /// Số vòng lặp đã sử dụng.
    pub iterations: usize,
}

impl OccupancyVolume {
    /// Lấy mật độ tại voxel (ix, iy, iz). Trả về None nếu ngoài phạm vi.
    pub fn get(&self, ix: usize, iy: usize, iz: usize) -> Option<f64> {
        if ix < self.nx && iy < self.ny && iz < self.nz {
            Some(self.densities[iz * self.ny * self.nx + iy * self.nx + ix])
        } else {
            None
        }
    }

    /// Kích thước voxel theo mỗi trục.
    pub fn voxel_size(&self) -> [f64; 3] {
        [
            (self.bounds[3] - self.bounds[0]) / self.nx as f64,
            (self.bounds[4] - self.bounds[1]) / self.ny as f64,
            (self.bounds[5] - self.bounds[2]) / self.nz as f64,
        ]
    }

    /// Vị trí tâm của voxel (ix, iy, iz).
    pub fn voxel_center(&self, ix: usize, iy: usize, iz: usize) -> Position3D {
        let vs = self.voxel_size();
        Position3D {
            x: self.bounds[0] + (ix as f64 + 0.5) * vs[0],
            y: self.bounds[1] + (iy as f64 + 0.5) * vs[1],
            z: self.bounds[2] + (iz as f64 + 0.5) * vs[2],
        }
    }
}

// ---------------------------------------------------------------------------
// Bộ giải chụp cắt lớp
// ---------------------------------------------------------------------------

/// Bộ giải chụp cắt lớp RF thô.
///
/// Với một tập hợp liên kết TX-RX và phép đo suy hao trên từng liên kết,
/// tái tạo thể tích chiếm dụng 3D bằng bình phương tối thiểu có chính quy L1.
pub struct RfTomographer {
    config: TomographyConfig,
    /// Ma trận trọng số đã tính trước: `weight_matrix[link_idx]` là danh sách
    /// các cặp (chỉ_số_voxel, trọng_số).
    weight_matrix: Vec<Vec<(usize, f64)>>,
    /// Số lượng voxel.
    n_voxels: usize,
}

impl RfTomographer {
    /// Tạo bộ chụp cắt lớp mới với cấu hình và hình học liên kết cho trước.
    pub fn new(config: TomographyConfig, links: &[LinkGeometry]) -> Result<Self, TomographyError> {
        if links.len() < config.min_links {
            return Err(TomographyError::InsufficientLinks {
                needed: config.min_links,
                got: links.len(),
            });
        }
        if config.nx == 0 || config.ny == 0 || config.nz == 0 {
            return Err(TomographyError::InvalidGrid(
                "Kích thước lưới phải > 0".into(),
            ));
        }

        let n_voxels = config
            .nx
            .checked_mul(config.ny)
            .and_then(|v| v.checked_mul(config.nz))
            .ok_or_else(|| {
                TomographyError::InvalidGrid(format!(
                    "Kích thước lưới tràn số: {}x{}x{}",
                    config.nx, config.ny, config.nz
                ))
            })?;

        // Tính trước ma trận trọng số
        let weight_matrix: Vec<Vec<(usize, f64)>> = links
            .iter()
            .map(|link| compute_link_weights(link, &config))
            .collect();

        // Đảm bảo ít nhất một liên kết giao cắt với voxel nào đó
        let total_weights: usize = weight_matrix.iter().map(|w| w.len()).sum();
        if total_weights == 0 {
            return Err(TomographyError::NoIntersections);
        }

        Ok(Self {
            config,
            weight_matrix,
            n_voxels,
        })
    }

    /// Tái tạo chiếm dụng từ phép đo suy hao trên từng liên kết.
    ///
    /// `attenuations` có một phần tử cho mỗi liên kết (cùng thứ tự với liên kết truyền vào `new`).
    /// Suy hao cao hơn cho thấy vật cản nhiều hơn dọc đường truyền liên kết.
    pub fn reconstruct(&self, attenuations: &[f64]) -> Result<OccupancyVolume, TomographyError> {
        if attenuations.len() != self.weight_matrix.len() {
            return Err(TomographyError::ObservationMismatch {
                expected: self.weight_matrix.len(),
                got: attenuations.len(),
            });
        }

        // ISTA (Thuật toán co rút-ngưỡng lặp) cho tối thiểu hóa L1
        // min ||Wx - y||^2 + lambda * ||x||_1
        let mut x = vec![0.0_f64; self.n_voxels];
        let n_links = attenuations.len();

        // Ước lượng bước nhảy: 1 / L với L là hằng số Lipschitz của
        // gradient ||Wx - y||^2, tức chuẩn phổ của W^T W.
        // Cận trên an toàn là bình phương chuẩn Frobenius của W (tổng tất cả
        // các phần tử bình phương), vì ||W^T W|| <= ||W||_F^2.
        let frobenius_sq: f64 = self
            .weight_matrix
            .iter()
            .flat_map(|ws| ws.iter().map(|&(_, w)| w * w))
            .sum();
        let lipschitz = frobenius_sq.max(1e-10);
        let step_size = 1.0 / lipschitz;

        let mut residual = 0.0_f64;
        let mut iterations = 0;

        for iter in 0..self.config.max_iterations {
            // Tính gradient: W^T (Wx - y)
            let mut gradient = vec![0.0_f64; self.n_voxels];
            residual = 0.0;

            for (link_idx, weights) in self.weight_matrix.iter().enumerate() {
                // Chiều thuận: Wx cho liên kết này
                let predicted: f64 = weights.iter().map(|&(idx, w)| w * x[idx]).sum();
                let diff = predicted - attenuations[link_idx];
                residual += diff * diff;

                // Chiều ngược: tích lũy gradient
                for &(idx, w) in weights {
                    gradient[idx] += w * diff;
                }
            }

            residual = (residual / n_links as f64).sqrt();

            // Bước gradient + co rút mềm (proximal L1)
            let mut max_change = 0.0_f64;
            for i in 0..self.n_voxels {
                let new_val = x[i] - step_size * gradient[i];
                // Co rút mềm
                let threshold = self.config.lambda * step_size;
                let shrunk = if new_val > threshold {
                    new_val - threshold
                } else if new_val < -threshold {
                    new_val + threshold
                } else {
                    0.0
                };
                // Ràng buộc không âm (mật độ >= 0)
                let clamped = shrunk.max(0.0);
                max_change = max_change.max((clamped - x[i]).abs());
                x[i] = clamped;
            }

            iterations = iter + 1;

            if max_change < self.config.tolerance {
                break;
            }
        }

        // Đếm voxel bị chiếm dụng (mật độ > 0.01)
        let occupied_count = x.iter().filter(|&&d| d > 0.01).count();

        Ok(OccupancyVolume {
            densities: x,
            nx: self.config.nx,
            ny: self.config.ny,
            nz: self.config.nz,
            bounds: self.config.bounds,
            occupied_count,
            total_voxels: self.n_voxels,
            residual,
            iterations,
        })
    }

    /// Số liên kết trong bộ chụp cắt lớp này.
    pub fn n_links(&self) -> usize {
        self.weight_matrix.len()
    }

    /// Số voxel trong lưới.
    pub fn n_voxels(&self) -> usize {
        self.n_voxels
    }
}

// ---------------------------------------------------------------------------
// Tính trọng số (giao cắt tia-voxel đơn giản hóa)
// ---------------------------------------------------------------------------

/// Tính trọng số giao cắt của một liên kết với lưới voxel.
///
/// Sử dụng phương pháp đơn giản hóa: cho mỗi voxel, tính khoảng cách
/// tối thiểu từ tâm voxel đến tia liên kết. Các voxel nằm trong
/// một vùng Fresnel nhận trọng số tỉ lệ thuận với độ gần.
fn compute_link_weights(link: &LinkGeometry, config: &TomographyConfig) -> Vec<(usize, f64)> {
    let vx = (config.bounds[3] - config.bounds[0]) / config.nx as f64;
    let vy = (config.bounds[4] - config.bounds[1]) / config.ny as f64;
    let vz = (config.bounds[5] - config.bounds[2]) / config.nz as f64;

    // Bán kính nửa vùng Fresnel (xấp xỉ)
    let link_dist = link.distance();
    let wavelength = 0.06; // ~5 GHz
    let fresnel_radius = (wavelength * link_dist / 4.0).sqrt().max(vx.max(vy));

    let dx = link.rx.x - link.tx.x;
    let dy = link.rx.y - link.tx.y;
    let dz = link.rx.z - link.tx.z;

    let mut weights = Vec::new();

    for iz in 0..config.nz {
        for iy in 0..config.ny {
            for ix in 0..config.nx {
                let cx = config.bounds[0] + (ix as f64 + 0.5) * vx;
                let cy = config.bounds[1] + (iy as f64 + 0.5) * vy;
                let cz = config.bounds[2] + (iz as f64 + 0.5) * vz;

                // Khoảng cách từ điểm đến đường thẳng
                let dist = point_to_segment_distance(
                    cx, cy, cz, link.tx.x, link.tx.y, link.tx.z, dx, dy, dz, link_dist,
                );

                if dist < fresnel_radius {
                    // Trọng số giảm theo khoảng cách từ tia liên kết
                    let w = 1.0 - dist / fresnel_radius;
                    let idx = iz * config.ny * config.nx + iy * config.nx + ix;
                    weights.push((idx, w));
                }
            }
        }
    }

    weights
}

/// Khoảng cách từ điểm (px,py,pz) đến đoạn thẳng xác định bởi start + t*dir
/// trong đó dir = (dx,dy,dz) và chiều dài đoạn = `seg_len`.
fn point_to_segment_distance(
    px: f64,
    py: f64,
    pz: f64,
    sx: f64,
    sy: f64,
    sz: f64,
    dx: f64,
    dy: f64,
    dz: f64,
    seg_len: f64,
) -> f64 {
    if seg_len < 1e-12 {
        return ((px - sx).powi(2) + (py - sy).powi(2) + (pz - sz).powi(2)).sqrt();
    }

    // Chiếu điểm lên đường thẳng: t = dot(P-S, D) / |D|^2
    let t = ((px - sx) * dx + (py - sy) * dy + (pz - sz) * dz) / (seg_len * seg_len);
    let t_clamped = t.clamp(0.0, 1.0);

    let closest_x = sx + t_clamped * dx;
    let closest_y = sy + t_clamped * dy;
    let closest_z = sz + t_clamped * dz;

    ((px - closest_x).powi(2) + (py - closest_y).powi(2) + (pz - closest_z).powi(2)).sqrt()
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_square_links() -> Vec<LinkGeometry> {
        // 4 nút trong hình vuông tại z=1.5, 12 liên kết có hướng
        let nodes = [
            Position3D {
                x: 0.5,
                y: 0.5,
                z: 1.5,
            },
            Position3D {
                x: 5.5,
                y: 0.5,
                z: 1.5,
            },
            Position3D {
                x: 5.5,
                y: 5.5,
                z: 1.5,
            },
            Position3D {
                x: 0.5,
                y: 5.5,
                z: 1.5,
            },
        ];
        let mut links = Vec::new();
        let mut id = 0;
        for i in 0..4 {
            for j in 0..4 {
                if i != j {
                    links.push(LinkGeometry {
                        tx: nodes[i],
                        rx: nodes[j],
                        link_id: id,
                    });
                    id += 1;
                }
            }
        }
        links
    }

    #[test]
    fn test_tomographer_creation() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();
        assert_eq!(tomo.n_links(), 12);
        assert_eq!(tomo.n_voxels(), 8 * 8 * 4);
    }

    #[test]
    fn test_insufficient_links() {
        let links = vec![LinkGeometry {
            tx: Position3D {
                x: 0.0,
                y: 0.0,
                z: 0.0,
            },
            rx: Position3D {
                x: 1.0,
                y: 0.0,
                z: 0.0,
            },
            link_id: 0,
        }];
        let config = TomographyConfig {
            min_links: 8,
            ..Default::default()
        };
        assert!(matches!(
            RfTomographer::new(config, &links),
            Err(TomographyError::InsufficientLinks { .. })
        ));
    }

    #[test]
    fn test_invalid_grid() {
        let links = make_square_links();
        let config = TomographyConfig {
            nx: 0,
            ..Default::default()
        };
        assert!(matches!(
            RfTomographer::new(config, &links),
            Err(TomographyError::InvalidGrid(_))
        ));
    }

    #[test]
    fn test_zero_attenuation_empty_room() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        // Suy hao bằng 0 = phòng trống
        let attenuations = vec![0.0; tomo.n_links()];
        let volume = tomo.reconstruct(&attenuations).unwrap();

        assert_eq!(volume.total_voxels, 8 * 8 * 4);
        // Tất cả mật độ phải bằng 0 hoặc gần 0
        assert!(
            volume.occupied_count == 0,
            "Phòng trống không nên có voxel bị chiếm dụng, nhận được {}",
            volume.occupied_count
        );
    }

    #[test]
    fn test_nonzero_attenuation_produces_density() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            lambda: 0.001, // chính quy nhẹ để nghiệm không bị triệt tiêu
            max_iterations: 500,
            tolerance: 1e-8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        // Suy hao lớn để đại diện cho liên kết bị vật cản
        let attenuations: Vec<f64> = (0..tomo.n_links()).map(|i| 5.0 + 1.0 * i as f64).collect();
        let volume = tomo.reconstruct(&attenuations).unwrap();

        // Kiểm tra ít nhất một số voxel có mật độ đáng kể
        let any_nonzero = volume.densities.iter().any(|&d| d > 1e-6);
        assert!(
            any_nonzero,
            "Suy hao khác 0 phải tạo ra mật độ voxel khác 0"
        );
    }

    #[test]
    fn test_observation_mismatch() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        let attenuations = vec![0.1; 3]; // số lượng sai
        assert!(matches!(
            tomo.reconstruct(&attenuations),
            Err(TomographyError::ObservationMismatch { .. })
        ));
    }

    #[test]
    fn test_voxel_access() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        let attenuations = vec![0.0; tomo.n_links()];
        let volume = tomo.reconstruct(&attenuations).unwrap();

        // Truy cập hợp lệ
        assert!(volume.get(0, 0, 0).is_some());
        assert!(volume.get(7, 7, 3).is_some());
        // Ngoài phạm vi
        assert!(volume.get(8, 0, 0).is_none());
        assert!(volume.get(0, 8, 0).is_none());
        assert!(volume.get(0, 0, 4).is_none());
    }

    #[test]
    fn test_voxel_center() {
        let links = make_square_links();
        let config = TomographyConfig {
            nx: 6,
            ny: 6,
            nz: 3,
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        let attenuations = vec![0.0; tomo.n_links()];
        let volume = tomo.reconstruct(&attenuations).unwrap();

        let center = volume.voxel_center(0, 0, 0);
        assert!(center.x > 0.0 && center.x < 1.0);
        assert!(center.y > 0.0 && center.y < 1.0);
        assert!(center.z > 0.0 && center.z < 1.0);
    }

    #[test]
    fn test_voxel_size() {
        let links = make_square_links();
        let config = TomographyConfig {
            nx: 6,
            ny: 6,
            nz: 3,
            bounds: [0.0, 0.0, 0.0, 6.0, 6.0, 3.0],
            min_links: 8,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        let attenuations = vec![0.0; tomo.n_links()];
        let volume = tomo.reconstruct(&attenuations).unwrap();
        let vs = volume.voxel_size();

        assert!((vs[0] - 1.0).abs() < 1e-10);
        assert!((vs[1] - 1.0).abs() < 1e-10);
        assert!((vs[2] - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_point_to_segment_distance() {
        // Điểm nằm trên đoạn thẳng
        let d = point_to_segment_distance(0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0);
        assert!(d < 1e-10);

        // Điểm cách 1 đơn vị phía trên trung điểm
        let d = point_to_segment_distance(0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0);
        assert!((d - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_link_distance() {
        let link = LinkGeometry {
            tx: Position3D {
                x: 0.0,
                y: 0.0,
                z: 0.0,
            },
            rx: Position3D {
                x: 3.0,
                y: 4.0,
                z: 0.0,
            },
            link_id: 0,
        };
        assert!((link.distance() - 5.0).abs() < 1e-10);
    }

    #[test]
    fn test_solver_convergence() {
        let links = make_square_links();
        let config = TomographyConfig {
            min_links: 8,
            lambda: 0.01,
            max_iterations: 500,
            tolerance: 1e-6,
            ..Default::default()
        };
        let tomo = RfTomographer::new(config, &links).unwrap();

        let attenuations: Vec<f64> = (0..tomo.n_links())
            .map(|i| 0.3 * (i as f64 * 0.7).sin().abs())
            .collect();
        let volume = tomo.reconstruct(&attenuations).unwrap();

        assert!(volume.residual.is_finite());
        assert!(volume.iterations > 0);
    }
}
