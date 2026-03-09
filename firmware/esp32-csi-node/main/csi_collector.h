/**
 * @file csi_collector.h
 * @brief Thu thập dữ liệu CSI và tuần tự hóa khung nhị phân ADR-018.
 */

#ifndef CSI_COLLECTOR_H
#define CSI_COLLECTOR_H

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
#include "esp_wifi_types.h"

/** Số ma thuật ADR-018. */
#define CSI_MAGIC 0xC5110001

/** Kích thước header ADR-018 tính bằng byte. */
#define CSI_HEADER_SIZE 20

/** Kích thước bộ đệm khung tối đa (header + 4 antennas * 256 subcarriers * 2 bytes). */
#define CSI_MAX_FRAME_SIZE (CSI_HEADER_SIZE + 4 * 256 * 2)

/** Số kênh tối đa trong bảng nhảy (ADR-029). */
#define CSI_HOP_CHANNELS_MAX 6

/**
 * Khởi tạo thu thập CSI.
 * Đăng ký callback WiFi CSI.
 */
void csi_collector_init(void);

/**
 * Tuần tự hóa dữ liệu CSI theo định dạng khung nhị phân ADR-018.
 *
 * @param info   WiFi CSI info from the ESP-IDF callback.
 * @param buf    Output buffer (must be at least CSI_MAX_FRAME_SIZE bytes).
 * @param buf_len Size of the output buffer.
 * @return Number of bytes written, or 0 on error.
 */
size_t csi_serialize_frame(const wifi_csi_info_t *info, uint8_t *buf, size_t buf_len);

/**
 * Cấu hình bảng nhảy kênh cho cảm biến đa băng (ADR-029).
 *
 * When hop_count == 1 the collector stays on the single configured channel
 * (backward-compatible with the original single-channel mode).
 *
 * @param channels  Array of WiFi channel numbers (1-14 for 2.4 GHz, 36-177 for 5 GHz).
 * @param hop_count Number of entries in the channels array (1..CSI_HOP_CHANNELS_MAX).
 * @param dwell_ms  Dwell time per channel in milliseconds (>= 10).
 */
void csi_collector_set_hop_table(const uint8_t *channels, uint8_t hop_count, uint32_t dwell_ms);

/**
 * Chuyển sang kênh tiếp theo trong bảng nhảy.
 *
 * Called by the hop timer callback. If hop_count <= 1 this is a no-op.
 * Calls esp_wifi_set_channel() internally.
 */
void csi_hop_next_channel(void);

/**
 * Khởi động bộ đếm nhảy kênh.
 *
 * Creates an esp_timer periodic callback that fires every dwell_ms
 * milliseconds, calling csi_hop_next_channel(). If hop_count <= 1
 * the timer is not started (single-channel backward-compatible mode).
 */
void csi_collector_start_hop_timer(void);

/**
 * Phát khung NDP (Gói dữ liệu rỗng) cho cảm biến.
 *
 * Uses esp_wifi_80211_tx() to send a preamble-only frame (~24 us airtime)
 * that triggers CSI measurement at all receivers. This is the "sensing-first"
 * TX mechanism described in ADR-029.
 *
 * @return ESP_OK on success, or an error code.
 *
 * @note TODO: Full NDP frame construction. Currently sends a minimal
 *       null-data frame as a placeholder.
 */
esp_err_t csi_inject_ndp_frame(void);

#endif /* CSI_COLLECTOR_H */
