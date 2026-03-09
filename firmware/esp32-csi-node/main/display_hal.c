/**
 * @file display_hal.c
 * @brief ADR-045: HAL AMOLED QSPI SH8601 cho Waveshare ESP32-S3-Touch-AMOLED-1.8.
 *
 * Sử dụng esp_lcd_panel_io_spi ESP-IDF ở chế độ QSPI (quad_mode=true, lcd_cmd_bits=32).
 * Lớp panel_io xử lý mã hóa lệnh QSPI 0x02/0x32.
 *
 * Phần cứng: SH8601 368x448, cảm ứng FT3168, mở rộng I/O TCA9554 cho nguồn/reset.
 *
 * Gán chân (Waveshare ESP32-S3-Touch-AMOLED-1.8):
 *   QSPI: CS=12, CLK=11, D0=4, D1=5, D2=6, D3=7
 *   I2C:  SDA=15, SCL=14  (shared: touch FT3168 + TCA9554 expander)
 *   Touch INT=21
 */

#include "display_hal.h"
#include "sdkconfig.h"

#if CONFIG_DISPLAY_ENABLE

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_lcd_panel_io.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_heap_caps.h"

static const char *TAG = "disp_hal";

/* ---- Định Nghĩa Chân QSPI (bo Waveshare) ---- */
#define DISP_QSPI_CS       12
#define DISP_QSPI_CLK      11
#define DISP_QSPI_D0       4
#define DISP_QSPI_D1       5
#define DISP_QSPI_D2       6
#define DISP_QSPI_D3       7

/* ---- I2C (dùng chung: cảm ứng + mở rộng TCA9554) ---- */
#define I2C_SDA             15
#define I2C_SCL             14
#define TOUCH_INT_PIN       21
#define I2C_MASTER_NUM      I2C_NUM_0
#define I2C_MASTER_FREQ_HZ  400000

/* ---- Mở rộng I/O TCA9554 ---- */
#define TCA9554_ADDR        0x20
#define TCA9554_REG_OUTPUT  0x01
#define TCA9554_REG_CONFIG  0x03

/* ---- Bộ điều khiển cảm ứng FT3168 ---- */
#define FT3168_ADDR         0x38

/* ---- Kích thước màn hình ---- */
#define DISP_H_RES          368
#define DISP_V_RES          448

/* ---- Opcode QSPI (đóng gói trong lcd_cmd bits [31:24]) ---- */
#define LCD_OPCODE_WRITE_CMD   0x02
#define LCD_OPCODE_WRITE_COLOR 0x32

/* ---- Trạng thái ---- */
static esp_lcd_panel_io_handle_t s_io_handle = NULL;
static bool s_i2c_initialized = false;
static bool s_touch_initialized = false;

/* ---- Trợ giúp I2C ---- */

static esp_err_t i2c_write_reg(uint8_t dev_addr, uint8_t reg, const uint8_t *data, size_t len)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    if (data && len > 0) {
        i2c_master_write(cmd, data, len, true);
    }
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(I2C_MASTER_NUM, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return ret;
}

static esp_err_t i2c_read_reg(uint8_t dev_addr, uint8_t reg, uint8_t *data, size_t len)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_READ, true);
    i2c_master_read(cmd, data, len, I2C_MASTER_LAST_NACK);
    i2c_master_stop(cmd);
    esp_err_t ret = i2c_master_cmd_begin(I2C_MASTER_NUM, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return ret;
}

static esp_err_t init_i2c_bus(void)
{
    if (s_i2c_initialized) return ESP_OK;

    i2c_config_t i2c_cfg = {
        .mode             = I2C_MODE_MASTER,
        .sda_io_num       = I2C_SDA,
        .scl_io_num       = I2C_SCL,
        .sda_pullup_en    = GPIO_PULLUP_ENABLE,
        .scl_pullup_en    = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_MASTER_FREQ_HZ,
    };

    esp_err_t ret = i2c_param_config(I2C_MASTER_NUM, &i2c_cfg);
    if (ret != ESP_OK) return ret;

    ret = i2c_driver_install(I2C_MASTER_NUM, I2C_MODE_MASTER, 0, 0, 0);
    if (ret != ESP_OK) return ret;

    s_i2c_initialized = true;
    ESP_LOGI(TAG, "Khởi tạo bus I2C OK (SDA=%d, SCL=%d)", I2C_SDA, I2C_SCL);
    return ESP_OK;
}

/* ---- Mở rộng I/O TCA9554: toggle pins for display power/reset ---- */

static esp_err_t tca9554_init_display_power(void)
{
    /* Đặt chân 0, 1, 2 làm đầu ra */
    uint8_t cfg = 0xF8;
    esp_err_t ret = i2c_write_reg(TCA9554_ADDR, TCA9554_REG_CONFIG, &cfg, 1);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Không tìm thấy TCA9554 tại 0x%02X: %s", TCA9554_ADDR, esp_err_to_name(ret));
        return ret;
    }

    /* Đặt chân 0,1,2 LOW (trạng thái reset) */
    uint8_t out = 0x00;
    i2c_write_reg(TCA9554_ADDR, TCA9554_REG_OUTPUT, &out, 1);
    vTaskDelay(pdMS_TO_TICKS(200));

    /* Đặt chân 0,1,2 HIGH (bật nguồn + giải phóng reset) */
    out = 0x07;
    i2c_write_reg(TCA9554_ADDR, TCA9554_REG_OUTPUT, &out, 1);
    vTaskDelay(pdMS_TO_TICKS(200));

    ESP_LOGI(TAG, "Đã chuyển đổi nguồn/reset màn hình TCA9554");
    return ESP_OK;
}

/* ---- Trợ giúp Panel IO: gửi lệnh qua esp_lcd QSPI panel IO ---- */

static esp_err_t panel_write_cmd(uint8_t dcs_cmd, const void *data, size_t data_len)
{
    /* Đóng gói thành lcd_cmd 32-bit: [31:24]=opcode, [23:8]=dcs_cmd, [7:0]=0 */
    uint32_t lcd_cmd = ((uint32_t)LCD_OPCODE_WRITE_CMD << 24) | ((uint32_t)dcs_cmd << 8);
    return esp_lcd_panel_io_tx_param(s_io_handle, (int)lcd_cmd, data, data_len);
}

static esp_err_t panel_write_color(const void *color_data, size_t data_len)
{
    /* RAMWR (0x2C) đóng gói thành lcd_cmd 32-bit với opcode quad */
    uint32_t lcd_cmd = ((uint32_t)LCD_OPCODE_WRITE_COLOR << 24) | (0x2C << 8);
    return esp_lcd_panel_io_tx_color(s_io_handle, (int)lcd_cmd, color_data, data_len);
}

/* ---- Chuỗi khởi tạo SH8601 (từ tài liệu Waveshare) ---- */

typedef struct {
    uint8_t cmd;
    uint8_t data[4];
    uint8_t data_len;
    uint16_t delay_ms;
} sh8601_init_cmd_t;

static const sh8601_init_cmd_t sh8601_init_cmds[] = {
    {0x11, {0x00},                   0, 120},  /* Thoát ngủ + 120ms */
    {0x44, {0x01, 0xD1},             2, 0},    /* Vùng từng phần */
    {0x35, {0x00},                   1, 0},    /* Bật hiệu ứng xé hình */
    {0x53, {0x20},                   1, 10},   /* Ghi CTRL màn hình */
    {0x2A, {0x00, 0x00, 0x01, 0x6F}, 4, 0},   /* CASET: 0-367 */
    {0x2B, {0x00, 0x00, 0x01, 0xBF}, 4, 0},   /* RASET: 0-447 */
    {0x51, {0x00},                   1, 10},   /* Độ sáng: 0 */
    {0x29, {0x00},                   0, 10},   /* Bật màn hình */
    {0x51, {0xFF},                   1, 0},    /* Độ sáng: tối đa */
    {0x00, {0x00},                   0xFF, 0}, /* Lính canh kết thúc */
};

static esp_err_t send_init_sequence(void)
{
    for (int i = 0; sh8601_init_cmds[i].data_len != 0xFF; i++) {
        const sh8601_init_cmd_t *cmd = &sh8601_init_cmds[i];
        esp_err_t ret = panel_write_cmd(
            cmd->cmd,
            cmd->data_len > 0 ? cmd->data : NULL,
            cmd->data_len);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Lệnh 0x%02X thất bại: %s", cmd->cmd, esp_err_to_name(ret));
            return ret;
        }
        if (cmd->delay_ms > 0) {
            vTaskDelay(pdMS_TO_TICKS(cmd->delay_ms));
        }
    }
    return ESP_OK;
}

/* ---- API Công Khai ---- */

esp_err_t display_hal_init_panel(void)
{
    ESP_LOGI(TAG, "Đang khởi tạo Waveshare AMOLED 1.8\" (SH8601 368x448)...");

    /* Bước 1: Khởi tạo bus I2C */
    esp_err_t ret = init_i2c_bus();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo bus I2C thất bại");
        return ESP_ERR_NOT_FOUND;
    }

    /* Bước 2: Nguồn/reset màn hình TCA9554 (tùy chọn — chỉ có trên bo Waveshare) */
    ret = tca9554_init_display_power();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Không tìm thấy TCA9554 — giả định nguồn màn hình luôn bật (nối dây trực tiếp)");
        /* Tiếp tục không có TCA9554 — màn hình có thể được cấp nguồn trực tiếp */
    }

    /* Bước 3: Khởi tạo bus SPI */
    spi_bus_config_t bus_cfg = {
        .sclk_io_num     = DISP_QSPI_CLK,
        .data0_io_num    = DISP_QSPI_D0,
        .data1_io_num    = DISP_QSPI_D1,
        .data2_io_num    = DISP_QSPI_D2,
        .data3_io_num    = DISP_QSPI_D3,
        .max_transfer_sz = DISP_H_RES * DISP_V_RES * 2,
    };

    ret = spi_bus_initialize(SPI2_HOST, &bus_cfg, SPI_DMA_CH_AUTO);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Khởi tạo bus SPI thất bại: %s", esp_err_to_name(ret));
        return ESP_ERR_NOT_FOUND;
    }

    /* Bước 4: Tạo panel IO với chế độ QSPI */
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num       = -1,       /* Không có chân DC trong chế độ QSPI */
        .cs_gpio_num       = DISP_QSPI_CS,
        .pclk_hz           = 40 * 1000 * 1000,
        .lcd_cmd_bits      = 32,       /* Lệnh 32-bit: [opcode|dcs_cmd|0x00] */
        .lcd_param_bits    = 8,
        .spi_mode          = 0,
        .trans_queue_depth = 10,
        .flags = {
            .quad_mode = true,
        },
    };

    ret = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST, &io_config, &s_io_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Khởi tạo Panel IO thất bại: %s", esp_err_to_name(ret));
        spi_bus_free(SPI2_HOST);
        return ESP_ERR_NOT_FOUND;
    }
    ESP_LOGI(TAG, "Panel IO QSPI đã tạo (40MHz, chế độ quad)");

    /* Bước 5: Gửi chuỗi khởi tạo SH8601 */
    ret = send_init_sequence();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Chuỗi khởi tạo SH8601 thất bại");
        esp_lcd_panel_io_del(s_io_handle);
        spi_bus_free(SPI2_HOST);
        s_io_handle = NULL;
        return ESP_ERR_NOT_FOUND;
    }

    /* Bước 6: Vẽ mẫu thử — thanh xanh lam ở trên */
    ESP_LOGI(TAG, "Đang vẽ mẫu thử...");
    uint16_t *line_buf = heap_caps_malloc(DISP_H_RES * 2, MALLOC_CAP_DMA);
    if (line_buf) {
        uint8_t caset[4] = {0, 0, (DISP_H_RES - 1) >> 8, (DISP_H_RES - 1) & 0xFF};
        uint8_t raset[4] = {0, 0, (DISP_V_RES - 1) >> 8, (DISP_V_RES - 1) & 0xFF};
        panel_write_cmd(0x2A, caset, 4);
        panel_write_cmd(0x2B, raset, 4);

        for (int y = 0; y < DISP_V_RES; y++) {
            uint16_t color = (y < 30) ? 0x07FF : 0x0841;
            for (int x = 0; x < DISP_H_RES; x++) {
                line_buf[x] = color;
            }
            panel_write_color(line_buf, DISP_H_RES * 2);
        }
        free(line_buf);
        ESP_LOGI(TAG, "Đã vẽ mẫu thử");
    }

    ESP_LOGI(TAG, "Khởi tạo panel SH8601 OK (%dx%d)", DISP_H_RES, DISP_V_RES);
    return ESP_OK;
}

void display_hal_draw(int x_start, int y_start, int x_end, int y_end,
                      const void *color_data)
{
    if (!s_io_handle) return;

    /* SH8601 yêu cầu tọa độ chia hết cho 2 */
    x_start &= ~1;
    y_start &= ~1;
    if (x_end & 1) x_end++;
    if (y_end & 1) y_end++;
    if (x_end > DISP_H_RES) x_end = DISP_H_RES;
    if (y_end > DISP_V_RES) y_end = DISP_V_RES;

    uint8_t caset[4] = {
        (x_start >> 8) & 0xFF, x_start & 0xFF,
        ((x_end - 1) >> 8) & 0xFF, (x_end - 1) & 0xFF,
    };
    panel_write_cmd(0x2A, caset, 4);

    uint8_t raset[4] = {
        (y_start >> 8) & 0xFF, y_start & 0xFF,
        ((y_end - 1) >> 8) & 0xFF, (y_end - 1) & 0xFF,
    };
    panel_write_cmd(0x2B, raset, 4);

    size_t len = (x_end - x_start) * (y_end - y_start) * 2;
    panel_write_color(color_data, len);
}

esp_err_t display_hal_init_touch(void)
{
    ESP_LOGI(TAG, "Probing Bộ điều khiển cảm ứng FT3168...");

    if (!s_i2c_initialized) {
        esp_err_t ret = init_i2c_bus();
        if (ret != ESP_OK) return ESP_ERR_NOT_FOUND;
    }

    gpio_config_t int_cfg = {
        .pin_bit_mask = (1ULL << TOUCH_INT_PIN),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&int_cfg);

    uint8_t chip_id = 0;
    esp_err_t ret = i2c_read_reg(FT3168_ADDR, 0xA8, &chip_id, 1);
    if (ret != ESP_OK || chip_id == 0x00 || chip_id == 0xFF) {
        ESP_LOGW(TAG, "Không tìm thấy FT3168 (ret=%s, id=0x%02X)", esp_err_to_name(ret), chip_id);
        return ESP_ERR_NOT_FOUND;
    }

    s_touch_initialized = true;
    ESP_LOGI(TAG, "Khởi tạo cảm ứng FT3168 OK (chip_id=0x%02X)", chip_id);
    return ESP_OK;
}

bool display_hal_touch_read(uint16_t *x, uint16_t *y)
{
    if (!s_touch_initialized) return false;

    uint8_t buf[7] = {0};
    esp_err_t ret = i2c_read_reg(FT3168_ADDR, 0x01, buf, 7);
    if (ret != ESP_OK) return false;

    uint8_t num_points = buf[1];
    if (num_points == 0 || num_points > 2) return false;

    *x = ((buf[2] & 0x0F) << 8) | buf[3];
    *y = ((buf[4] & 0x0F) << 8) | buf[5];
    return true;
}

void display_hal_set_brightness(uint8_t percent)
{
    if (!s_io_handle) return;
    if (percent > 100) percent = 100;
    uint8_t val = (uint8_t)((uint32_t)percent * 255 / 100);
    panel_write_cmd(0x51, &val, 1);
}

#endif /* CONFIG_DISPLAY_ENABLE */
