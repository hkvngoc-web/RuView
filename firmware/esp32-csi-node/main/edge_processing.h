/**
 * @file edge_processing.h
 * @brief ADR-039 Trí Tuệ Biên — đường ống xử lý CSI hai nhân.
 *
 * Nhân 0 (WiFi): Tạo khung CSI vào bộ đệm vòng SPSC không khóa.
 * Nhân 1 (DSP):  Tiêu thụ khung, chạy xử lý tín hiệu, trích xuất sinh hiệu.
 *
 * Features:
 *   - Bộ lọc thông dải biquad IIR cho nhịp thở (0.1-0.5 Hz) và nhịp tim (0.8-2.0 Hz)
 *   - Mở gói pha và thống kê chạy Welford
 *   - Chọn sóng mang phụ Top-K theo phương sai
 *   - Phát hiện hiện diện với hiệu chuẩn ngưỡng thích ứng
 *   - Sinh hiệu: nhịp thở, nhịp tim (BPM cắt zero)
 *   - Phát hiện ngã (gia tốc pha vượt ngưỡng)
 *   - Nén delta (XOR + RLE) để giảm băng thông
 *   - Sinh hiệu đa người qua phân nhóm sóng mang phụ
 *   - Gói sinh hiệu 32-byte (magic 0xC5110002) cho phân tích phía server
 */

#ifndef EDGE_PROCESSING_H
#define EDGE_PROCESSING_H

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

/* ---- Số magic ---- */
#define EDGE_VITALS_MAGIC     0xC5110002  /**< Magic gói sinh hiệu. */
#define EDGE_COMPRESSED_MAGIC 0xC5110003  /**< Magic khung nén. */

/* ---- Kích thước bộ đệm ---- */
#define EDGE_RING_SLOTS       16    /**< Khe bộ đệm vòng SPSC (lũy thừa 2). */
#define EDGE_MAX_IQ_BYTES     1024  /**< Tải I/Q tối đa mỗi khe. */
#define EDGE_PHASE_HISTORY_LEN 256  /**< Độ sâu bộ đệm lịch sử pha. */
#define EDGE_TOP_K            8     /**< Sóng mang phụ Top-K cần theo dõi. */
#define EDGE_MAX_SUBCARRIERS  128   /**< Sóng mang phụ tối đa mỗi khung. */

/* ---- Đa người ---- */
#define EDGE_MAX_PERSONS      4     /**< Số người đồng thời tối đa. */

/* ---- Hiệu chuẩn ---- */
#define EDGE_CALIB_FRAMES     1200  /**< Khung cho hiệu chuẩn thích ứng (~60 giây ở 20 Hz). */
#define EDGE_CALIB_SIGMA_MULT 3.0f  /**< Ngưỡng = trung bình + 3*sigma của môi trường. */

/* ---- Khe bộ đệm vòng SPSC ---- */
typedef struct {
    uint8_t  iq_data[EDGE_MAX_IQ_BYTES]; /**< Byte I/Q thô từ callback CSI. */
    uint16_t iq_len;                     /**< Độ dài dữ liệu I/Q thực tế. */
    int8_t   rssi;                       /**< RSSI từ rx_ctrl. */
    uint8_t  channel;                    /**< Kênh WiFi. */
    uint32_t timestamp_us;               /**< Nhãn thời gian micro giây. */
} edge_ring_slot_t;

/* ---- Bộ đệm vòng SPSC ---- */
typedef struct {
    edge_ring_slot_t slots[EDGE_RING_SLOTS];
    volatile uint32_t head;  /**< Ghi bởi nhà sản xuất (Nhân 0). */
    volatile uint32_t tail;  /**< Ghi bởi nhà tiêu thụ (Nhân 1). */
} edge_ring_buf_t;

/* ---- Trạng thái bộ lọc biquad IIR ---- */
typedef struct {
    float b0, b1, b2;  /**< Hệ số tử số. */
    float a1, a2;       /**< Hệ số mẫu số (a0 = 1). */
    float x1, x2;       /**< Đường trễ đầu vào. */
    float y1, y2;       /**< Đường trễ đầu ra. */
} edge_biquad_t;

/* ---- Thống kê chạy Welford ---- */
typedef struct {
    double mean;
    double m2;
    uint32_t count;
} edge_welford_t;

/* ---- Trạng thái sinh hiệu theo người (chế độ đa người) ---- */
typedef struct {
    float    phase_history[EDGE_PHASE_HISTORY_LEN];
    uint16_t history_len;
    uint16_t history_idx;
    float    breathing_bpm;
    float    heartrate_bpm;
    uint8_t  subcarrier_idx;  /**< Nhóm sóng mang phụ người này theo dõi. */
    bool     active;
} edge_person_vitals_t;

/* ---- Gói sinh hiệu (32 byte, định dạng truyền) ---- */
typedef struct __attribute__((packed)) {
    uint32_t magic;          /**< EDGE_VITALS_MAGIC = 0xC5110002. */
    uint8_t  node_id;        /**< Mã định danh nút ESP32. */
    uint8_t  flags;          /**< Bit0=hiện diện, Bit1=ngã, Bit2=chuyển động. */
    uint16_t breathing_rate; /**< BPM * 100 (dấu phẩy cố định). */
    uint32_t heartrate;      /**< BPM * 10000 (dấu phẩy cố định). */
    int8_t   rssi;           /**< RSSI mới nhất. */
    uint8_t  n_persons;      /**< Số người phát hiện (đa người). */
    uint8_t  reserved[2];
    float    motion_energy;  /**< Phương sai pha / chỉ số chuyển động. */
    float    presence_score; /**< Điểm phát hiện hiện diện. */
    uint32_t timestamp_ms;   /**< Mili giây kể từ khởi động. */
    uint32_t reserved2;      /**< Dành cho tương lai. */
} edge_vitals_pkt_t;

_Static_assert(sizeof(edge_vitals_pkt_t) == 32, "vitals packet must be 32 bytes");

/* ---- Cấu hình xử lý biên (từ NVS) ---- */
typedef struct {
    uint8_t  tier;           /**< Tầng xử lý: 0=thô, 1=cơ bản, 2=đầy đủ. */
    float    presence_thresh;/**< Ngưỡng phát hiện hiện diện (0 = tự hiệu chuẩn). */
    float    fall_thresh;    /**< Ngưỡng phát hiện ngã (gia tốc pha, rad/s^2). */
    uint16_t vital_window;   /**< Cửa sổ lịch sử pha cho ước lượng BPM. */
    uint16_t vital_interval_ms; /**< Khoảng gửi gói sinh hiệu tính bằng ms. */
    uint8_t  top_k_count;    /**< Số sóng mang phụ hàng đầu cần theo dõi. */
    uint8_t  power_duty;     /**< Phần trăm chu kỳ hoạt động nguồn (10-100). */
} edge_config_t;

/**
 * Khởi tạo đường ống xử lý biên.
 * Creates the Bộ đệm vòng SPSC and starts the DSP task on Core 1.
 *
 * @param cfg  Cấu hình biên (từ NVS hoặc mặc định).
 * @return ESP_OK khi thành công.
 */
esp_err_t edge_processing_init(const edge_config_t *cfg);

/**
 * Xếp hàng khung CSI từ callback WiFi (Nhân 0).
 * Push SPSC không khóa — an toàn để gọi từ ngữ cảnh ISR.
 *
 * @param iq_data   Dữ liệu I/Q thô từ wifi_csi_info_t.buf.
 * @param iq_len    Độ dài dữ liệu I/Q tính bằng byte.
 * @param rssi      RSSI từ rx_ctrl.
 * @param channel   Số kênh WiFi.
 * @return true nếu đã xếp hàng, false nếu bộ đệm vòng đầy (khung bị bỏ).
 */
bool edge_enqueue_csi(const uint8_t *iq_data, uint16_t iq_len,
                      int8_t rssi, uint8_t channel);

/**
 * Lấy gói sinh hiệu mới nhất (bản sao an toàn luồng).
 *
 * @param pkt  Gói sinh hiệu đầu ra.
 * @return true nếu có dữ liệu sinh hiệu hợp lệ.
 */
bool edge_get_vitals(edge_vitals_pkt_t *pkt);

/**
 * Lấy mảng sinh hiệu đa người.
 *
 * @param persons   Mảng đầu ra (phải có EDGE_MAX_PERSONS phần tử).
 * @param n_active  Đầu ra: số người hoạt động.
 */
void edge_get_multi_person(edge_person_vitals_t *persons, uint8_t *n_active);

/**
 * Lấy con trỏ đến bộ đệm vòng lịch sử pha và trạng thái.
 * Được sử dụng bởi WASM runtime (ADR-040) để cung cấp lịch sử pha cho module.
 *
 * @param out_buf     Đầu ra: con trỏ đến mảng lịch sử pha.
 * @param out_len     Đầu ra: số mục hợp lệ.
 * @param out_idx     Đầu ra: chỉ số ghi hiện tại.
 */
void edge_get_phase_history(const float **out_buf, uint16_t *out_len,
                            uint16_t *out_idx);

/**
 * Lấy mảng phương sai Welford theo sóng mang phụ.
 * Được sử dụng bởi WASM runtime (ADR-040) để cung cấp phương sai cho module.
 *
 * @param out_variances  Mảng đầu ra (phải có EDGE_MAX_SUBCARRIERS phần tử).
 * @param n_subcarriers  Số sóng mang phụ cần điền.
 */
void edge_get_variances(float *out_variances, uint16_t n_subcarriers);

#endif /* EDGE_PROCESSING_H */
