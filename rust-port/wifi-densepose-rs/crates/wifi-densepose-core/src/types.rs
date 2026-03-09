//! Các kiểu dữ liệu cốt lõi cho hệ thống WiFi-DensePose.
//!
//! Module này định nghĩa các cấu trúc dữ liệu nền tảng được sử dụng xuyên suốt
//! hệ sinh thái WiFi-DensePose để biểu diễn dữ liệu CSI, tín hiệu đã xử lý,
//! và kết quả ước lượng tư thế.
//!
//! # Phân Loại Kiểu
//!
//! - **Kiểu CSI**: [`CsiFrame`], [`CsiMetadata`], [`AntennaConfig`]
//! - **Kiểu Tín Hiệu**: [`ProcessedSignal`], [`SignalFeatures`], [`FrequencyBand`]
//! - **Kiểu Tư Thế**: [`PoseEstimate`], [`PersonPose`], [`Keypoint`], [`KeypointType`]
//! - **Kiểu Dùng Chung**: [`Confidence`], [`Timestamp`], [`FrameId`], [`DeviceId`]

use chrono::{DateTime, Utc};
use ndarray::{Array1, Array2, Array3};
use num_complex::Complex64;
use uuid::Uuid;

#[cfg(feature = "serde")]
use serde::{Deserialize, Serialize};

use crate::error::{CoreError, CoreResult};
use crate::{DEFAULT_CONFIDENCE_THRESHOLD, MAX_KEYPOINTS};

// =============================================================================
// Kiểu Dùng Chung
// =============================================================================

/// Định danh duy nhất cho một khung CSI.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct FrameId(Uuid);

impl FrameId {
    /// Tạo một ID khung duy nhất mới.
    #[must_use]
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    /// Tạo ID khung từ một UUID có sẵn.
    #[must_use]
    pub fn from_uuid(uuid: Uuid) -> Self {
        Self(uuid)
    }

    /// Trả về UUID bên trong.
    #[must_use]
    pub fn as_uuid(&self) -> &Uuid {
        &self.0
    }
}

impl Default for FrameId {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for FrameId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Định danh duy nhất cho một thiết bị `WiFi`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct DeviceId(String);

impl DeviceId {
    /// Tạo ID thiết bị mới từ chuỗi.
    #[must_use]
    pub fn new(id: impl Into<String>) -> Self {
        Self(id.into())
    }

    /// Trả về ID thiết bị dưới dạng slice chuỗi.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for DeviceId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Dấu thời gian độ chính xác cao cho dữ liệu CSI.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct Timestamp {
    /// Số giây kể từ Unix epoch
    pub seconds: i64,
    /// Số nano giây trong giây
    pub nanos: u32,
}

impl Timestamp {
    /// Tạo dấu thời gian mới từ giây và nano giây.
    #[must_use]
    pub fn new(seconds: i64, nanos: u32) -> Self {
        Self { seconds, nanos }
    }

    /// Tạo dấu thời gian từ thời điểm hiện tại.
    #[must_use]
    pub fn now() -> Self {
        let now = Utc::now();
        Self {
            seconds: now.timestamp(),
            nanos: now.timestamp_subsec_nanos(),
        }
    }

    /// Tạo dấu thời gian từ `DateTime<Utc>`.
    #[must_use]
    pub fn from_datetime(dt: DateTime<Utc>) -> Self {
        Self {
            seconds: dt.timestamp(),
            nanos: dt.timestamp_subsec_nanos(),
        }
    }

    /// Chuyển đổi sang `DateTime<Utc>`.
    #[must_use]
    pub fn to_datetime(&self) -> Option<DateTime<Utc>> {
        DateTime::from_timestamp(self.seconds, self.nanos)
    }

    /// Trả về dấu thời gian dưới dạng tổng nano giây kể từ epoch.
    #[must_use]
    pub fn as_nanos(&self) -> i128 {
        i128::from(self.seconds) * 1_000_000_000 + i128::from(self.nanos)
    }

    /// Trả về khoảng thời gian giữa hai dấu thời gian tính bằng giây.
    #[must_use]
    pub fn duration_since(&self, earlier: &Self) -> f64 {
        let diff_nanos = self.as_nanos() - earlier.as_nanos();
        diff_nanos as f64 / 1_000_000_000.0
    }
}

impl Default for Timestamp {
    fn default() -> Self {
        Self::now()
    }
}

/// Điểm số độ tin cậy trong phạm vi [0.0, 1.0].
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct Confidence(f32);

impl Confidence {
    /// Tạo giá trị độ tin cậy mới.
    ///
    /// # Lỗi
    ///
    /// Trả về lỗi nếu giá trị không nằm trong phạm vi [0.0, 1.0].
    pub fn new(value: f32) -> CoreResult<Self> {
        if !(0.0..=1.0).contains(&value) {
            return Err(CoreError::validation(format!(
                "Độ tin cậy phải nằm trong [0.0, 1.0], nhận được {value}"
            )));
        }
        Ok(Self(value))
    }

    /// Tạo giá trị độ tin cậy không cần xác thực (dùng nội bộ).
    ///
    /// Trả về giá trị độ tin cậy thô.
    #[must_use]
    pub fn value(&self) -> f32 {
        self.0
    }

    /// Trả về `true` nếu độ tin cậy vượt ngưỡng mặc định.
    #[must_use]
    pub fn is_high(&self) -> bool {
        self.0 >= DEFAULT_CONFIDENCE_THRESHOLD
    }

    /// Trả về `true` nếu độ tin cậy vượt ngưỡng cho trước.
    #[must_use]
    pub fn exceeds(&self, threshold: f32) -> bool {
        self.0 >= threshold
    }

    /// Độ tin cậy tối đa (1.0).
    pub const MAX: Self = Self(1.0);

    /// Độ tin cậy tối thiểu (0.0).
    pub const MIN: Self = Self(0.0);
}

impl Default for Confidence {
    fn default() -> Self {
        Self(0.0)
    }
}

// =============================================================================
// Kiểu CSI
// =============================================================================

/// Băng tần `WiFi`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub enum FrequencyBand {
    /// Băng 2.4 GHz (802.11b/g/n)
    Band2_4GHz,
    /// Băng 5 GHz (802.11a/n/ac)
    Band5GHz,
    /// Băng 6 GHz (802.11ax/WiFi 6E)
    Band6GHz,
}

impl FrequencyBand {
    /// Trả về tần số trung tâm tính bằng MHz.
    #[must_use]
    pub fn center_frequency_mhz(&self) -> u32 {
        match self {
            Self::Band2_4GHz => 2437,
            Self::Band5GHz => 5180,
            Self::Band6GHz => 5975,
        }
    }

    /// Trả về số sóng mang con điển hình cho băng tần này.
    #[must_use]
    pub fn typical_subcarriers(&self) -> usize {
        match self {
            Self::Band2_4GHz => 56,
            Self::Band5GHz => 114,
            Self::Band6GHz => 234,
        }
    }
}

/// Cấu hình ăng-ten cho hệ thống MIMO.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct AntennaConfig {
    /// Số ăng-ten phát
    pub tx_antennas: u8,
    /// Số ăng-ten thu
    pub rx_antennas: u8,
    /// Khoảng cách ăng-ten tính bằng mili-mét (nếu biết)
    pub spacing_mm: Option<f32>,
}

impl AntennaConfig {
    /// Tạo cấu hình ăng-ten mới.
    #[must_use]
    pub fn new(tx_antennas: u8, rx_antennas: u8) -> Self {
        Self {
            tx_antennas,
            rx_antennas,
            spacing_mm: None,
        }
    }

    /// Đặt khoảng cách ăng-ten.
    #[must_use]
    pub fn with_spacing(mut self, spacing_mm: f32) -> Self {
        self.spacing_mm = Some(spacing_mm);
        self
    }

    /// Trả về tổng số luồng không gian.
    #[must_use]
    pub fn spatial_streams(&self) -> usize {
        usize::from(self.tx_antennas) * usize::from(self.rx_antennas)
    }

    /// Cấu hình SIMO 1x3 phổ biến.
    pub const SIMO_1X3: Self = Self {
        tx_antennas: 1,
        rx_antennas: 3,
        spacing_mm: None,
    };

    /// Cấu hình MIMO 2x2 phổ biến.
    pub const MIMO_2X2: Self = Self {
        tx_antennas: 2,
        rx_antennas: 2,
        spacing_mm: None,
    };

    /// Cấu hình MIMO 3x3 phổ biến.
    pub const MIMO_3X3: Self = Self {
        tx_antennas: 3,
        rx_antennas: 3,
        spacing_mm: None,
    };
}

impl Default for AntennaConfig {
    fn default() -> Self {
        Self::SIMO_1X3
    }
}

/// Siêu dữ liệu liên kết với một khung CSI.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct CsiMetadata {
    /// Dấu thời gian khi khung được thu thập
    pub timestamp: Timestamp,
    /// Định danh thiết bị nguồn
    pub device_id: DeviceId,
    /// Băng tần
    pub frequency_band: FrequencyBand,
    /// Số kênh
    pub channel: u8,
    /// Băng thông tính bằng MHz
    pub bandwidth_mhz: u16,
    /// Cấu hình ăng-ten
    pub antenna_config: AntennaConfig,
    /// Chỉ số cường độ tín hiệu thu (dBm)
    pub rssi_dbm: i8,
    /// Nền nhiễu (dBm)
    pub noise_floor_dbm: i8,
    /// Số thứ tự khung
    pub sequence_number: u32,
}

impl CsiMetadata {
    /// Tạo siêu dữ liệu CSI mới với các trường bắt buộc.
    #[must_use]
    pub fn new(device_id: DeviceId, frequency_band: FrequencyBand, channel: u8) -> Self {
        Self {
            timestamp: Timestamp::now(),
            device_id,
            frequency_band,
            channel,
            bandwidth_mhz: 20,
            antenna_config: AntennaConfig::default(),
            rssi_dbm: -50,
            noise_floor_dbm: -90,
            sequence_number: 0,
        }
    }

    /// Trả về Tỷ số Tín hiệu trên Nhiễu tính bằng dB.
    #[must_use]
    pub fn snr_db(&self) -> f64 {
        f64::from(self.rssi_dbm) - f64::from(self.noise_floor_dbm)
    }
}

/// Một khung dữ liệu Thông tin Trạng thái Kênh (CSI) đơn lẻ.
///
/// CSI thu thập đáp ứng tần số của kênh không dây, mã hoá
/// thông tin về biên độ và pha tín hiệu trên nhiều sóng mang con
/// và cặp ăng-ten.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct CsiFrame {
    /// Định danh khung duy nhất
    pub id: FrameId,
    /// Siêu dữ liệu khung
    pub metadata: CsiMetadata,
    /// Dữ liệu CSI phức: [luồng_không_gian, sóng_mang_con]
    #[cfg_attr(feature = "serde", serde(skip))]
    pub data: Array2<Complex64>,
    /// Dữ liệu biên độ (độ lớn của giá trị phức)
    #[cfg_attr(feature = "serde", serde(skip))]
    pub amplitude: Array2<f64>,
    /// Dữ liệu pha (góc của giá trị phức, tính bằng radian)
    #[cfg_attr(feature = "serde", serde(skip))]
    pub phase: Array2<f64>,
}

impl CsiFrame {
    /// Tạo khung CSI mới từ dữ liệu phức thô.
    pub fn new(metadata: CsiMetadata, data: Array2<Complex64>) -> Self {
        let amplitude = data.mapv(num_complex::Complex::norm);
        let phase = data.mapv(num_complex::Complex::arg);

        Self {
            id: FrameId::new(),
            metadata,
            data,
            amplitude,
            phase,
        }
    }

    /// Trả về số luồng không gian (cặp ăng-ten).
    #[must_use]
    pub fn num_spatial_streams(&self) -> usize {
        self.data.nrows()
    }

    /// Trả về số sóng mang con.
    #[must_use]
    pub fn num_subcarriers(&self) -> usize {
        self.data.ncols()
    }

    /// Trả về biên độ trung bình trên tất cả sóng mang con và luồng.
    #[must_use]
    pub fn mean_amplitude(&self) -> f64 {
        self.amplitude.mean().unwrap_or(0.0)
    }

    /// Trả về phương sai biên độ, hữu ích cho phát hiện chuyển động.
    #[must_use]
    pub fn amplitude_variance(&self) -> f64 {
        self.amplitude.var(0.0)
    }
}

// =============================================================================
// Kiểu Tín Hiệu
// =============================================================================

/// Các đặc trưng trích xuất từ tín hiệu CSI đã xử lý.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct SignalFeatures {
    /// Ước lượng vận tốc Doppler (m/s)
    pub doppler_velocities: Vec<f64>,
    /// Ước lượng thời gian bay (ns)
    pub time_of_flight: Vec<f64>,
    /// Ước lượng góc đến (radian)
    pub angle_of_arrival: Vec<f64>,
    /// Độ tin cậy phát hiện chuyển động
    pub motion_confidence: Confidence,
    /// Độ tin cậy phát hiện sự hiện diện
    pub presence_confidence: Confidence,
    /// Số lượng cơ thể phát hiện được
    pub body_count: u8,
}

impl Default for SignalFeatures {
    fn default() -> Self {
        Self {
            doppler_velocities: Vec::new(),
            time_of_flight: Vec::new(),
            angle_of_arrival: Vec::new(),
            motion_confidence: Confidence::MIN,
            presence_confidence: Confidence::MIN,
            body_count: 0,
        }
    }
}

/// Tín hiệu CSI đã xử lý sẵn sàng cho suy luận mạng nơ-ron.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct ProcessedSignal {
    /// ID các khung nguồn đã đóng góp vào tín hiệu đã xử lý này
    pub source_frame_ids: Vec<FrameId>,
    /// Dấu thời gian của khung nguồn gần nhất
    pub timestamp: Timestamp,
    /// Tensor biên độ đã xử lý: [bước_thời_gian, luồng_không_gian, sóng_mang_con]
    #[cfg_attr(feature = "serde", serde(skip))]
    pub amplitude_tensor: Array3<f32>,
    /// Tensor pha đã xử lý: [bước_thời_gian, luồng_không_gian, sóng_mang_con]
    #[cfg_attr(feature = "serde", serde(skip))]
    pub phase_tensor: Array3<f32>,
    /// Các đặc trưng tín hiệu đã trích xuất
    pub features: SignalFeatures,
    /// Thiết bị đã thu thập dữ liệu này
    pub device_id: DeviceId,
}

impl ProcessedSignal {
    /// Tạo tín hiệu đã xử lý mới.
    #[must_use]
    pub fn new(
        source_frame_ids: Vec<FrameId>,
        timestamp: Timestamp,
        amplitude_tensor: Array3<f32>,
        phase_tensor: Array3<f32>,
        device_id: DeviceId,
    ) -> Self {
        Self {
            source_frame_ids,
            timestamp,
            amplitude_tensor,
            phase_tensor,
            features: SignalFeatures::default(),
            device_id,
        }
    }

    /// Trả về kích thước của tensor tín hiệu [thời_gian, luồng, sóng_mang_con].
    #[must_use]
    pub fn shape(&self) -> (usize, usize, usize) {
        let shape = self.amplitude_tensor.shape();
        (shape[0], shape[1], shape[2])
    }

    /// Trả về tổng số bước thời gian trong tín hiệu.
    #[must_use]
    pub fn num_time_steps(&self) -> usize {
        self.amplitude_tensor.shape()[0]
    }
}

// =============================================================================
// Kiểu Tư Thế
// =============================================================================

/// Các loại điểm khớp cơ thể theo định dạng COCO.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
#[repr(u8)]
pub enum KeypointType {
    /// Mũi
    Nose = 0,
    /// Mắt trái
    LeftEye = 1,
    /// Mắt phải
    RightEye = 2,
    /// Tai trái
    LeftEar = 3,
    /// Tai phải
    RightEar = 4,
    /// Vai trái
    LeftShoulder = 5,
    /// Vai phải
    RightShoulder = 6,
    /// Khuỷu tay trái
    LeftElbow = 7,
    /// Khuỷu tay phải
    RightElbow = 8,
    /// Cổ tay trái
    LeftWrist = 9,
    /// Cổ tay phải
    RightWrist = 10,
    /// Hông trái
    LeftHip = 11,
    /// Hông phải
    RightHip = 12,
    /// Đầu gối trái
    LeftKnee = 13,
    /// Đầu gối phải
    RightKnee = 14,
    /// Mắt cá chân trái
    LeftAnkle = 15,
    /// Mắt cá chân phải
    RightAnkle = 16,
}

impl KeypointType {
    /// Trả về tất cả các loại điểm khớp theo thứ tự.
    #[must_use]
    pub fn all() -> &'static [Self; MAX_KEYPOINTS] {
        &[
            Self::Nose,
            Self::LeftEye,
            Self::RightEye,
            Self::LeftEar,
            Self::RightEar,
            Self::LeftShoulder,
            Self::RightShoulder,
            Self::LeftElbow,
            Self::RightElbow,
            Self::LeftWrist,
            Self::RightWrist,
            Self::LeftHip,
            Self::RightHip,
            Self::LeftKnee,
            Self::RightKnee,
            Self::LeftAnkle,
            Self::RightAnkle,
        ]
    }

    /// Trả về tên điểm khớp dưới dạng chuỗi.
    #[must_use]
    pub fn name(&self) -> &'static str {
        match self {
            Self::Nose => "nose",
            Self::LeftEye => "left_eye",
            Self::RightEye => "right_eye",
            Self::LeftEar => "left_ear",
            Self::RightEar => "right_ear",
            Self::LeftShoulder => "left_shoulder",
            Self::RightShoulder => "right_shoulder",
            Self::LeftElbow => "left_elbow",
            Self::RightElbow => "right_elbow",
            Self::LeftWrist => "left_wrist",
            Self::RightWrist => "right_wrist",
            Self::LeftHip => "left_hip",
            Self::RightHip => "right_hip",
            Self::LeftKnee => "left_knee",
            Self::RightKnee => "right_knee",
            Self::LeftAnkle => "left_ankle",
            Self::RightAnkle => "right_ankle",
        }
    }

    /// Trả về `true` nếu đây là điểm khớp trên mặt.
    #[must_use]
    pub fn is_face(&self) -> bool {
        matches!(
            self,
            Self::Nose | Self::LeftEye | Self::RightEye | Self::LeftEar | Self::RightEar
        )
    }

    /// Trả về `true` nếu đây là điểm khớp phần thân trên.
    #[must_use]
    pub fn is_upper_body(&self) -> bool {
        matches!(
            self,
            Self::LeftShoulder
                | Self::RightShoulder
                | Self::LeftElbow
                | Self::RightElbow
                | Self::LeftWrist
                | Self::RightWrist
        )
    }

    /// Trả về `true` nếu đây là điểm khớp phần thân dưới.
    #[must_use]
    pub fn is_lower_body(&self) -> bool {
        matches!(
            self,
            Self::LeftHip
                | Self::RightHip
                | Self::LeftKnee
                | Self::RightKnee
                | Self::LeftAnkle
                | Self::RightAnkle
        )
    }
}

impl TryFrom<u8> for KeypointType {
    type Error = CoreError;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Nose),
            1 => Ok(Self::LeftEye),
            2 => Ok(Self::RightEye),
            3 => Ok(Self::LeftEar),
            4 => Ok(Self::RightEar),
            5 => Ok(Self::LeftShoulder),
            6 => Ok(Self::RightShoulder),
            7 => Ok(Self::LeftElbow),
            8 => Ok(Self::RightElbow),
            9 => Ok(Self::LeftWrist),
            10 => Ok(Self::RightWrist),
            11 => Ok(Self::LeftHip),
            12 => Ok(Self::RightHip),
            13 => Ok(Self::LeftKnee),
            14 => Ok(Self::RightKnee),
            15 => Ok(Self::LeftAnkle),
            16 => Ok(Self::RightAnkle),
            _ => Err(CoreError::validation(format!(
                "Loại điểm khớp không hợp lệ: {value}"
            ))),
        }
    }
}

/// Một điểm khớp cơ thể đơn lẻ với vị trí và độ tin cậy.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct Keypoint {
    /// Loại điểm khớp
    pub keypoint_type: KeypointType,
    /// Toạ độ X (chuẩn hoá 0.0-1.0 hoặc pixel tuyệt đối)
    pub x: f32,
    /// Toạ độ Y (chuẩn hoá 0.0-1.0 hoặc pixel tuyệt đối)
    pub y: f32,
    /// Toạ độ Z (độ sâu, nếu có)
    pub z: Option<f32>,
    /// Độ tin cậy phát hiện
    pub confidence: Confidence,
}

impl Keypoint {
    /// Tạo điểm khớp 2D mới.
    #[must_use]
    pub fn new(keypoint_type: KeypointType, x: f32, y: f32, confidence: Confidence) -> Self {
        Self {
            keypoint_type,
            x,
            y,
            z: None,
            confidence,
        }
    }

    /// Tạo điểm khớp 3D mới.
    #[must_use]
    pub fn new_3d(
        keypoint_type: KeypointType,
        x: f32,
        y: f32,
        z: f32,
        confidence: Confidence,
    ) -> Self {
        Self {
            keypoint_type,
            x,
            y,
            z: Some(z),
            confidence,
        }
    }

    /// Trả về `true` nếu điểm khớp này nên được coi là nhìn thấy được.
    #[must_use]
    pub fn is_visible(&self) -> bool {
        self.confidence.is_high()
    }

    /// Trả về vị trí 2D dưới dạng tuple.
    #[must_use]
    pub fn position_2d(&self) -> (f32, f32) {
        (self.x, self.y)
    }

    /// Trả về vị trí 3D dưới dạng tuple, nếu có.
    #[must_use]
    pub fn position_3d(&self) -> Option<(f32, f32, f32)> {
        self.z.map(|z| (self.x, self.y, z))
    }

    /// Tính khoảng cách Euclid đến điểm khớp khác.
    #[must_use]
    pub fn distance_to(&self, other: &Self) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        match (self.z, other.z) {
            (Some(z1), Some(z2)) => {
                let dz = z1 - z2;
                dz.mul_add(dz, dx.mul_add(dx, dy * dy)).sqrt()
            }
            _ => (dx * dx + dy * dy).sqrt(),
        }
    }
}

/// Khung bao căn chỉnh theo trục.
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct BoundingBox {
    /// Toạ độ X cạnh trái
    pub x_min: f32,
    /// Toạ độ Y cạnh trên
    pub y_min: f32,
    /// Toạ độ X cạnh phải
    pub x_max: f32,
    /// Toạ độ Y cạnh dưới
    pub y_max: f32,
}

impl BoundingBox {
    /// Tạo khung bao mới.
    #[must_use]
    pub fn new(x_min: f32, y_min: f32, x_max: f32, y_max: f32) -> Self {
        Self {
            x_min,
            y_min,
            x_max,
            y_max,
        }
    }

    /// Tạo khung bao từ tâm, chiều rộng và chiều cao.
    #[must_use]
    pub fn from_center(cx: f32, cy: f32, width: f32, height: f32) -> Self {
        let half_w = width / 2.0;
        let half_h = height / 2.0;
        Self {
            x_min: cx - half_w,
            y_min: cy - half_h,
            x_max: cx + half_w,
            y_max: cy + half_h,
        }
    }

    /// Trả về chiều rộng của khung bao.
    #[must_use]
    pub fn width(&self) -> f32 {
        self.x_max - self.x_min
    }

    /// Trả về chiều cao của khung bao.
    #[must_use]
    pub fn height(&self) -> f32 {
        self.y_max - self.y_min
    }

    /// Trả về diện tích của khung bao.
    #[must_use]
    pub fn area(&self) -> f32 {
        self.width() * self.height()
    }

    /// Trả về điểm tâm của khung bao.
    #[must_use]
    pub fn center(&self) -> (f32, f32) {
        ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)
    }

    /// Tính Giao trên Hợp (IoU) với khung bao khác.
    #[must_use]
    pub fn iou(&self, other: &Self) -> f32 {
        let x_min = self.x_min.max(other.x_min);
        let y_min = self.y_min.max(other.y_min);
        let x_max = self.x_max.min(other.x_max);
        let y_max = self.y_max.min(other.y_max);

        if x_max <= x_min || y_max <= y_min {
            return 0.0;
        }

        let intersection = (x_max - x_min) * (y_max - y_min);
        let union = self.area() + other.area() - intersection;

        if union <= 0.0 {
            0.0
        } else {
            intersection / union
        }
    }

    /// Trả về `true` nếu điểm nằm bên trong khung bao.
    #[must_use]
    pub fn contains(&self, x: f32, y: f32) -> bool {
        x >= self.x_min && x <= self.x_max && y >= self.y_min && y <= self.y_max
    }
}

/// Ước lượng tư thế cho một người đơn lẻ.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct PersonPose {
    /// Định danh duy nhất cho người này (để theo dõi)
    pub id: Option<u32>,
    /// Tất cả các điểm khớp phát hiện được
    pub keypoints: [Option<Keypoint>; MAX_KEYPOINTS],
    /// Khung bao quanh người
    pub bounding_box: Option<BoundingBox>,
    /// Độ tin cậy tổng thể của tư thế
    pub confidence: Confidence,
}

impl PersonPose {
    /// Tạo tư thế người trống mới.
    #[must_use]
    pub fn new() -> Self {
        Self {
            id: None,
            keypoints: [None; MAX_KEYPOINTS],
            bounding_box: None,
            confidence: Confidence::MIN,
        }
    }

    /// Đặt một điểm khớp.
    pub fn set_keypoint(&mut self, keypoint: Keypoint) {
        let idx = keypoint.keypoint_type as usize;
        if idx < MAX_KEYPOINTS {
            self.keypoints[idx] = Some(keypoint);
        }
    }

    /// Lấy điểm khớp theo loại.
    #[must_use]
    pub fn get_keypoint(&self, keypoint_type: KeypointType) -> Option<&Keypoint> {
        self.keypoints[keypoint_type as usize].as_ref()
    }

    /// Trả về số điểm khớp nhìn thấy được.
    #[must_use]
    pub fn visible_keypoint_count(&self) -> usize {
        self.keypoints
            .iter()
            .filter(|kp| kp.as_ref().is_some_and(Keypoint::is_visible))
            .count()
    }

    /// Trả về tất cả các điểm khớp nhìn thấy được.
    #[must_use]
    pub fn visible_keypoints(&self) -> Vec<&Keypoint> {
        self.keypoints
            .iter()
            .filter_map(|kp| kp.as_ref())
            .filter(|kp| kp.is_visible())
            .collect()
    }

    /// Tính khung bao từ các điểm khớp nhìn thấy được.
    #[must_use]
    pub fn compute_bounding_box(&self) -> Option<BoundingBox> {
        let visible: Vec<_> = self.visible_keypoints();
        if visible.is_empty() {
            return None;
        }

        let mut x_min = f32::MAX;
        let mut y_min = f32::MAX;
        let mut x_max = f32::MIN;
        let mut y_max = f32::MIN;

        for kp in visible {
            x_min = x_min.min(kp.x);
            y_min = y_min.min(kp.y);
            x_max = x_max.max(kp.x);
            y_max = y_max.max(kp.y);
        }

        Some(BoundingBox::new(x_min, y_min, x_max, y_max))
    }

    /// Chuyển đổi các điểm khớp thành mảng phẳng [x0, y0, conf0, x1, y1, conf1, ...].
    #[must_use]
    pub fn to_flat_array(&self) -> Array1<f32> {
        let mut arr = Array1::zeros(MAX_KEYPOINTS * 3);
        for (i, kp_opt) in self.keypoints.iter().enumerate() {
            if let Some(kp) = kp_opt {
                arr[i * 3] = kp.x;
                arr[i * 3 + 1] = kp.y;
                arr[i * 3 + 2] = kp.confidence.value();
            }
        }
        arr
    }
}

impl Default for PersonPose {
    fn default() -> Self {
        Self::new()
    }
}

/// Kết quả ước lượng tư thế hoàn chỉnh cho một khung.
#[derive(Debug, Clone)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct PoseEstimate {
    /// Định danh duy nhất cho ước lượng này
    pub id: FrameId,
    /// Dấu thời gian của ước lượng
    pub timestamp: Timestamp,
    /// Tín hiệu nguồn đã tạo ra ước lượng này
    pub source_signal_ids: Vec<FrameId>,
    /// Tất cả những người phát hiện được
    pub persons: Vec<PersonPose>,
    /// Độ tin cậy suy luận tổng thể
    pub confidence: Confidence,
    /// Độ trễ suy luận tính bằng mili giây
    pub latency_ms: f32,
    /// Phiên bản mô hình sử dụng cho suy luận
    pub model_version: String,
}

impl PoseEstimate {
    /// Tạo ước lượng tư thế mới.
    #[must_use]
    pub fn new(
        source_signal_ids: Vec<FrameId>,
        persons: Vec<PersonPose>,
        confidence: Confidence,
        latency_ms: f32,
        model_version: String,
    ) -> Self {
        Self {
            id: FrameId::new(),
            timestamp: Timestamp::now(),
            source_signal_ids,
            persons,
            confidence,
            latency_ms,
            model_version,
        }
    }

    /// Trả về số người phát hiện được.
    #[must_use]
    pub fn person_count(&self) -> usize {
        self.persons.len()
    }

    /// Trả về `true` nếu có người nào được phát hiện.
    #[must_use]
    pub fn has_detections(&self) -> bool {
        !self.persons.is_empty()
    }

    /// Trả về người có độ tin cậy cao nhất.
    #[must_use]
    pub fn highest_confidence_person(&self) -> Option<&PersonPose> {
        self.persons
            .iter()
            .max_by(|a, b| {
                a.confidence
                    .value()
                    .partial_cmp(&b.confidence.value())
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_confidence_validation() {
        assert!(Confidence::new(0.5).is_ok());
        assert!(Confidence::new(0.0).is_ok());
        assert!(Confidence::new(1.0).is_ok());
        assert!(Confidence::new(-0.1).is_err());
        assert!(Confidence::new(1.1).is_err());
    }

    #[test]
    fn test_confidence_threshold() {
        let high = Confidence::new(0.8).unwrap();
        let low = Confidence::new(0.3).unwrap();

        assert!(high.is_high());
        assert!(!low.is_high());
    }

    #[test]
    fn test_keypoint_distance() {
        let kp1 = Keypoint::new(KeypointType::Nose, 0.0, 0.0, Confidence::MAX);
        let kp2 = Keypoint::new(KeypointType::LeftEye, 3.0, 4.0, Confidence::MAX);

        let distance = kp1.distance_to(&kp2);
        assert!((distance - 5.0).abs() < 0.001);
    }

    #[test]
    fn test_bounding_box_iou() {
        let box1 = BoundingBox::new(0.0, 0.0, 10.0, 10.0);
        let box2 = BoundingBox::new(5.0, 5.0, 15.0, 15.0);

        let iou = box1.iou(&box2);
        // Giao: 5x5 = 25, Hợp: 100 + 100 - 25 = 175
        assert!((iou - 25.0 / 175.0).abs() < 0.001);
    }

    #[test]
    fn test_person_pose() {
        let mut pose = PersonPose::new();
        pose.set_keypoint(Keypoint::new(
            KeypointType::Nose,
            0.5,
            0.3,
            Confidence::new(0.95).unwrap(),
        ));
        pose.set_keypoint(Keypoint::new(
            KeypointType::LeftShoulder,
            0.4,
            0.5,
            Confidence::new(0.8).unwrap(),
        ));

        assert_eq!(pose.visible_keypoint_count(), 2);
        assert!(pose.get_keypoint(KeypointType::Nose).is_some());
        assert!(pose.get_keypoint(KeypointType::RightAnkle).is_none());
    }

    #[test]
    fn test_timestamp_duration() {
        let t1 = Timestamp::new(100, 0);
        let t2 = Timestamp::new(101, 500_000_000);

        let duration = t2.duration_since(&t1);
        assert!((duration - 1.5).abs() < 0.001);
    }

    #[test]
    fn test_keypoint_type_conversion() {
        assert_eq!(KeypointType::try_from(0).unwrap(), KeypointType::Nose);
        assert_eq!(KeypointType::try_from(16).unwrap(), KeypointType::RightAnkle);
        assert!(KeypointType::try_from(17).is_err());
    }

    #[test]
    fn test_frequency_band() {
        assert_eq!(FrequencyBand::Band2_4GHz.typical_subcarriers(), 56);
        assert_eq!(FrequencyBand::Band5GHz.typical_subcarriers(), 114);
        assert!(FrequencyBand::Band5GHz.center_frequency_mhz() > 5000);
    }
}
