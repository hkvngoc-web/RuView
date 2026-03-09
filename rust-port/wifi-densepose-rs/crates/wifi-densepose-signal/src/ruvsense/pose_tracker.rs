//! Bộ Theo Dõi Tư Thế Kalman 17 Điểm Khớp với Tái Nhận Dạng (ADR-029 Mục 2.7)
//!
//! Theo dõi nhiều người dưới dạng khung xương 17 điểm khớp bền vững qua thời gian.
//! Mỗi điểm khớp có trạng thái Kalman 6D (x, y, z, vx, vy, vz) với
//! mô hình chuyển động vận tốc hằng. Vòng đời theo dõi tuân theo:
//!
//!   Thử Nghiệm -> Hoạt Động -> Mất Dấu -> Kết Thúc
//!
//! Gán phát hiện-theo dõi sử dụng chi phí kết hợp gồm khoảng cách
//! Mahalanobis (60%) và độ tương đồng cosine nhúng tái nhận dạng AETHER (40%),
//! triển khai qua `ruvector-mincut::DynamicPersonMatcher`.
//!
//! # Tham Số
//!
//! | Tham số | Giá trị | Lý do |
//! |---------|---------|-------|
//! | Chiều trạng thái | 6 mỗi điểm khớp | Mô hình vận tốc hằng |
//! | Nhiễu quá trình | 0.3 m/s^2 | Gia tốc đi bộ bình thường |
//! | Nhiễu đo lường | 0.08 m | Mục tiêu <8cm RMS tại thân |
//! | Số hit sinh | 2 khung | Loại bỏ nhiễu đơn khung |
//! | Số miss mất | 5 khung | Dung sai che khuất ngắn |
//! | Nhúng tái nhận dạng | 128 chiều | Phân biệt hình dáng cơ thể AETHER |
//! | Cửa sổ tái nhận dạng | 5 giây | Khôi phục khi giao nhau |
//!
//! # Tích Hợp RuVector
//!
//! - `ruvector-mincut` -> Phân tách người và gán theo dõi

use super::{TrackId, NUM_KEYPOINTS};

/// Các lỗi từ bộ theo dõi tư thế.
#[derive(Debug, thiserror::Error)]
pub enum PoseTrackerError {
    /// Chỉ số điểm khớp không hợp lệ.
    #[error("Chỉ số điểm khớp không hợp lệ {index}, tối đa là {}", NUM_KEYPOINTS - 1)]
    InvalidKeypointIndex { index: usize },

    /// Chiều nhúng không hợp lệ.
    #[error("Chiều nhúng {got} không khớp với kỳ vọng {expected}")]
    EmbeddingDimMismatch { expected: usize, got: usize },

    /// Vượt cổng Mahalanobis.
    #[error("Khoảng cách Mahalanobis {distance:.2} vượt cổng {gate:.2}")]
    MahalanobisGateExceeded { distance: f32, gate: f32 },

    /// Không tìm thấy theo dõi.
    #[error("Không tìm thấy theo dõi {0}")]
    TrackNotFound(TrackId),

    /// Không có phát hiện nào được cung cấp.
    #[error("Không có phát hiện nào được cung cấp để cập nhật")]
    NoDetections,
}

/// Trạng thái Kalman mỗi điểm khớp.
///
/// Duy trì vector trạng thái 6D [x, y, z, vx, vy, vz] và ma trận hiệp
/// phương sai 6x6 lưu dạng tam giác trên (21 phần tử, theo hàng).
#[derive(Debug, Clone)]
pub struct KeypointState {
    /// Vector trạng thái [x, y, z, vx, vy, vz].
    pub state: [f32; 6],
    /// Tam giác trên hiệp phương sai 6x6 (21 phần tử, theo hàng).
    /// Chỉ số: (0,0)=0, (0,1)=1, (0,2)=2, (0,3)=3, (0,4)=4, (0,5)=5,
    ///          (1,1)=6, (1,2)=7, (1,3)=8, (1,4)=9, (1,5)=10,
    ///          (2,2)=11, (2,3)=12, (2,4)=13, (2,5)=14,
    ///          (3,3)=15, (3,4)=16, (3,5)=17,
    ///          (4,4)=18, (4,5)=19,
    ///          (5,5)=20
    pub covariance: [f32; 21],
    /// Độ tin cậy (0.0-1.0) từ đầu ra mô hình DensePose.
    pub confidence: f32,
}

impl KeypointState {
    /// Tạo trạng thái điểm khớp mới tại vị trí 3D cho trước.
    pub fn new(x: f32, y: f32, z: f32) -> Self {
        let mut cov = [0.0_f32; 21];
        // Khởi tạo đường chéo với độ bất định mặc định
        let pos_var = 0.1 * 0.1;  // Độ bất định vị trí ban đầu 10 cm
        let vel_var = 0.5 * 0.5;  // Độ bất định vận tốc ban đầu 0.5 m/s
        cov[0] = pos_var;   // phương sai x
        cov[6] = pos_var;   // phương sai y
        cov[11] = pos_var;  // phương sai z
        cov[15] = vel_var;  // phương sai vx
        cov[18] = vel_var;  // phương sai vy
        cov[20] = vel_var;  // phương sai vz

        Self {
            state: [x, y, z, 0.0, 0.0, 0.0],
            covariance: cov,
            confidence: 0.0,
        }
    }

    /// Trả về vị trí [x, y, z].
    pub fn position(&self) -> [f32; 3] {
        [self.state[0], self.state[1], self.state[2]]
    }

    /// Trả về vận tốc [vx, vy, vz].
    pub fn velocity(&self) -> [f32; 3] {
        [self.state[3], self.state[4], self.state[5]]
    }

    /// Bước dự đoán: tiến trạng thái dt giây sử dụng mô hình vận tốc hằng.
    ///
    /// x' = x + vx * dt
    /// P' = F * P * F^T + Q
    pub fn predict(&mut self, dt: f32, process_noise_accel: f32) {
        // Dự đoán trạng thái: x' = x + v * dt
        self.state[0] += self.state[3] * dt;
        self.state[1] += self.state[4] * dt;
        self.state[2] += self.state[5] * dt;

        // Nhiễu quá trình Q (mô hình gia tốc hằng)
        let dt2 = dt * dt;
        let dt3 = dt2 * dt;
        let dt4 = dt3 * dt;
        let q = process_noise_accel * process_noise_accel;

        // Thêm nhiễu quá trình vào các phần tử đường chéo
        // Phương sai vị trí: + q * dt^4 / 4
        let pos_q = q * dt4 / 4.0;
        // Phương sai vận tốc: + q * dt^2
        let vel_q = q * dt2;
        // Chéo vị trí-vận tốc: + q * dt^3 / 2
        let _cross_q = q * dt3 / 2.0;

        // Đơn giản hoá: chỉ cập nhật đường chéo cho ổn định số học
        self.covariance[0] += pos_q;   // xx
        self.covariance[6] += pos_q;   // yy
        self.covariance[11] += pos_q;  // zz
        self.covariance[15] += vel_q;  // vxvx
        self.covariance[18] += vel_q;  // vyvy
        self.covariance[20] += vel_q;  // vzvz
    }

    /// Cập nhật đo lường: tích hợp quan sát vị trí [x, y, z].
    ///
    /// Sử dụng cập nhật Kalman chuẩn với mô hình đo lường chỉ vị trí
    /// H = [I3 | 0_3x3].
    pub fn update(
        &mut self,
        measurement: &[f32; 3],
        measurement_noise: f32,
        noise_multiplier: f32,
    ) {
        let r = measurement_noise * measurement_noise * noise_multiplier;

        // Đổi mới (phần dư)
        let innov = [
            measurement[0] - self.state[0],
            measurement[1] - self.state[1],
            measurement[2] - self.state[2],
        ];

        // Hiệp phương sai đổi mới S = H * P * H^T + R
        // Vì H = [I3 | 0], S chỉ là khối 3x3 trên-trái của P + R
        let s = [
            self.covariance[0] + r,
            self.covariance[6] + r,
            self.covariance[11] + r,
        ];

        // Độ lợi Kalman K = P * H^T * S^-1
        // Với S đường chéo, K_ij = P_ij / S_jj (đơn giản hoá)
        let k = [
            [self.covariance[0] / s[0], 0.0, 0.0],               // hàng x
            [0.0, self.covariance[6] / s[1], 0.0],               // hàng y
            [0.0, 0.0, self.covariance[11] / s[2]],              // hàng z
            [self.covariance[3] / s[0], 0.0, 0.0],               // hàng vx
            [0.0, self.covariance[9] / s[1], 0.0],               // hàng vy
            [0.0, 0.0, self.covariance[14] / s[2]],              // hàng vz
        ];

        // Cập nhật trạng thái: x' = x + K * đổi mới
        for i in 0..6 {
            for j in 0..3 {
                self.state[i] += k[i][j] * innov[j];
            }
        }

        // Cập nhật hiệp phương sai: P' = (I - K*H) * P (cập nhật đường chéo đơn giản)
        self.covariance[0] *= 1.0 - k[0][0];
        self.covariance[6] *= 1.0 - k[1][1];
        self.covariance[11] *= 1.0 - k[2][2];
    }

    /// Tính khoảng cách Mahalanobis giữa trạng thái này và một đo lường.
    pub fn mahalanobis_distance(&self, measurement: &[f32; 3]) -> f32 {
        let innov = [
            measurement[0] - self.state[0],
            measurement[1] - self.state[1],
            measurement[2] - self.state[2],
        ];

        // Sử dụng xấp xỉ đường chéo
        let mut dist_sq = 0.0_f32;
        let variances = [self.covariance[0], self.covariance[6], self.covariance[11]];
        for i in 0..3 {
            let v = variances[i].max(1e-6);
            dist_sq += innov[i] * innov[i] / v;
        }

        dist_sq.sqrt()
    }
}

impl Default for KeypointState {
    fn default() -> Self {
        Self::new(0.0, 0.0, 0.0)
    }
}

/// Máy trạng thái vòng đời theo dõi.
///
/// Tuân theo mẫu từ ADR-026:
///   Thử Nghiệm -> Hoạt Động -> Mất Dấu -> Kết Thúc
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrackLifecycleState {
    /// Theo dõi đã được phát hiện nhưng chưa xác nhận (< birth_hits khung).
    Tentative,
    /// Theo dõi đã xác nhận và đang được cập nhật tích cực.
    Active,
    /// Theo dõi đã mất liên kết đo lường (< loss_misses khung).
    Lost,
    /// Theo dõi đã bị kết thúc (vượt thời gian mất tối đa hoặc xác định là dương tính giả).
    Terminated,
}

impl TrackLifecycleState {
    /// Trả về true nếu theo dõi ở trạng thái hoạt động hoặc thử nghiệm.
    pub fn is_alive(&self) -> bool {
        matches!(self, Self::Tentative | Self::Active | Self::Lost)
    }

    /// Trả về true nếu theo dõi có thể nhận cập nhật đo lường.
    pub fn accepts_updates(&self) -> bool {
        matches!(self, Self::Tentative | Self::Active)
    }

    /// Trả về true nếu theo dõi đủ điều kiện cho tái nhận dạng.
    pub fn is_lost(&self) -> bool {
        matches!(self, Self::Lost)
    }
}

/// Một theo dõi tư thế -- gốc tổng hợp để theo dõi một người.
///
/// Chứa 17 trạng thái Kalman điểm khớp, vòng đời, và nhúng tái nhận dạng.
#[derive(Debug, Clone)]
pub struct PoseTrack {
    /// Định danh theo dõi duy nhất.
    pub id: TrackId,
    /// Trạng thái Kalman mỗi điểm khớp (thứ tự COCO-17).
    pub keypoints: [KeypointState; NUM_KEYPOINTS],
    /// Trạng thái vòng đời theo dõi.
    pub lifecycle: TrackLifecycleState,
    /// Nhúng AETHER trung bình cuốn cho tái nhận dạng (128 chiều).
    pub embedding: Vec<f32>,
    /// Tổng số khung kể từ khi tạo.
    pub age: u64,
    /// Số khung kể từ lần cập nhật đo lường thành công gần nhất.
    pub time_since_update: u64,
    /// Số lần cập nhật đo lường liên tiếp (cho cổng sinh).
    pub consecutive_hits: u64,
    /// Dấu thời gian tạo tính bằng micro giây.
    pub created_at: u64,
    /// Dấu thời gian cập nhật gần nhất tính bằng micro giây.
    pub updated_at: u64,
}

impl PoseTrack {
    /// Tạo theo dõi thử nghiệm mới từ một phát hiện.
    pub fn new(
        id: TrackId,
        keypoint_positions: &[[f32; 3]; NUM_KEYPOINTS],
        timestamp_us: u64,
        embedding_dim: usize,
    ) -> Self {
        let keypoints = std::array::from_fn(|i| {
            let [x, y, z] = keypoint_positions[i];
            KeypointState::new(x, y, z)
        });

        Self {
            id,
            keypoints,
            lifecycle: TrackLifecycleState::Tentative,
            embedding: vec![0.0; embedding_dim],
            age: 0,
            time_since_update: 0,
            consecutive_hits: 1,
            created_at: timestamp_us,
            updated_at: timestamp_us,
        }
    }

    /// Dự đoán tất cả điểm khớp tiến dt giây.
    pub fn predict(&mut self, dt: f32, process_noise: f32) {
        for kp in &mut self.keypoints {
            kp.predict(dt, process_noise);
        }
        self.age += 1;
        self.time_since_update += 1;
    }

    /// Cập nhật tất cả điểm khớp với đo lường mới.
    ///
    /// Đồng thời cập nhật chuyển trạng thái vòng đời dựa trên cổng sinh/mất.
    pub fn update_keypoints(
        &mut self,
        measurements: &[[f32; 3]; NUM_KEYPOINTS],
        measurement_noise: f32,
        noise_multiplier: f32,
        timestamp_us: u64,
    ) {
        for (kp, meas) in self.keypoints.iter_mut().zip(measurements.iter()) {
            kp.update(meas, measurement_noise, noise_multiplier);
        }

        self.time_since_update = 0;
        self.consecutive_hits += 1;
        self.updated_at = timestamp_us;

        // Chuyển đổi vòng đời
        self.update_lifecycle();
    }

    /// Cập nhật nhúng với suy giảm EMA.
    pub fn update_embedding(&mut self, new_embedding: &[f32], decay: f32) {
        if new_embedding.len() != self.embedding.len() {
            return;
        }

        let alpha = 1.0 - decay;
        for (e, &ne) in self.embedding.iter_mut().zip(new_embedding.iter()) {
            *e = decay * *e + alpha * ne;
        }
    }

    /// Tính vị trí trọng tâm (trung bình của tất cả điểm khớp).
    pub fn centroid(&self) -> [f32; 3] {
        let n = NUM_KEYPOINTS as f32;
        let mut c = [0.0_f32; 3];
        for kp in &self.keypoints {
            let pos = kp.position();
            c[0] += pos[0];
            c[1] += pos[1];
            c[2] += pos[2];
        }
        c[0] /= n;
        c[1] /= n;
        c[2] /= n;
        c
    }

    /// Tính RMS rung lắc thân tính bằng mét.
    ///
    /// Sử dụng độ lớn vận tốc các điểm khớp thân (vai, hông)
    /// làm đại diện cho rung lắc.
    pub fn torso_jitter_rms(&self) -> f32 {
        let torso_indices = super::keypoint::TORSO_INDICES;
        let mut sum_sq = 0.0_f32;
        let mut count = 0;

        for &idx in torso_indices {
            let vel = self.keypoints[idx].velocity();
            let speed_sq = vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2];
            sum_sq += speed_sq;
            count += 1;
        }

        if count == 0 {
            return 0.0;
        }

        (sum_sq / count as f32).sqrt()
    }

    /// Đánh dấu theo dõi là mất dấu.
    pub fn mark_lost(&mut self) {
        if self.lifecycle != TrackLifecycleState::Terminated {
            self.lifecycle = TrackLifecycleState::Lost;
        }
    }

    /// Đánh dấu theo dõi là kết thúc.
    pub fn terminate(&mut self) {
        self.lifecycle = TrackLifecycleState::Terminated;
    }

    /// Cập nhật trạng thái vòng đời dựa trên số hit và miss liên tiếp.
    fn update_lifecycle(&mut self) {
        match self.lifecycle {
            TrackLifecycleState::Tentative => {
                if self.consecutive_hits >= 2 {
                    // Cổng sinh: thăng cấp lên Hoạt Động sau 2 lần cập nhật liên tiếp
                    self.lifecycle = TrackLifecycleState::Active;
                }
            }
            TrackLifecycleState::Lost => {
                // Tái thu nhận: thăng cấp lại Hoạt Động
                self.lifecycle = TrackLifecycleState::Active;
                self.consecutive_hits = 1;
            }
            _ => {}
        }
    }
}

/// Tham số cấu hình bộ theo dõi.
#[derive(Debug, Clone)]
pub struct TrackerConfig {
    /// Gia tốc nhiễu quá trình (m/s^2). Mặc định: 0.3.
    pub process_noise: f32,
    /// Độ lệch chuẩn nhiễu đo lường (m). Mặc định: 0.08.
    pub measurement_noise: f32,
    /// Ngưỡng cổng Mahalanobis (chi-squared(3) tại 3-sigma = 9.0).
    pub mahalanobis_gate: f32,
    /// Số khung cần thiết để thăng cấp thử nghiệm->hoạt động. Mặc định: 2.
    pub birth_hits: u64,
    /// Số khung tối đa không cập nhật trước khi chuyển sang mất dấu. Mặc định: 5.
    pub loss_misses: u64,
    /// Cửa sổ tái nhận dạng tính bằng khung (5 giây ở 20Hz = 100). Mặc định: 100.
    pub reid_window: u64,
    /// Tốc độ suy giảm EMA nhúng. Mặc định: 0.95.
    pub embedding_decay: f32,
    /// Chiều nhúng. Mặc định: 128.
    pub embedding_dim: usize,
    /// Trọng số vị trí trong chi phí gán. Mặc định: 0.6.
    pub position_weight: f32,
    /// Trọng số nhúng trong chi phí gán. Mặc định: 0.4.
    pub embedding_weight: f32,
}

impl Default for TrackerConfig {
    fn default() -> Self {
        Self {
            process_noise: 0.3,
            measurement_noise: 0.08,
            mahalanobis_gate: 9.0,
            birth_hits: 2,
            loss_misses: 5,
            reid_window: 100,
            embedding_decay: 0.95,
            embedding_dim: 128,
            position_weight: 0.6,
            embedding_weight: 0.4,
        }
    }
}

/// Bộ theo dõi tư thế đa người.
///
/// Quản lý tập hợp các phiên bản `PoseTrack` với quản lý vòng đời tự động,
/// gán phát hiện-theo dõi, và tái nhận dạng.
#[derive(Debug)]
pub struct PoseTracker {
    config: TrackerConfig,
    tracks: Vec<PoseTrack>,
    next_id: u64,
}

impl PoseTracker {
    /// Tạo bộ theo dõi mới với cấu hình mặc định.
    pub fn new() -> Self {
        Self {
            config: TrackerConfig::default(),
            tracks: Vec::new(),
            next_id: 0,
        }
    }

    /// Tạo bộ theo dõi mới với cấu hình tùy chỉnh.
    pub fn with_config(config: TrackerConfig) -> Self {
        Self {
            config,
            tracks: Vec::new(),
            next_id: 0,
        }
    }

    /// Trả về tất cả theo dõi đang hoạt động (chưa kết thúc).
    pub fn active_tracks(&self) -> Vec<&PoseTrack> {
        self.tracks
            .iter()
            .filter(|t| t.lifecycle.is_alive())
            .collect()
    }

    /// Trả về tất cả theo dõi bao gồm cả đã kết thúc.
    pub fn all_tracks(&self) -> &[PoseTrack] {
        &self.tracks
    }

    /// Trả về số lượng theo dõi đang hoạt động (còn sống).
    pub fn active_count(&self) -> usize {
        self.tracks.iter().filter(|t| t.lifecycle.is_alive()).count()
    }

    /// Bước dự đoán cho tất cả theo dõi (tiến dt giây).
    pub fn predict_all(&mut self, dt: f32) {
        for track in &mut self.tracks {
            if track.lifecycle.is_alive() {
                track.predict(dt, self.config.process_noise);
            }
        }

        // Đánh dấu theo dõi là mất dấu sau khi vượt loss_misses
        for track in &mut self.tracks {
            if track.lifecycle.accepts_updates()
                && track.time_since_update >= self.config.loss_misses
            {
                track.mark_lost();
            }
        }

        // Kết thúc theo dõi đã mất dấu quá lâu
        let reid_window = self.config.reid_window;
        for track in &mut self.tracks {
            if track.lifecycle.is_lost() && track.time_since_update >= reid_window {
                track.terminate();
            }
        }
    }

    /// Tạo theo dõi mới từ một phát hiện.
    pub fn create_track(
        &mut self,
        keypoints: &[[f32; 3]; NUM_KEYPOINTS],
        timestamp_us: u64,
    ) -> TrackId {
        let id = TrackId::new(self.next_id);
        self.next_id += 1;

        let track = PoseTrack::new(id, keypoints, timestamp_us, self.config.embedding_dim);
        self.tracks.push(track);
        id
    }

    /// Tìm theo dõi với ID cho trước.
    pub fn find_track(&self, id: TrackId) -> Option<&PoseTrack> {
        self.tracks.iter().find(|t| t.id == id)
    }

    /// Tìm theo dõi với ID cho trước (có thể thay đổi).
    pub fn find_track_mut(&mut self, id: TrackId) -> Option<&mut PoseTrack> {
        self.tracks.iter_mut().find(|t| t.id == id)
    }

    /// Xoá các theo dõi đã kết thúc khỏi tập hợp.
    pub fn prune_terminated(&mut self) {
        self.tracks
            .retain(|t| t.lifecycle != TrackLifecycleState::Terminated);
    }

    /// Tính chi phí gán giữa một theo dõi và một phát hiện.
    ///
    /// chi phí = trọng_số_vị_trí * mahalanobis(theo_dõi, phát_hiện.vị_trí)
    ///         + trọng_số_nhúng * (1 - cosine_sim(theo_dõi.nhúng, phát_hiện.nhúng))
    pub fn assignment_cost(
        &self,
        track: &PoseTrack,
        detection_centroid: &[f32; 3],
        detection_embedding: &[f32],
    ) -> f32 {
        // Chi phí vị trí: khoảng cách Mahalanobis tại trọng tâm
        let centroid_kp = track.centroid();
        let centroid_state = KeypointState::new(centroid_kp[0], centroid_kp[1], centroid_kp[2]);
        let maha = centroid_state.mahalanobis_distance(detection_centroid);

        // Chi phí nhúng: 1 - độ tương đồng cosine
        let embed_cost = 1.0 - cosine_similarity(&track.embedding, detection_embedding);

        self.config.position_weight * maha + self.config.embedding_weight * embed_cost
    }
}

impl Default for PoseTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// Độ tương đồng cosine giữa hai vector.
///
/// Trả về giá trị trong [-1.0, 1.0] trong đó 1.0 nghĩa là cùng hướng.
pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let n = a.len().min(b.len());
    if n == 0 {
        return 0.0;
    }

    let mut dot = 0.0_f32;
    let mut norm_a = 0.0_f32;
    let mut norm_b = 0.0_f32;

    for i in 0..n {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }

    let denom = (norm_a * norm_b).sqrt();
    if denom < 1e-12 {
        return 0.0;
    }

    (dot / denom).clamp(-1.0, 1.0)
}

/// Tư thế phát hiện từ mô hình, trước khi gán cho một theo dõi.
#[derive(Debug, Clone)]
pub struct PoseDetection {
    /// Vị trí mỗi điểm khớp [x, y, z, confidence] cho 17 điểm khớp.
    pub keypoints: [[f32; 4]; NUM_KEYPOINTS],
    /// Nhúng tái nhận dạng AETHER (128 chiều).
    pub embedding: Vec<f32>,
}

impl PoseDetection {
    /// Trích xuất mảng vị trí 3D từ các điểm khớp.
    pub fn positions(&self) -> [[f32; 3]; NUM_KEYPOINTS] {
        std::array::from_fn(|i| [self.keypoints[i][0], self.keypoints[i][1], self.keypoints[i][2]])
    }

    /// Tính trọng tâm của phát hiện.
    pub fn centroid(&self) -> [f32; 3] {
        let n = NUM_KEYPOINTS as f32;
        let mut c = [0.0_f32; 3];
        for kp in &self.keypoints {
            c[0] += kp[0];
            c[1] += kp[1];
            c[2] += kp[2];
        }
        c[0] /= n;
        c[1] /= n;
        c[2] /= n;
        c
    }

    /// Độ tin cậy trung bình trên tất cả điểm khớp.
    pub fn mean_confidence(&self) -> f32 {
        let sum: f32 = self.keypoints.iter().map(|kp| kp[3]).sum();
        sum / NUM_KEYPOINTS as f32
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn zero_positions() -> [[f32; 3]; NUM_KEYPOINTS] {
        [[0.0, 0.0, 0.0]; NUM_KEYPOINTS]
    }

    #[allow(dead_code)]
    fn offset_positions(offset: f32) -> [[f32; 3]; NUM_KEYPOINTS] {
        std::array::from_fn(|i| [offset + i as f32 * 0.1, offset, 0.0])
    }

    #[test]
    fn keypoint_state_creation() {
        let kp = KeypointState::new(1.0, 2.0, 3.0);
        assert_eq!(kp.position(), [1.0, 2.0, 3.0]);
        assert_eq!(kp.velocity(), [0.0, 0.0, 0.0]);
        assert_eq!(kp.confidence, 0.0);
    }

    #[test]
    fn keypoint_predict_moves_position() {
        let mut kp = KeypointState::new(0.0, 0.0, 0.0);
        kp.state[3] = 1.0; // vx = 1 m/s
        kp.predict(0.05, 0.3); // bước 50ms
        assert!((kp.state[0] - 0.05).abs() < 1e-5, "x phải xấp xỉ 0.05, nhận được {}", kp.state[0]);
    }

    #[test]
    fn keypoint_predict_increases_uncertainty() {
        let mut kp = KeypointState::new(0.0, 0.0, 0.0);
        let initial_var = kp.covariance[0];
        kp.predict(0.05, 0.3);
        assert!(kp.covariance[0] > initial_var);
    }

    #[test]
    fn keypoint_update_reduces_uncertainty() {
        let mut kp = KeypointState::new(0.0, 0.0, 0.0);
        kp.predict(0.05, 0.3);
        let post_predict_var = kp.covariance[0];
        kp.update(&[0.01, 0.0, 0.0], 0.08, 1.0);
        assert!(kp.covariance[0] < post_predict_var);
    }

    #[test]
    fn mahalanobis_zero_distance() {
        let kp = KeypointState::new(1.0, 2.0, 3.0);
        let d = kp.mahalanobis_distance(&[1.0, 2.0, 3.0]);
        assert!(d < 1e-3);
    }

    #[test]
    fn mahalanobis_positive_for_offset() {
        let kp = KeypointState::new(0.0, 0.0, 0.0);
        let d = kp.mahalanobis_distance(&[1.0, 0.0, 0.0]);
        assert!(d > 0.0);
    }

    #[test]
    fn lifecycle_transitions() {
        assert!(TrackLifecycleState::Tentative.is_alive());
        assert!(TrackLifecycleState::Active.is_alive());
        assert!(TrackLifecycleState::Lost.is_alive());
        assert!(!TrackLifecycleState::Terminated.is_alive());

        assert!(TrackLifecycleState::Tentative.accepts_updates());
        assert!(TrackLifecycleState::Active.accepts_updates());
        assert!(!TrackLifecycleState::Lost.accepts_updates());
        assert!(!TrackLifecycleState::Terminated.accepts_updates());

        assert!(!TrackLifecycleState::Tentative.is_lost());
        assert!(TrackLifecycleState::Lost.is_lost());
    }

    #[test]
    fn track_creation() {
        let positions = zero_positions();
        let track = PoseTrack::new(TrackId(0), &positions, 1000, 128);
        assert_eq!(track.id, TrackId(0));
        assert_eq!(track.lifecycle, TrackLifecycleState::Tentative);
        assert_eq!(track.embedding.len(), 128);
        assert_eq!(track.age, 0);
        assert_eq!(track.consecutive_hits, 1);
    }

    #[test]
    fn track_birth_gate() {
        let positions = zero_positions();
        let mut track = PoseTrack::new(TrackId(0), &positions, 0, 128);
        assert_eq!(track.lifecycle, TrackLifecycleState::Tentative);

        // Cập nhật đầu tiên: cần 2 hit nên thăng cấp
        track.update_keypoints(&positions, 0.08, 1.0, 100);
        assert_eq!(track.lifecycle, TrackLifecycleState::Active);
    }

    #[test]
    fn track_loss_gate() {
        let positions = zero_positions();
        let mut track = PoseTrack::new(TrackId(0), &positions, 0, 128);
        track.lifecycle = TrackLifecycleState::Active;

        // Dự đoán mà không cập nhật vượt quá loss_misses
        for _ in 0..6 {
            track.predict(0.05, 0.3);
        }
        // Đánh dấu mất dấu thủ công (thường do bộ theo dõi thực hiện)
        if track.time_since_update >= 5 {
            track.mark_lost();
        }
        assert_eq!(track.lifecycle, TrackLifecycleState::Lost);
    }

    #[test]
    fn track_centroid() {
        let positions: [[f32; 3]; NUM_KEYPOINTS] =
            std::array::from_fn(|_| [1.0, 2.0, 3.0]);
        let track = PoseTrack::new(TrackId(0), &positions, 0, 128);
        let c = track.centroid();
        assert!((c[0] - 1.0).abs() < 1e-5);
        assert!((c[1] - 2.0).abs() < 1e-5);
        assert!((c[2] - 3.0).abs() < 1e-5);
    }

    #[test]
    fn track_embedding_update() {
        let positions = zero_positions();
        let mut track = PoseTrack::new(TrackId(0), &positions, 0, 4);
        let new_embed = vec![1.0, 2.0, 3.0, 4.0];
        track.update_embedding(&new_embed, 0.5);
        // EMA: 0.5 * 0.0 + 0.5 * mới = mới / 2
        for i in 0..4 {
            assert!((track.embedding[i] - new_embed[i] * 0.5).abs() < 1e-5);
        }
    }

    #[test]
    fn tracker_create_and_find() {
        let mut tracker = PoseTracker::new();
        let positions = zero_positions();
        let id = tracker.create_track(&positions, 1000);
        assert!(tracker.find_track(id).is_some());
        assert_eq!(tracker.active_count(), 1);
    }

    #[test]
    fn tracker_predict_marks_lost() {
        let mut tracker = PoseTracker::with_config(TrackerConfig {
            loss_misses: 3,
            reid_window: 10,
            ..Default::default()
        });
        let positions = zero_positions();
        let id = tracker.create_track(&positions, 0);

        // Thăng cấp lên hoạt động
        if let Some(t) = tracker.find_track_mut(id) {
            t.lifecycle = TrackLifecycleState::Active;
        }

        // Dự đoán 4 lần mà không cập nhật
        for _ in 0..4 {
            tracker.predict_all(0.05);
        }

        let track = tracker.find_track(id).unwrap();
        assert_eq!(track.lifecycle, TrackLifecycleState::Lost);
    }

    #[test]
    fn tracker_prune_terminated() {
        let mut tracker = PoseTracker::new();
        let positions = zero_positions();
        let id = tracker.create_track(&positions, 0);
        if let Some(t) = tracker.find_track_mut(id) {
            t.terminate();
        }
        assert_eq!(tracker.all_tracks().len(), 1);
        tracker.prune_terminated();
        assert_eq!(tracker.all_tracks().len(), 0);
    }

    #[test]
    fn cosine_similarity_identical() {
        let a = vec![1.0, 2.0, 3.0];
        let b = vec![1.0, 2.0, 3.0];
        assert!((cosine_similarity(&a, &b) - 1.0).abs() < 1e-5);
    }

    #[test]
    fn cosine_similarity_orthogonal() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![0.0, 1.0, 0.0];
        assert!(cosine_similarity(&a, &b).abs() < 1e-5);
    }

    #[test]
    fn cosine_similarity_opposite() {
        let a = vec![1.0, 2.0, 3.0];
        let b = vec![-1.0, -2.0, -3.0];
        assert!((cosine_similarity(&a, &b) + 1.0).abs() < 1e-5);
    }

    #[test]
    fn cosine_similarity_empty() {
        assert_eq!(cosine_similarity(&[], &[]), 0.0);
    }

    #[test]
    fn pose_detection_centroid() {
        let kps: [[f32; 4]; NUM_KEYPOINTS] =
            std::array::from_fn(|_| [1.0, 2.0, 3.0, 0.9]);
        let det = PoseDetection {
            keypoints: kps,
            embedding: vec![0.0; 128],
        };
        let c = det.centroid();
        assert!((c[0] - 1.0).abs() < 1e-5);
    }

    #[test]
    fn pose_detection_mean_confidence() {
        let kps: [[f32; 4]; NUM_KEYPOINTS] =
            std::array::from_fn(|_| [0.0, 0.0, 0.0, 0.8]);
        let det = PoseDetection {
            keypoints: kps,
            embedding: vec![0.0; 128],
        };
        assert!((det.mean_confidence() - 0.8).abs() < 1e-5);
    }

    #[test]
    fn pose_detection_positions() {
        let kps: [[f32; 4]; NUM_KEYPOINTS] =
            std::array::from_fn(|i| [i as f32, 0.0, 0.0, 1.0]);
        let det = PoseDetection {
            keypoints: kps,
            embedding: vec![],
        };
        let pos = det.positions();
        assert_eq!(pos[0], [0.0, 0.0, 0.0]);
        assert_eq!(pos[5], [5.0, 0.0, 0.0]);
    }

    #[test]
    fn assignment_cost_computation() {
        let mut tracker = PoseTracker::new();
        let positions = zero_positions();
        let id = tracker.create_track(&positions, 0);

        let track = tracker.find_track(id).unwrap();
        let cost = tracker.assignment_cost(track, &[0.0, 0.0, 0.0], &vec![0.0; 128]);
        // Khoảng cách zero + chi phí nhúng zero phải gần 0
        // Nhưng chi phí nhúng = 1 - cosine_sim(zeros, zeros) = 1 - 0 = 1
        // Nên chi phí = 0.6 * 0 + 0.4 * 1 = 0.4
        assert!((cost - 0.4).abs() < 0.1, "Kỳ vọng ~0.4, nhận được {}", cost);
    }

    #[test]
    fn torso_jitter_rms_stationary() {
        let positions = zero_positions();
        let track = PoseTrack::new(TrackId(0), &positions, 0, 128);
        let jitter = track.torso_jitter_rms();
        assert!(jitter < 1e-5, "Theo dõi đứng yên phải có rung lắc gần zero");
    }

    #[test]
    fn default_tracker_config() {
        let cfg = TrackerConfig::default();
        assert!((cfg.process_noise - 0.3).abs() < f32::EPSILON);
        assert!((cfg.measurement_noise - 0.08).abs() < f32::EPSILON);
        assert!((cfg.mahalanobis_gate - 9.0).abs() < f32::EPSILON);
        assert_eq!(cfg.birth_hits, 2);
        assert_eq!(cfg.loss_misses, 5);
        assert_eq!(cfg.reid_window, 100);
        assert!((cfg.embedding_decay - 0.95).abs() < f32::EPSILON);
        assert_eq!(cfg.embedding_dim, 128);
        assert!((cfg.position_weight - 0.6).abs() < f32::EPSILON);
        assert!((cfg.embedding_weight - 0.4).abs() < f32::EPSILON);
    }

    #[test]
    fn track_terminate_prevents_lost() {
        let positions = zero_positions();
        let mut track = PoseTrack::new(TrackId(0), &positions, 0, 128);
        track.terminate();
        assert_eq!(track.lifecycle, TrackLifecycleState::Terminated);
        track.mark_lost(); // Không nên ghi đè Terminated
        assert_eq!(track.lifecycle, TrackLifecycleState::Terminated);
    }
}
