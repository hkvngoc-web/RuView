/**
 * @file main.c
 * @brief Nút cảm biến ESP32-S3 CSI — phần mềm tuân thủ ADR-018.
 *
 * Khởi tạo NVS, chế độ WiFi STA, thu thập CSI, và truyền phát UDP.
 * Các khung CSI được tuần tự hóa theo định dạng nhị phân ADR-018 và gửi tới
 * bộ tổng hợp qua UDP.
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "csi_collector.h"
#include "stream_sender.h"
#include "nvs_config.h"
#include "edge_processing.h"
#include "ota_update.h"
#include "power_mgmt.h"
#include "wasm_runtime.h"
#include "wasm_upload.h"
#include "display_task.h"

#include "esp_timer.h"

static const char *TAG = "main";

/* ADR-040: Handle bộ đếm WASM (gọi on_timer theo chu kỳ cấu hình). */
static esp_timer_handle_t s_wasm_timer;

/* Cấu hình runtime (tải từ NVS hoặc mặc định Kconfig).
 * Biến toàn cục để các module khác (wasm_upload.c) truy cập pubkey, v.v. */
nvs_config_t g_nvs_config;

/* Các bit nhóm sự kiện */
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static EventGroupHandle_t s_wifi_event_group;
static int s_retry_num = 0;
#define MAX_RETRY 10

static void event_handler(void *arg, esp_event_base_t event_base,
                          int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry_num < MAX_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "Đang thử kết nối lại WiFi (%d/%d)", s_retry_num, MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Đã nhận IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL, &instance_got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };

    /* Sao chép SSID/mật khẩu runtime từ cấu hình NVS */
    strncpy((char *)wifi_config.sta.ssid, g_nvs_config.wifi_ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, g_nvs_config.wifi_password, sizeof(wifi_config.sta.password) - 1);

    /* Nếu mật khẩu trống, dùng xác thực mở */
    if (strlen((char *)wifi_config.sta.password) == 0) {
        wifi_config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    }

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "WiFi STA đã khởi tạo, đang kết nối tới SSID: %s", g_nvs_config.wifi_ssid);

    /* Chờ kết nối */
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
        WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
        pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Đã kết nối WiFi thành công");
    } else if (bits & WIFI_FAIL_BIT) {
        ESP_LOGE(TAG, "Kết nối WiFi thất bại sau %d lần thử", MAX_RETRY);
    }
}

void app_main(void)
{
    /* Khởi tạo NVS */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* Tải cấu hình runtime (NVS ghi đè mặc định Kconfig) */
    nvs_config_load(&g_nvs_config);

    ESP_LOGI(TAG, "Nút cảm biến ESP32-S3 CSI (ADR-018) — Mã nút: %d", g_nvs_config.node_id);

    /* Khởi tạo WiFi STA */
    wifi_init_sta();

    /* Khởi tạo bộ gửi UDP với đích runtime */
    if (stream_sender_init_with(g_nvs_config.target_ip, g_nvs_config.target_port) != 0) {
        ESP_LOGE(TAG, "Khởi tạo bộ gửi UDP thất bại");
        return;
    }

    /* Khởi tạo thu thập CSI */
    csi_collector_init();

    /* ADR-039: Khởi tạo pipeline xử lý biên. */
    edge_config_t edge_cfg = {
        .tier              = g_nvs_config.edge_tier,
        .presence_thresh   = g_nvs_config.presence_thresh,
        .fall_thresh       = g_nvs_config.fall_thresh,
        .vital_window      = g_nvs_config.vital_window,
        .vital_interval_ms = g_nvs_config.vital_interval_ms,
        .top_k_count       = g_nvs_config.top_k_count,
        .power_duty        = g_nvs_config.power_duty,
    };
    esp_err_t edge_ret = edge_processing_init(&edge_cfg);
    if (edge_ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo xử lý biên thất bại: %s (tiếp tục không có DSP biên)",
                 esp_err_to_name(edge_ret));
    }

    /* Khởi tạo máy chủ cập nhật OTA qua HTTP. */
    httpd_handle_t ota_server = NULL;
    esp_err_t ota_ret = ota_update_init_ex(&ota_server);
    if (ota_ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo máy chủ OTA thất bại: %s", esp_err_to_name(ota_ret));
    }

    /* ADR-040: Khởi tạo runtime cảm biến lập trình WASM. */
    esp_err_t wasm_ret = wasm_runtime_init();
    if (wasm_ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo runtime WASM thất bại: %s", esp_err_to_name(wasm_ret));
    } else {
        /* Đăng ký endpoint tải lên WASM trên máy chủ HTTP OTA. */
        if (ota_server != NULL) {
            wasm_upload_register(ota_server);
        }

        /* Khởi động bộ đếm định kỳ cho wasm_runtime_on_timer(). */
        esp_timer_create_args_t timer_args = {
            .callback = (void (*)(void *))wasm_runtime_on_timer,
            .arg = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "wasm_timer",
        };
        esp_err_t timer_ret = esp_timer_create(&timer_args, &s_wasm_timer);
        if (timer_ret == ESP_OK) {
#ifdef CONFIG_WASM_TIMER_INTERVAL_MS
            uint64_t interval_us = (uint64_t)CONFIG_WASM_TIMER_INTERVAL_MS * 1000ULL;
#else
            uint64_t interval_us = 1000000ULL;  /* Default: 1 second. */
#endif
            esp_timer_start_periodic(s_wasm_timer, interval_us);
            ESP_LOGI(TAG, "WASM on_timer() định kỳ: %llu ms",
                     (unsigned long long)(interval_us / 1000));
        } else {
            ESP_LOGW(TAG, "Tạo bộ đếm WASM thất bại: %s", esp_err_to_name(timer_ret));
        }
    }

    /* Khởi tạo quản lý nguồn. */
    power_mgmt_init(g_nvs_config.power_duty);

    /* ADR-045: Khởi động tác vụ màn hình AMOLED (bỏ qua nếu không có màn hình). */
    esp_err_t disp_ret = display_task_start();
    if (disp_ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo màn hình trả về: %s", esp_err_to_name(disp_ret));
    }

    ESP_LOGI(TAG, "Luồng CSI đang hoạt động → %s:%d (edge_tier=%u, OTA=%s, WASM=%s)",
             g_nvs_config.target_ip, g_nvs_config.target_port,
             g_nvs_config.edge_tier,
             (ota_ret == ESP_OK) ? "ready" : "off",
             (wasm_ret == ESP_OK) ? "ready" : "off");

    /* Vòng lặp chính — duy trì hoạt động */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
