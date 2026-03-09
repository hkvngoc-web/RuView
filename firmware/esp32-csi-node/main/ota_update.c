/**
 * @file ota_update.c
 * @brief Cập nhật firmware OTA qua HTTP cho nút CSI ESP32-S3.
 *
 * Sử dụng API OTA gốc của ESP-IDF với hỗ trợ rollback.
 * Server HTTP chạy trên cổng 8032 và chấp nhận:
 *   POST /ota — payload firmware nhị phân (application/octet-stream)
 *   GET /ota/status — phiên bản firmware và thông tin phân vùng hiện tại
 */

#include "ota_update.h"

#include <string.h>
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_http_server.h"
#include "esp_app_desc.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *TAG = "ota_update";

/** Cổng server HTTP OTA. */
#define OTA_PORT 8032

/** Kích thước firmware tối đa (900 KB — khớp cổng kích thước nhị phân CI). */
#define OTA_MAX_SIZE (900 * 1024)

/** Namespace NVS và khóa cho khóa chia sẻ trước OTA. */
#define OTA_NVS_NAMESPACE "security"
#define OTA_NVS_KEY       "ota_psk"

/** Độ dài PSK tối đa (SHA-256 mã hóa hex). */
#define OTA_PSK_MAX_LEN   65

/** PSK đã lưu cache từ NVS khi khởi tạo. Rỗng = xác thực tắt. */
static char s_ota_psk[OTA_PSK_MAX_LEN] = {0};

/**
 * ADR-050: Xác minh header Authorization chứa PSK đúng.
 * Trả về true nếu xác thực tắt (không có PSK) hoặc nếu
 * token Bearer khớp với PSK đã lưu.
 */
static bool ota_check_auth(httpd_req_t *req)
{
    if (s_ota_psk[0] == '\0') {
        /* Không có PSK — xác thực tắt (cho phép khi dev). */
        return true;
    }

    char auth_header[128] = {0};
    if (httpd_req_get_hdr_value_str(req, "Authorization", auth_header,
                                     sizeof(auth_header)) != ESP_OK) {
        return false;
    }

    /* Expect "Bearer <psk>" */
    const char *prefix = "Bearer ";
    if (strncmp(auth_header, prefix, strlen(prefix)) != 0) {
        return false;
    }

    const char *token = auth_header + strlen(prefix);
    /* So sánh thời gian cố định để ngăn tấn công timing. */
    size_t psk_len = strlen(s_ota_psk);
    size_t tok_len = strlen(token);
    if (psk_len != tok_len) return false;
    volatile uint8_t result = 0;
    for (size_t i = 0; i < psk_len; i++) {
        result |= (uint8_t)(s_ota_psk[i] ^ token[i]);
    }
    return result == 0;
}

/**
 * GET /ota/status — trả về phiên bản firmware và thông tin phân vùng.
 */
static esp_err_t ota_status_handler(httpd_req_t *req)
{
    const esp_app_desc_t *app = esp_app_get_description();
    const esp_partition_t *running = esp_ota_get_running_partition();
    const esp_partition_t *update = esp_ota_get_next_update_partition(NULL);

    char response[512];
    int len = snprintf(response, sizeof(response),
        "{\"version\":\"%s\",\"date\":\"%s\",\"time\":\"%s\","
        "\"running_partition\":\"%s\",\"next_partition\":\"%s\","
        "\"max_size\":%d}",
        app->version, app->date, app->time,
        running ? running->label : "unknown",
        update ? update->label : "none",
        OTA_MAX_SIZE);

    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, response, len);
    return ESP_OK;
}

/**
 * POST /ota — nhận và nạp firmware nhị phân.
 */
static esp_err_t ota_upload_handler(httpd_req_t *req)
{
    /* ADR-050: Xác thực trước khi chấp nhận upload firmware. */
    if (!ota_check_auth(req)) {
        ESP_LOGW(TAG, "Upload OTA bị từ chối: xác thực thất bại");
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN,
                            "Yêu cầu xác thực. Dùng: Authorization: Bearer <psk>");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Bắt đầu cập nhật OTA, content_length=%d", req->content_len);

    if (req->content_len <= 0 || req->content_len > OTA_MAX_SIZE) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                            "Kích thước firmware không hợp lệ (phải 1B - 900KB)");
        return ESP_FAIL;
    }

    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (update_partition == NULL) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "Không có phân vùng OTA khả dụng");
        return ESP_FAIL;
    }

    esp_ota_handle_t ota_handle;
    esp_err_t err = esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "Bắt đầu OTA thất bại");
        return ESP_FAIL;
    }

    /* Đọc firmware theo từng đoạn. */
    char buf[1024];
    int received = 0;
    int total = 0;

    while (total < req->content_len) {
        received = httpd_req_recv(req, buf, sizeof(buf));
        if (received <= 0) {
            if (received == HTTPD_SOCK_ERR_TIMEOUT) {
                continue;  /* Thử lại khi hết thời gian. */
            }
            ESP_LOGE(TAG, "Lỗi nhận OTA tại byte %d", total);
            esp_ota_abort(ota_handle);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                "Lỗi nhận dữ liệu");
            return ESP_FAIL;
        }

        err = esp_ota_write(ota_handle, buf, received);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write failed at byte %d: %s",
                     total, esp_err_to_name(err));
            esp_ota_abort(ota_handle);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                                "Ghi OTA thất bại");
            return ESP_FAIL;
        }

        total += received;
        if ((total % (64 * 1024)) == 0) {
            ESP_LOGI(TAG, "Tiến trình OTA: %d / %d byte (%.0f%%)",
                     total, req->content_len,
                     (float)total * 100.0f / (float)req->content_len);
        }
    }

    err = esp_ota_end(ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end failed: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "Xác thực OTA thất bại");
        return ESP_FAIL;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition failed: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR,
                            "Đặt phân vùng khởi động thất bại");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Cập nhật OTA thành công! Đang khởi động lại phân vùng '%s'...",
             update_partition->label);

    const char *resp = "{\"status\":\"ok\",\"message\":\"OTA update successful. Rebooting...\"}";
    httpd_resp_set_type(req, "application/json");
    httpd_resp_send(req, resp, strlen(resp));

    /* Chờ ngắn để phản hồi xong, sau đó khởi động lại. */
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();

    return ESP_OK;  /* Không bao giờ đến đây. */
}

/** Nội bộ: khởi động server HTTP và đăng ký endpoint OTA. */
static esp_err_t ota_start_server(httpd_handle_t *out_handle)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = OTA_PORT;
    config.max_uri_handlers = 12;  /* Khe bổ sung cho endpoint WASM (ADR-040). */
    /* Tăng thời gian chờ nhận cho upload lớn. */
    config.recv_wait_timeout = 30;

    httpd_handle_t server = NULL;
    esp_err_t err = httpd_start(&server, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Không thể khởi động server HTTP OTA trên cổng %d: %s",
                 OTA_PORT, esp_err_to_name(err));
        if (out_handle) *out_handle = NULL;
        return err;
    }

    httpd_uri_t status_uri = {
        .uri      = "/ota/status",
        .method   = HTTP_GET,
        .handler  = ota_status_handler,
        .user_ctx = NULL,
    };
    httpd_register_uri_handler(server, &status_uri);

    httpd_uri_t upload_uri = {
        .uri      = "/ota",
        .method   = HTTP_POST,
        .handler  = ota_upload_handler,
        .user_ctx = NULL,
    };
    httpd_register_uri_handler(server, &upload_uri);

    ESP_LOGI(TAG, "Server HTTP OTA đã khởi động trên cổng %d", OTA_PORT);
    ESP_LOGI(TAG, "  GET  /ota/status — thông tin phiên bản firmware");
    ESP_LOGI(TAG, "  POST /ota        — upload firmware nhị phân mới");

    if (out_handle) *out_handle = server;
    return ESP_OK;
}

esp_err_t ota_update_init(void)
{
    /* ADR-050: Tải PSK OTA từ NVS nếu đã cung cấp. */
    nvs_handle_t nvs;
    if (nvs_open(OTA_NVS_NAMESPACE, NVS_READONLY, &nvs) == ESP_OK) {
        size_t len = sizeof(s_ota_psk);
        if (nvs_get_str(nvs, OTA_NVS_KEY, s_ota_psk, &len) == ESP_OK) {
            ESP_LOGI(TAG, "PSK OTA đã tải từ NVS (%d ký tự) — xác thực đã bật", (int)len - 1);
        } else {
            ESP_LOGW(TAG, "Không có PSK OTA trong NVS — xác thực OTA TẮT (cung cấp bằng nvs_set)");
        }
        nvs_close(nvs);
    } else {
        ESP_LOGW(TAG, "Không tìm thấy namespace NVS '%s' — xác thực OTA TẮT", OTA_NVS_NAMESPACE);
    }

    return ota_start_server(NULL);
}

esp_err_t ota_update_init_ex(void **out_server)
{
    return ota_start_server((httpd_handle_t *)out_server);
}
