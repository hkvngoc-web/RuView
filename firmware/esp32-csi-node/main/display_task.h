/**
 * @file display_task.h
 * @brief ADR-045: Tác vụ hiển thị FreeRTOS — bơm LVGL trên Nhân 0.
 */

#ifndef DISPLAY_TASK_H
#define DISPLAY_TASK_H

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Khởi động tác vụ hiển thị trên Nhân 0, ưu tiên 1.
 *
 * Dò panel RM67162 và SPIRAM. Nếu một trong hai vắng mặt,
 * ghi cảnh báo và trả về ESP_OK (bỏ qua nhẹ nhàng).
 *
 * @return ESP_OK luôn (hiển thị là tùy chọn).
 */
esp_err_t display_task_start(void);

#ifdef __cplusplus
}
#endif

#endif /* DISPLAY_TASK_H */
