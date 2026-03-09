/**
 * @file ota_update.h
 * @brief Endpoint cập nhật firmware OTA qua HTTP cho nút CSI ESP32-S3.
 *
 * Cung cấp endpoint server HTTP chấp nhận firmware nhị phân
 * cho cập nhật không dây mà không cần truy cập vật lý vào thiết bị.
 */

#ifndef OTA_UPDATE_H
#define OTA_UPDATE_H

#include "esp_err.h"

/**
 * Khởi tạo server HTTP cập nhật OTA.
 * Khởi động server HTTP nhẹ trên cổng 8032 chấp nhận
 * POST /ota với payload firmware nhị phân.
 *
 * @return ESP_OK khi thành công.
 */
esp_err_t ota_update_init(void);

/**
 * Khởi tạo server HTTP cập nhật OTA và trả về handle.
 * Giống ota_update_init() nhưng cung cấp httpd_handle_t để
 * các module khác (VD: WASM upload) có thể đăng ký thêm endpoint.
 *
 * @param out_server  Đầu ra: handle server HTTP (có thể NULL khi thất bại).
 * @return ESP_OK khi thành công.
 */
esp_err_t ota_update_init_ex(void **out_server);

#endif /* OTA_UPDATE_H */
