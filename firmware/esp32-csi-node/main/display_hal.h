/**
 * @file display_hal.h
 * @brief ADR-045: HAL AMOLED QSPI RM67162 + cảm ứng CST816S.
 *
 * Trừu tượng hóa phần cứng cho panel AMOLED LilyGO T-Display-S3.
 * Dò phần cứng khi khởi động; trả về ESP_ERR_NOT_FOUND nếu vắng mặt.
 */

#ifndef DISPLAY_HAL_H
#define DISPLAY_HAL_H

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Dò và khởi tạo panel AMOLED QSPI RM67162.
 *
 * Cấu hình bus QSPI, gửi chuỗi khởi tạo panel, và điền
 * màn hình nền tối để xác nhận hoạt động.
 * Trả về ESP_ERR_NOT_FOUND nếu panel không phản hồi.
 *
 * @return ESP_OK khi thành công, ESP_ERR_NOT_FOUND nếu không phát hiện màn hình.
 */
esp_err_t display_hal_init_panel(void);

/**
 * Vẽ hình chữ nhật pixel lên AMOLED.
 * Gửi CASET + RASET + RAMWR trực tiếp qua QSPI.
 *
 * @param x_start  Cột trái (bao gồm).
 * @param y_start  Hàng trên (bao gồm).
 * @param x_end    Cột phải (không bao gồm).
 * @param y_end    Hàng dưới (không bao gồm).
 * @param color_data  Dữ liệu pixel RGB565, (x_end-x_start)*(y_end-y_start) pixel.
 */
void display_hal_draw(int x_start, int y_start, int x_end, int y_end,
                      const void *color_data);

/**
 * Dò và khởi tạo bộ điều khiển cảm ứng điện dung CST816S.
 *
 * @return ESP_OK khi thành công, ESP_ERR_NOT_FOUND nếu không phát hiện IC cảm ứng.
 */
esp_err_t display_hal_init_touch(void);

/**
 * Đọc điểm chạm (không chặn).
 *
 * @param[out] x  Tọa độ X chạm (0..535).
 * @param[out] y  Tọa độ Y chạm (0..239).
 * @return true nếu đang chạm, false nếu đã thả.
 */
bool display_hal_touch_read(uint16_t *x, uint16_t *y);

/**
 * Đặt độ sáng AMOLED qua lệnh MIPI DCS.
 *
 * @param percent  Độ sáng 0-100.
 */
void display_hal_set_brightness(uint8_t percent);

#ifdef __cplusplus
}
#endif

#endif /* DISPLAY_HAL_H */
