//! Liên tục danh tính chéo phòng.
//!
//! Duy trì sự liên tục danh tính giữa các phòng mà không cần quang học bằng
//! cách tạo dấu vân tay hồ sơ điện từ mỗi phòng, theo dõi
//! sự kiện ra/vào, và đối chiếu nhúng người qua ranh giới
//! chuyển đổi.
//!
//! # Thuật Toán
//! 1. Mỗi phòng được tạo dấu vân tay dưới dạng nhúng AETHER 128 chiều
//!    của hồ sơ CSI tĩnh
//! 2. Khi mất dõi gần ranh giới phòng, ghi lại sự kiện rời đi
//!    với nhúng hiện tại của người
//! 3. Khi có dõi mới xuất hiện trong phòng liền kề trong 60s, so sánh
//!    nhúng với các lần rời đi gần đây
//! 4. Nếu tương tự cosine > 0.80, liên kết các danh tính
//!
//! # Bất Biến
//! - Đối chiếu chéo phòng yêu cầu tương tự cosine > 0.80 VÀ khoảng thời gian < 60s
//! - Đồ thị chuyển đổi chỉ thêm (bản ghi kiểm toán bất biến)
//! - Không lưu trữ dữ liệu hình ảnh — chỉ nhúng 128 chiều và sự kiện cấu trúc
//! - Tối đa 100 phòng mỗi triển khai
//!
//! # Tham Khảo
//! - ADR-030 Tầng 5: Liên Tục Danh Tính Chéo Phòng

// ---------------------------------------------------------------------------
// Kiểu lỗi
// ---------------------------------------------------------------------------

/// Các lỗi từ thao tác chéo phòng.
#[derive(Debug, thiserror::Error)]
pub enum CrossRoomError {
    /// Vượt quá dung lượng phòng.
    #[error("Vượt quá số phòng tối đa: giới hạn là {max}")]
    MaxRoomsExceeded { max: usize },

    /// Không tìm thấy phòng.
    #[error("ID phòng không xác định: {0}")]
    UnknownRoom(u64),

    /// Chiều nhúng không khớp.
    #[error("Chiều nhúng không khớp: kỳ vọng {expected}, nhận được {got}")]
    EmbeddingDimensionMismatch { expected: usize, got: usize },

    /// Khoảng thời gian không hợp lệ cho đối chiếu.
    #[error("Khoảng thời gian {gap_s:.1}s vượt quá tối đa {max_s:.1}s")]
    TemporalGapExceeded { gap_s: f64, max_s: f64 },
}

// ---------------------------------------------------------------------------
// Cấu hình
// ---------------------------------------------------------------------------

/// Cấu hình cho theo dõi danh tính chéo phòng.
#[derive(Debug, Clone)]
pub struct CrossRoomConfig {
    /// Chiều nhúng (thường là 128).
    pub embedding_dim: usize,
    /// Tương tự cosine tối thiểu cho đối chiếu chéo phòng.
    pub min_similarity: f32,
    /// Khoảng thời gian tối đa (giây) cho đối chiếu chéo phòng.
    pub max_gap_s: f64,
    /// Số phòng tối đa trong triển khai.
    pub max_rooms: usize,
    /// Số sự kiện rời đi chờ tối đa được giữ lại.
    pub max_pending_exits: usize,
}

impl Default for CrossRoomConfig {
    fn default() -> Self {
        Self {
            embedding_dim: 128,
            min_similarity: 0.80,
            max_gap_s: 60.0,
            max_rooms: 100,
            max_pending_exits: 200,
        }
    }
}

// ---------------------------------------------------------------------------
// Kiểu miền
// ---------------------------------------------------------------------------

/// Dấu vân tay điện từ của phòng.
#[derive(Debug, Clone)]
pub struct RoomFingerprint {
    /// Định danh phòng.
    pub room_id: u64,
    /// Vector nhúng dấu vân tay.
    pub embedding: Vec<f32>,
    /// Dấu thời gian khi dấu vân tay được tính lần cuối (micro giây).
    pub computed_at_us: u64,
    /// Số node đóng góp vào dấu vân tay này.
    pub node_count: usize,
}

/// Sự kiện rời đi: một người rời khỏi phòng.
#[derive(Debug, Clone)]
pub struct ExitEvent {
    /// Nhúng người tại thời điểm rời đi.
    pub embedding: Vec<f32>,
    /// Phòng đã rời.
    pub room_id: u64,
    /// ID dõi người (cục bộ trong phòng).
    pub track_id: u64,
    /// Dấu thời gian rời đi (micro giây).
    pub timestamp_us: u64,
    /// Sự kiện rời đi này đã được đối chiếu với một lần vào hay chưa.
    pub matched: bool,
}

/// Sự kiện vào: một người xuất hiện trong phòng.
#[derive(Debug, Clone)]
pub struct EntryEvent {
    /// Nhúng người tại thời điểm vào.
    pub embedding: Vec<f32>,
    /// Phòng đã vào.
    pub room_id: u64,
    /// ID dõi người (cục bộ trong phòng).
    pub track_id: u64,
    /// Dấu thời gian vào (micro giây).
    pub timestamp_us: u64,
}

/// Bản ghi chuyển đổi chéo phòng (bất biến).
#[derive(Debug, Clone)]
pub struct TransitionEvent {
    /// Người đã chuyển đổi.
    pub person_id: u64,
    /// Phòng đã rời.
    pub from_room: u64,
    /// Phòng đã vào.
    pub to_room: u64,
    /// ID dõi lúc rời.
    pub exit_track_id: u64,
    /// ID dõi lúc vào.
    pub entry_track_id: u64,
    /// Tương tự cosine giữa nhúng rời và vào.
    pub similarity: f32,
    /// Khoảng thời gian giữa rời và vào (giây).
    pub gap_s: f64,
    /// Dấu thời gian của chuyển đổi (dấu thời gian vào).
    pub timestamp_us: u64,
}

/// Kết quả thử đối chiếu một lần vào với các lần rời đi chờ.
#[derive(Debug, Clone)]
pub struct MatchResult {
    /// Có tìm thấy đối chiếu hay không.
    pub matched: bool,
    /// Sự kiện chuyển đổi, nếu đã đối chiếu.
    pub transition: Option<TransitionEvent>,
    /// Số ứng viên đã kiểm tra.
    pub candidates_checked: usize,
    /// Tương tự tốt nhất tìm thấy (kể cả nếu dưới ngưỡng).
    pub best_similarity: f32,
}

// ---------------------------------------------------------------------------
// Bộ theo dõi danh tính chéo phòng
// ---------------------------------------------------------------------------

/// Bộ theo dõi liên tục danh tính chéo phòng.
///
/// Duy trì dấu vân tay phòng, sự kiện rời đi chờ, và đồ thị
/// chuyển đổi bất biến. Đối chiếu nhúng người giữa các phòng
/// sử dụng tương tự cosine với ràng buộc thời gian.
#[derive(Debug)]
pub struct CrossRoomTracker {
    config: CrossRoomConfig,
    /// Dấu vân tay phòng được đánh chỉ số theo room_id.
    rooms: Vec<RoomFingerprint>,
    /// Sự kiện rời đi chờ (chưa đối chiếu).
    pending_exits: Vec<ExitEvent>,
    /// Nhật ký chuyển đổi bất biến (chỉ thêm).
    transitions: Vec<TransitionEvent>,
    /// ID người tiếp theo cho gán danh tính chéo phòng.
    next_person_id: u64,
}

impl CrossRoomTracker {
    /// Tạo bộ theo dõi chéo phòng mới.
    pub fn new(config: CrossRoomConfig) -> Self {
        Self {
            config,
            rooms: Vec::new(),
            pending_exits: Vec::new(),
            transitions: Vec::new(),
            next_person_id: 1,
        }
    }

    /// Đăng ký dấu vân tay phòng.
    pub fn register_room(&mut self, fingerprint: RoomFingerprint) -> Result<(), CrossRoomError> {
        if self.rooms.len() >= self.config.max_rooms {
            return Err(CrossRoomError::MaxRoomsExceeded {
                max: self.config.max_rooms,
            });
        }
        if fingerprint.embedding.len() != self.config.embedding_dim {
            return Err(CrossRoomError::EmbeddingDimensionMismatch {
                expected: self.config.embedding_dim,
                got: fingerprint.embedding.len(),
            });
        }
        // Thay thế dấu vân tay hiện có nếu phòng đã được đăng ký
        if let Some(existing) = self
            .rooms
            .iter_mut()
            .find(|r| r.room_id == fingerprint.room_id)
        {
            *existing = fingerprint;
        } else {
            self.rooms.push(fingerprint);
        }
        Ok(())
    }

    /// Ghi lại một người rời khỏi phòng.
    pub fn record_exit(&mut self, event: ExitEvent) -> Result<(), CrossRoomError> {
        if event.embedding.len() != self.config.embedding_dim {
            return Err(CrossRoomError::EmbeddingDimensionMismatch {
                expected: self.config.embedding_dim,
                got: event.embedding.len(),
            });
        }
        // Loại bỏ cũ nhất nếu đạt dung lượng
        if self.pending_exits.len() >= self.config.max_pending_exits {
            self.pending_exits.remove(0);
        }
        self.pending_exits.push(event);
        Ok(())
    }

    /// Thử đối chiếu sự kiện vào với các lần rời đi chờ.
    ///
    /// Nếu tìm thấy đối chiếu, tạo TransitionEvent và đánh dấu
    /// lần rời đi là đã đối chiếu. Trả về kết quả đối chiếu.
    pub fn match_entry(&mut self, entry: &EntryEvent) -> Result<MatchResult, CrossRoomError> {
        if entry.embedding.len() != self.config.embedding_dim {
            return Err(CrossRoomError::EmbeddingDimensionMismatch {
                expected: self.config.embedding_dim,
                got: entry.embedding.len(),
            });
        }

        let mut best_idx: Option<usize> = None;
        let mut best_sim: f32 = -1.0;
        let mut candidates_checked = 0;

        for (idx, exit) in self.pending_exits.iter().enumerate() {
            if exit.matched || exit.room_id == entry.room_id {
                continue;
            }

            // Ràng buộc thời gian
            let gap_us = entry.timestamp_us.saturating_sub(exit.timestamp_us);
            let gap_s = gap_us as f64 / 1_000_000.0;
            if gap_s > self.config.max_gap_s {
                continue;
            }

            candidates_checked += 1;

            let sim = cosine_similarity_f32(&exit.embedding, &entry.embedding);
            if sim > best_sim {
                best_sim = sim;
                if sim >= self.config.min_similarity {
                    best_idx = Some(idx);
                }
            }
        }

        if let Some(idx) = best_idx {
            let exit = &self.pending_exits[idx];
            let gap_us = entry.timestamp_us.saturating_sub(exit.timestamp_us);
            let gap_s = gap_us as f64 / 1_000_000.0;

            let person_id = self.next_person_id;
            self.next_person_id += 1;

            let transition = TransitionEvent {
                person_id,
                from_room: exit.room_id,
                to_room: entry.room_id,
                exit_track_id: exit.track_id,
                entry_track_id: entry.track_id,
                similarity: best_sim,
                gap_s,
                timestamp_us: entry.timestamp_us,
            };

            // Đánh dấu lần rời đi là đã đối chiếu
            self.pending_exits[idx].matched = true;

            // Thêm vào nhật ký chuyển đổi bất biến
            self.transitions.push(transition.clone());

            Ok(MatchResult {
                matched: true,
                transition: Some(transition),
                candidates_checked,
                best_similarity: best_sim,
            })
        } else {
            Ok(MatchResult {
                matched: false,
                transition: None,
                candidates_checked,
                best_similarity: if best_sim >= 0.0 { best_sim } else { 0.0 },
            })
        }
    }

    /// Hết hạn các lần rời đi chờ cũ vượt quá thời gian khoảng cách tối đa.
    pub fn expire_exits(&mut self, current_us: u64) {
        let max_gap_us = (self.config.max_gap_s * 1_000_000.0) as u64;
        self.pending_exits.retain(|exit| {
            !exit.matched && current_us.saturating_sub(exit.timestamp_us) <= max_gap_us
        });
    }

    /// Số phòng đã đăng ký.
    pub fn room_count(&self) -> usize {
        self.rooms.len()
    }

    /// Số sự kiện rời đi chờ (chưa đối chiếu).
    pub fn pending_exit_count(&self) -> usize {
        self.pending_exits.iter().filter(|e| !e.matched).count()
    }

    /// Số chuyển đổi đã ghi lại.
    pub fn transition_count(&self) -> usize {
        self.transitions.len()
    }

    /// Lấy tất cả chuyển đổi cho một người.
    pub fn transitions_for_person(&self, person_id: u64) -> Vec<&TransitionEvent> {
        self.transitions
            .iter()
            .filter(|t| t.person_id == person_id)
            .collect()
    }

    /// Lấy tất cả chuyển đổi giữa hai phòng.
    pub fn transitions_between(&self, from_room: u64, to_room: u64) -> Vec<&TransitionEvent> {
        self.transitions
            .iter()
            .filter(|t| t.from_room == from_room && t.to_room == to_room)
            .collect()
    }

    /// Lấy dấu vân tay phòng cho ID phòng.
    pub fn room_fingerprint(&self, room_id: u64) -> Option<&RoomFingerprint> {
        self.rooms.iter().find(|r| r.room_id == room_id)
    }
}

/// Tương tự cosine giữa hai vector f32.
fn cosine_similarity_f32(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    let denom = norm_a * norm_b;
    if denom < 1e-9 {
        0.0
    } else {
        dot / denom
    }
}

// ---------------------------------------------------------------------------
// Kiểm thử
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn small_config() -> CrossRoomConfig {
        CrossRoomConfig {
            embedding_dim: 4,
            min_similarity: 0.80,
            max_gap_s: 60.0,
            max_rooms: 10,
            max_pending_exits: 50,
        }
    }

    fn make_fingerprint(room_id: u64, v: [f32; 4]) -> RoomFingerprint {
        RoomFingerprint {
            room_id,
            embedding: v.to_vec(),
            computed_at_us: 0,
            node_count: 4,
        }
    }

    fn make_exit(room_id: u64, track_id: u64, emb: [f32; 4], ts: u64) -> ExitEvent {
        ExitEvent {
            embedding: emb.to_vec(),
            room_id,
            track_id,
            timestamp_us: ts,
            matched: false,
        }
    }

    fn make_entry(room_id: u64, track_id: u64, emb: [f32; 4], ts: u64) -> EntryEvent {
        EntryEvent {
            embedding: emb.to_vec(),
            room_id,
            track_id,
            timestamp_us: ts,
        }
    }

    #[test]
    fn test_tracker_creation() {
        let tracker = CrossRoomTracker::new(small_config());
        assert_eq!(tracker.room_count(), 0);
        assert_eq!(tracker.pending_exit_count(), 0);
        assert_eq!(tracker.transition_count(), 0);
    }

    #[test]
    fn test_register_room() {
        let mut tracker = CrossRoomTracker::new(small_config());
        tracker
            .register_room(make_fingerprint(1, [1.0, 0.0, 0.0, 0.0]))
            .unwrap();
        assert_eq!(tracker.room_count(), 1);
        assert!(tracker.room_fingerprint(1).is_some());
    }

    #[test]
    fn test_max_rooms_exceeded() {
        let config = CrossRoomConfig {
            max_rooms: 2,
            ..small_config()
        };
        let mut tracker = CrossRoomTracker::new(config);
        tracker
            .register_room(make_fingerprint(1, [1.0, 0.0, 0.0, 0.0]))
            .unwrap();
        tracker
            .register_room(make_fingerprint(2, [0.0, 1.0, 0.0, 0.0]))
            .unwrap();
        assert!(matches!(
            tracker.register_room(make_fingerprint(3, [0.0, 0.0, 1.0, 0.0])),
            Err(CrossRoomError::MaxRoomsExceeded { .. })
        ));
    }

    #[test]
    fn test_successful_cross_room_match() {
        let mut tracker = CrossRoomTracker::new(small_config());

        // Người rời phòng 1
        let exit_emb = [0.9, 0.1, 0.0, 0.0];
        tracker
            .record_exit(make_exit(1, 100, exit_emb, 1_000_000))
            .unwrap();

        // Cùng người vào phòng 2 (nhúng tương tự, trong 60s)
        let entry_emb = [0.88, 0.12, 0.01, 0.0];
        let entry = make_entry(2, 200, entry_emb, 5_000_000);
        let result = tracker.match_entry(&entry).unwrap();

        assert!(result.matched);
        let t = result.transition.unwrap();
        assert_eq!(t.from_room, 1);
        assert_eq!(t.to_room, 2);
        assert!(t.similarity >= 0.80);
        assert!(t.gap_s < 60.0);
    }

    #[test]
    fn test_no_match_different_person() {
        let mut tracker = CrossRoomTracker::new(small_config());

        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 1_000_000))
            .unwrap();

        // Nhúng rất khác biệt
        let entry = make_entry(2, 200, [0.0, 0.0, 0.0, 1.0], 5_000_000);
        let result = tracker.match_entry(&entry).unwrap();

        assert!(!result.matched);
        assert!(result.transition.is_none());
    }

    #[test]
    fn test_no_match_temporal_gap_exceeded() {
        let mut tracker = CrossRoomTracker::new(small_config());

        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 0))
            .unwrap();

        // Cùng nhúng nhưng 120 giây sau
        let entry = make_entry(2, 200, [1.0, 0.0, 0.0, 0.0], 120_000_000);
        let result = tracker.match_entry(&entry).unwrap();

        assert!(!result.matched, "Không nên đối chiếu với khoảng > 60s");
    }

    #[test]
    fn test_no_match_same_room() {
        let mut tracker = CrossRoomTracker::new(small_config());

        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 1_000_000))
            .unwrap();

        // Vào cùng phòng không nên đối chiếu
        let entry = make_entry(1, 200, [1.0, 0.0, 0.0, 0.0], 2_000_000);
        let result = tracker.match_entry(&entry).unwrap();

        assert!(!result.matched, "Vào cùng phòng không nên đối chiếu");
    }

    #[test]
    fn test_expire_exits() {
        let mut tracker = CrossRoomTracker::new(small_config());

        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 0))
            .unwrap();
        tracker
            .record_exit(make_exit(2, 200, [0.0, 1.0, 0.0, 0.0], 50_000_000))
            .unwrap();

        assert_eq!(tracker.pending_exit_count(), 2);

        // Hết hạn ở 70s — lần rời đi đầu (tại 0) phải bị hết hạn
        tracker.expire_exits(70_000_000);
        assert_eq!(tracker.pending_exit_count(), 1);
    }

    #[test]
    fn test_transition_log_immutable() {
        let mut tracker = CrossRoomTracker::new(small_config());

        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 1_000_000))
            .unwrap();

        let entry = make_entry(2, 200, [0.98, 0.02, 0.0, 0.0], 2_000_000);
        tracker.match_entry(&entry).unwrap();

        assert_eq!(tracker.transition_count(), 1);

        // Thêm chuyển đổi phải được nối thêm
        tracker
            .record_exit(make_exit(2, 300, [0.0, 1.0, 0.0, 0.0], 3_000_000))
            .unwrap();
        let entry2 = make_entry(3, 400, [0.01, 0.99, 0.0, 0.0], 4_000_000);
        tracker.match_entry(&entry2).unwrap();

        assert_eq!(tracker.transition_count(), 2);
    }

    #[test]
    fn test_transitions_between_rooms() {
        let mut tracker = CrossRoomTracker::new(small_config());

        // Phòng 1 → Phòng 2
        tracker
            .record_exit(make_exit(1, 100, [1.0, 0.0, 0.0, 0.0], 1_000_000))
            .unwrap();
        let entry = make_entry(2, 200, [0.98, 0.02, 0.0, 0.0], 2_000_000);
        tracker.match_entry(&entry).unwrap();

        // Phòng 2 → Phòng 3
        tracker
            .record_exit(make_exit(2, 300, [0.0, 1.0, 0.0, 0.0], 3_000_000))
            .unwrap();
        let entry2 = make_entry(3, 400, [0.01, 0.99, 0.0, 0.0], 4_000_000);
        tracker.match_entry(&entry2).unwrap();

        let r1_r2 = tracker.transitions_between(1, 2);
        assert_eq!(r1_r2.len(), 1);

        let r2_r3 = tracker.transitions_between(2, 3);
        assert_eq!(r2_r3.len(), 1);

        let r1_r3 = tracker.transitions_between(1, 3);
        assert_eq!(r1_r3.len(), 0);
    }

    #[test]
    fn test_embedding_dimension_mismatch() {
        let mut tracker = CrossRoomTracker::new(small_config());

        let bad_exit = ExitEvent {
            embedding: vec![1.0, 0.0], // chiều sai
            room_id: 1,
            track_id: 1,
            timestamp_us: 0,
            matched: false,
        };
        assert!(matches!(
            tracker.record_exit(bad_exit),
            Err(CrossRoomError::EmbeddingDimensionMismatch { .. })
        ));
    }

    #[test]
    fn test_cosine_similarity_identical() {
        let a = vec![1.0_f32, 2.0, 3.0, 4.0];
        let sim = cosine_similarity_f32(&a, &a);
        assert!((sim - 1.0).abs() < 1e-5);
    }

    #[test]
    fn test_cosine_similarity_orthogonal() {
        let a = vec![1.0_f32, 0.0, 0.0, 0.0];
        let b = vec![0.0_f32, 1.0, 0.0, 0.0];
        let sim = cosine_similarity_f32(&a, &b);
        assert!(sim.abs() < 1e-5);
    }
}
