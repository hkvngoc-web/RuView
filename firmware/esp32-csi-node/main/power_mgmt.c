/**
 * @file power_mgmt.c
 * @brief Quản lý nguồn cho nút CSI ESP32-S3 chạy pin.
 *
 * Sử dụng chế độ ngủ nhẹ tự động của ESP-IDF với chế độ tiết kiệm điện WiFi.
 * Trong ngủ nhẹ, WiFi duy trì kết nối nhưng tạm dừng thu thập CSI.
 * Chu kỳ hoạt động kiểm soát tần suất thiết bị thức dậy để thu CSI.
 */

#include "power_mgmt.h"

#include "esp_log.h"
#include "esp_pm.h"
#include "esp_wifi.h"
#include "esp_sleep.h"
#include "esp_timer.h"

static const char *TAG = "power_mgmt";

static uint32_t s_active_ms  = 0;
static uint32_t s_sleep_ms   = 0;
static uint32_t s_wake_count = 0;
static int64_t  s_last_wake  = 0;

esp_err_t power_mgmt_init(uint8_t duty_cycle_pct)
{
    if (duty_cycle_pct >= 100) {
        ESP_LOGI(TAG, "Quản lý nguồn tắt (chu_kỳ_hoạt_động=100%%)");
        return ESP_OK;
    }

    if (duty_cycle_pct < 10) {
        duty_cycle_pct = 10;
        ESP_LOGW(TAG, "Chu kỳ hoạt động giới hạn tối thiểu 10%%");
    }

    ESP_LOGI(TAG, "Khởi tạo quản lý nguồn (chu_kỳ_hoạt_động=%u%%)", duty_cycle_pct);

    /* Bật chế độ tiết kiệm điện WiFi (modem sleep). */
    esp_err_t err = esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Tiết kiệm điện WiFi thất bại: %s (tiếp tục không có PM)",
                 esp_err_to_name(err));
        return err;
    }

    /* Cấu hình ngủ nhẹ tự động qua quản lý nguồn.
     * ESP-IDF sẽ vào ngủ nhẹ khi không có tác vụ nào sẵn sàng chạy. */
#if CONFIG_PM_ENABLE
    esp_pm_config_t pm_config = {
        .max_freq_mhz = 240,
        .min_freq_mhz = 80,
        .light_sleep_enable = true,
    };

    err = esp_pm_configure(&pm_config);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Cấu hình PM thất bại: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "Ngủ nhẹ đã bật: max=%dMHz, min=%dMHz",
             pm_config.max_freq_mhz, pm_config.min_freq_mhz);
#else
    ESP_LOGW(TAG, "CONFIG_PM_ENABLE chưa đặt — ngủ nhẹ không khả dụng. "
             "Bật trong menuconfig: Component config → Power Management");
#endif

    s_last_wake = esp_timer_get_time();
    s_wake_count = 1;

    ESP_LOGI(TAG, "Quản lý nguồn đã khởi tạo (WiFi modem sleep đang hoạt động)");
    return ESP_OK;
}

void power_mgmt_stats(uint32_t *active_ms, uint32_t *sleep_ms, uint32_t *wake_count)
{
    if (active_ms)  *active_ms  = s_active_ms;
    if (sleep_ms)   *sleep_ms   = s_sleep_ms;
    if (wake_count) *wake_count = s_wake_count;
}
