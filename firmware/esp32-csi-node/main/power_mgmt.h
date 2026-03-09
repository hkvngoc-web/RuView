/**
 * @file power_mgmt.h
 * @brief Quản lý nguồn cho nút CSI ESP32-S3 chạy pin.
 *
 * Triển khai ngủ nhẹ giữa các lần thu thập CSI để giảm
 * tiêu thụ điện cho triển khai chạy pin.
 */

#ifndef POWER_MGMT_H
#define POWER_MGMT_H

#include <stdint.h>
#include "esp_err.h"

/**
 * Khởi tạo quản lý nguồn.
 * Cấu hình ngủ nhẹ tự động khi WiFi rảnh.
 *
 * @param duty_cycle_pct  Phần trăm chu kỳ hoạt động (10-100).
 *                        100 = luôn bật (hành vi mặc định).
 *                        50 = hoạt động 50% thời gian.
 * @return ESP_OK khi thành công.
 */
esp_err_t power_mgmt_init(uint8_t duty_cycle_pct);

/**
 * Lấy thống kê quản lý nguồn hiện tại.
 *
 * @param active_ms     Đầu ra: tổng thời gian hoạt động (ms).
 * @param sleep_ms      Đầu ra: tổng thời gian ngủ (ms).
 * @param wake_count    Đầu ra: số lần thức dậy.
 */
void power_mgmt_stats(uint32_t *active_ms, uint32_t *sleep_ms, uint32_t *wake_count);

#endif /* POWER_MGMT_H */
