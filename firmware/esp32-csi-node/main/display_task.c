/**
 * @file display_task.c
 * @brief ADR-045: Tác vụ hiển thị FreeRTOS — bơm LVGL trên Nhân 0, ưu tiên 1.
 *
 * Bỏ qua nhẹ nhàng nếu panel RM67162 hoặc SPIRAM vắng mặt.
 * Đọc từ edge_get_vitals() / edge_get_multi_person() (an toàn luồng).
 */

#include "display_task.h"
#include "sdkconfig.h"

#if CONFIG_DISPLAY_ENABLE

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "lvgl.h"

#include "display_hal.h"
#include "display_ui.h"

#define DISP_H_RES  368
#define DISP_V_RES  448

static const char *TAG = "disp_task";

/* ---- Cấu hình ---- */
#ifdef CONFIG_DISPLAY_FPS_LIMIT
#define DISP_FPS_LIMIT      CONFIG_DISPLAY_FPS_LIMIT
#else
#define DISP_FPS_LIMIT      30
#endif

#define DISP_TASK_STACK      (8 * 1024)
#define DISP_TASK_PRIORITY   1
#define DISP_TASK_CORE       0

#define DISP_BUF_LINES       40

/* ---- Callback flush LVGL — gọi display_hal_draw trực tiếp ---- */
static void lvgl_flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_p)
{
    display_hal_draw(area->x1, area->y1, area->x2 + 1, area->y2 + 1, color_p);
    lv_disp_flush_ready(drv);
}

/* ---- Callback đầu vào cảm ứng LVGL ---- */
static void lvgl_touch_cb(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    uint16_t x, y;
    if (display_hal_touch_read(&x, &y)) {
        data->point.x = x;
        data->point.y = y;
        data->state = LV_INDEV_STATE_PRESSED;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

/* ---- Tác vụ hiển thị ---- */
static void display_task(void *arg)
{
    const TickType_t frame_period = pdMS_TO_TICKS(1000 / DISP_FPS_LIMIT);

    ESP_LOGI(TAG, "Tác vụ hiển thị running on Core %d, %d fps limit",
             xPortGetCoreID(), DISP_FPS_LIMIT);

    display_ui_create(lv_scr_act());

    TickType_t last_wake = xTaskGetTickCount();
    while (1) {
        display_ui_update();
        lv_timer_handler();
        vTaskDelayUntil(&last_wake, frame_period);
    }
}

/* ---- Public API ---- */

esp_err_t display_task_start(void)
{
    ESP_LOGI(TAG, "Đang khởi tạo hệ thống hiển thị...");

    bool use_psram = false;
#if CONFIG_SPIRAM
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    if (psram_free >= 64 * 1024) {
        use_psram = true;
        ESP_LOGI(TAG, "PSRAM khả dụng: %u KB — sử dụng bộ đệm PSRAM", (unsigned)(psram_free / 1024));
    } else {
        ESP_LOGW(TAG, "PSRAM quá nhỏ (%u byte) — chuyển sang bộ nhớ DMA nội", (unsigned)psram_free);
    }
#else
    ESP_LOGW(TAG, "SPIRAM chưa bật — sử dụng bộ nhớ DMA nội (bộ đệm nhỏ hơn)");
#endif

    /* Dò phần cứng hiển thị */
    esp_err_t ret = display_hal_init_panel();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Màn hình không khả dụng — chạy không giao diện");
        return ESP_OK;
    }

    /* Khởi tạo cảm ứng (tùy chọn) */
    esp_err_t touch_ret = display_hal_init_touch();

    /* Khởi tạo LVGL */
    lv_init();

    /* Bộ đệm vẽ đệm đôi — ưu tiên PSRAM, dự phòng DMA nội */
    size_t buf_lines = use_psram ? DISP_BUF_LINES : 10;  /* Bộ đệm nhỏ hơn khi không có PSRAM */
    size_t buf_size = DISP_H_RES * buf_lines * sizeof(lv_color_t);
    uint32_t alloc_caps = use_psram ? MALLOC_CAP_SPIRAM : (MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    lv_color_t *buf1 = heap_caps_malloc(buf_size, alloc_caps);
    lv_color_t *buf2 = heap_caps_malloc(buf_size, alloc_caps);
    if (!buf1 || !buf2) {
        ESP_LOGE(TAG, "Không thể cấp phát bộ đệm LVGL (%u byte, caps=0x%lx)",
                 (unsigned)buf_size, (unsigned long)alloc_caps);
        if (buf1) free(buf1);
        if (buf2) free(buf2);
        return ESP_OK;
    }
    ESP_LOGI(TAG, "LVGL buffers: 2x %u bytes (%u lines, %s)",
             (unsigned)buf_size, (unsigned)buf_lines, use_psram ? "PSRAM" : "internal DMA");

    static lv_disp_draw_buf_t draw_buf;
    lv_disp_draw_buf_init(&draw_buf, buf1, buf2, DISP_H_RES * buf_lines);

    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res  = DISP_H_RES;
    disp_drv.ver_res  = DISP_V_RES;
    disp_drv.flush_cb = lvgl_flush_cb;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    if (touch_ret == ESP_OK) {
        static lv_indev_drv_t indev_drv;
        lv_indev_drv_init(&indev_drv);
        indev_drv.type    = LV_INDEV_TYPE_POINTER;
        indev_drv.read_cb = lvgl_touch_cb;
        lv_indev_drv_register(&indev_drv);
        ESP_LOGI(TAG, "Đầu vào cảm ứng đã đăng ký");
    }

    BaseType_t xret = xTaskCreatePinnedToCore(
        display_task, "display", DISP_TASK_STACK,
        NULL, DISP_TASK_PRIORITY, NULL, DISP_TASK_CORE);

    if (xret != pdPASS) {
        ESP_LOGE(TAG, "Không thể tạo tác vụ hiển thị");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Tác vụ hiển thị started (Core %d, priority %d, %d fps)",
             DISP_TASK_CORE, DISP_TASK_PRIORITY, DISP_FPS_LIMIT);
    return ESP_OK;
}

#else /* !CONFIG_DISPLAY_ENABLE */

esp_err_t display_task_start(void)
{
    return ESP_OK;
}

#endif /* CONFIG_DISPLAY_ENABLE */
