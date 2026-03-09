/**
 * @file display_ui.h
 * @brief ADR-045: Giao diện LVGL 4 màn vuốt cho thống kê nút CSI.
 *
 * Các màn: Bảng Điều Khiển | Sinh Hiệu | Hiện Diện | Hệ Thống
 * Giao diện tối với nhấn xanh lam (#00d4ff).
 */

#ifndef DISPLAY_UI_H
#define DISPLAY_UI_H

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Tạo tất cả các màn LVGL trên tileview cha đã cho. */
void display_ui_create(lv_obj_t *parent);

/**
 * Cập nhật tất cả các màn với dữ liệu mới nhất. Gọi mỗi chu kỳ làm mới hiển thị.
 * Đọc từ edge_get_vitals() và edge_get_multi_person() nội bộ.
 */
void display_ui_update(void);

#ifdef __cplusplus
}
#endif

#endif /* DISPLAY_UI_H */
