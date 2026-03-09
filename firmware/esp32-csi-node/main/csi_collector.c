/**
 * @file csi_collector.c
 * @brief Thu thập dữ liệu CSI và tuần tự hóa khung nhị phân ADR-018.
 *
 * Đăng ký callback WiFi CSI của ESP-IDF và tuần tự hóa dữ liệu CSI đến
 * theo định dạng khung nhị phân ADR-018 để truyền qua UDP.
 *
 * ADR-029 extensions:
 *   - Bảng nhảy kênh cho cảm biến đa băng (channels 1/6/11 by default)
 *   - Nhảy kênh theo bộ đếm với khoảng dừng có thể cấu hình
 *   - Stub phát khung NDP cho cơ chế TX ưu tiên cảm biến
 */

#include "csi_collector.h"
#include "stream_sender.h"
#include "edge_processing.h"

#include <string.h>
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "sdkconfig.h"

static const char *TAG = "csi_collector";

static uint32_t s_sequence = 0;
static uint32_t s_cb_count = 0;
static uint32_t s_send_ok = 0;
static uint32_t s_send_fail = 0;
static uint32_t s_rate_skip = 0;

/**
 * Khoảng cách tối thiểu giữa các lần gửi UDP tính bằng micro giây.
 * Callback CSI có thể kích hoạt hàng trăm lần/giây trong chế độ promiscuous.
 * Giới hạn tốc độ gửi để tránh cạn kiệt bộ đệm gói lwIP (ENOMEM).
 * Mặc định: 20 ms = tốc độ gửi tối đa 50 Hz.
 */
#define CSI_MIN_SEND_INTERVAL_US  (20 * 1000)
static int64_t s_last_send_us = 0;

/* ---- ADR-029: Channel-hop state ---- */

/** Bảng nhảy kênh (nạp từ NVS khi khởi động hoặc qua set_hop_table). */
static uint8_t  s_hop_channels[CSI_HOP_CHANNELS_MAX] = {1, 6, 11, 36, 40, 44};

/** Số kênh hoạt động trong bảng nhảy. 1 = đơn kênh (không nhảy). */
static uint8_t  s_hop_count   = 1;

/** Thời gian dừng mỗi kênh tính bằng mili giây. */
static uint32_t s_dwell_ms    = 50;

/** Chỉ mục hiện tại trong s_hop_channels. */
static uint8_t  s_hop_index   = 0;

/** Handle bộ đếm nhảy định kỳ. NULL khi bộ đếm không chạy. */
static esp_timer_handle_t s_hop_timer = NULL;

/**
 * Serialize CSI data into ADR-018 binary frame format.
 *
 * Layout:
 *   [0..3]   Magic: 0xC5110001 (LE)
 *   [4]      Node ID
 *   [5]      Number of antennas (rx_ctrl.rx_ant + 1 if available, else 1)
 *   [6..7]   Number of subcarriers (LE u16) = len / (2 * n_antennas)
 *   [8..11]  Frequency MHz (LE u32) — derived from channel
 *   [12..15] Sequence number (LE u32)
 *   [16]     RSSI (i8)
 *   [17]     Noise floor (i8)
 *   [18..19] Reserved
 *   [20..]   I/Q data (raw bytes from ESP-IDF callback)
 */
size_t csi_serialize_frame(const wifi_csi_info_t *info, uint8_t *buf, size_t buf_len)
{
    if (info == NULL || buf == NULL || info->buf == NULL) {
        return 0;
    }

    uint8_t n_antennas = 1;  /* ESP32-S3 typically reports 1 antenna for CSI */
    uint16_t iq_len = (uint16_t)info->len;
    uint16_t n_subcarriers = iq_len / (2 * n_antennas);

    size_t frame_size = CSI_HEADER_SIZE + iq_len;
    if (frame_size > buf_len) {
        ESP_LOGW(TAG, "Bộ đệm quá nhỏ: cần %u, có %u", (unsigned)frame_size, (unsigned)buf_len);
        return 0;
    }

    /* Tính tần số từ số kênh */
    uint8_t channel = info->rx_ctrl.channel;
    uint32_t freq_mhz;
    if (channel >= 1 && channel <= 13) {
        freq_mhz = 2412 + (channel - 1) * 5;
    } else if (channel == 14) {
        freq_mhz = 2484;
    } else if (channel >= 36 && channel <= 177) {
        freq_mhz = 5000 + channel * 5;
    } else {
        freq_mhz = 0;
    }

    /* Số ma thuật (LE) */
    uint32_t magic = CSI_MAGIC;
    memcpy(&buf[0], &magic, 4);

    /* Mã nút */
    buf[4] = (uint8_t)CONFIG_CSI_NODE_ID;

    /* Số ăng-ten */
    buf[5] = n_antennas;

    /* Số sóng mang con (LE u16) */
    memcpy(&buf[6], &n_subcarriers, 2);

    /* Tần số MHz (LE u32) */
    memcpy(&buf[8], &freq_mhz, 4);

    /* Số thứ tự (LE u32) */
    uint32_t seq = s_sequence++;
    memcpy(&buf[12], &seq, 4);

    /* RSSI (i8) */
    buf[16] = (uint8_t)(int8_t)info->rx_ctrl.rssi;

    /* Mức nhiễu (i8) */
    buf[17] = (uint8_t)(int8_t)info->rx_ctrl.noise_floor;

    /* Dự phòng */
    buf[18] = 0;
    buf[19] = 0;

    /* Dữ liệu I/Q */
    memcpy(&buf[CSI_HEADER_SIZE], info->buf, iq_len);

    return frame_size;
}

/**
 * WiFi CSI callback — invoked by ESP-IDF when CSI data is available.
 */
static void wifi_csi_callback(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;
    s_cb_count++;

    if (s_cb_count <= 3 || (s_cb_count % 100) == 0) {
        ESP_LOGI(TAG, "CSI cb #%lu: độ_dài=%d rssi=%d kênh=%d",
                 (unsigned long)s_cb_count, info->len,
                 info->rx_ctrl.rssi, info->rx_ctrl.channel);
    }

    uint8_t frame_buf[CSI_MAX_FRAME_SIZE];
    size_t frame_len = csi_serialize_frame(info, frame_buf, sizeof(frame_buf));

    if (frame_len > 0) {
        /* Giới hạn tốc độ gửi UDP để tránh ENOMEM from lwIP pbuf exhaustion.
         * Trong chế độ promiscuous, callback CSI có thể kích hoạt 100-500+ lần/giây.
         * Pipeline cảm biến chỉ cần 20-50 Hz. */
        int64_t now = esp_timer_get_time();
        if ((now - s_last_send_us) >= CSI_MIN_SEND_INTERVAL_US) {
            int ret = stream_sender_send(frame_buf, frame_len);
            if (ret > 0) {
                s_send_ok++;
                s_last_send_us = now;
            } else {
                s_send_fail++;
                if (s_send_fail <= 5) {
                    ESP_LOGW(TAG, "gửi thất bại (lỗi #%lu)", (unsigned long)s_send_fail);
                }
            }
        } else {
            s_rate_skip++;
        }
    }

    /* ADR-039: Đưa I/Q thô vào bộ đệm vòng xử lý biên. */
    if (info->buf && info->len > 0) {
        edge_enqueue_csi((const uint8_t *)info->buf, (uint16_t)info->len,
                         (int8_t)info->rx_ctrl.rssi, info->rx_ctrl.channel);
    }
}

/**
 * Promiscuous mode callback — required for CSI to fire on all received frames.
 * We don't need the packet content, just the CSI triggered by reception.
 */
static void wifi_promiscuous_cb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    /* No-op: CSI callback is registered separately and fires in parallel. */
    (void)buf;
    (void)type;
}

void csi_collector_init(void)
{
    /* Bật chế độ promiscuous — required for reliable CSI callbacks.
     * Nếu không bật, CSI chỉ kích hoạt cho khung đến trạm này,
     * có thể rất hiếm trên mạng yên tĩnh. */
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(wifi_promiscuous_cb));

    wifi_promiscuous_filter_t filt = {
        .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA,
    };
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filt));

    ESP_LOGI(TAG, "Đã bật chế độ promiscuous để thu thập CSI");

    wifi_csi_config_t csi_config = {
        .lltf_en = true,
        .htltf_en = true,
        .stbc_htltf2_en = true,
        .ltf_merge_en = true,
        .channel_filter_en = false,
        .manu_scale = false,
        .shift = false,
    };

    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_callback, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    ESP_LOGI(TAG, "Đã khởi tạo thu thập CSI (mã_nút=%d, kênh=%d)",
             CONFIG_CSI_NODE_ID, CONFIG_CSI_WIFI_CHANNEL);
}

/* ---- ADR-029: Channel hopping ---- */

void csi_collector_set_hop_table(const uint8_t *channels, uint8_t hop_count, uint32_t dwell_ms)
{
    if (channels == NULL) {
        ESP_LOGW(TAG, "csi_collector_set_hop_table: danh sách kênh rỗng");
        return;
    }
    if (hop_count == 0 || hop_count > CSI_HOP_CHANNELS_MAX) {
        ESP_LOGW(TAG, "csi_collector_set_hop_table: hop_count=%u không hợp lệ (tối đa=%u)",
                 (unsigned)hop_count, (unsigned)CSI_HOP_CHANNELS_MAX);
        return;
    }
    if (dwell_ms < 10) {
        ESP_LOGW(TAG, "csi_collector_set_hop_table: dwell_ms=%lu quá nhỏ, giới hạn thành 10",
                 (unsigned long)dwell_ms);
        dwell_ms = 10;
    }

    memcpy(s_hop_channels, channels, hop_count);
    s_hop_count = hop_count;
    s_dwell_ms  = dwell_ms;
    s_hop_index = 0;

    ESP_LOGI(TAG, "Đã thiết lập bảng nhảy: %u kênh, dừng=%lu ms", (unsigned)hop_count,
             (unsigned long)dwell_ms);
    for (uint8_t i = 0; i < hop_count; i++) {
        ESP_LOGI(TAG, "  nhảy[%u] = kênh %u", (unsigned)i, (unsigned)channels[i]);
    }
}

void csi_hop_next_channel(void)
{
    if (s_hop_count <= 1) {
        /* Chế độ đơn kênh: không thao tác để tương thích ngược. */
        return;
    }

    s_hop_index = (s_hop_index + 1) % s_hop_count;
    uint8_t channel = s_hop_channels[s_hop_index];

    /*
     * esp_wifi_set_channel() changes the primary channel.
     * The second parameter is the secondary channel offset for HT40;
     * we use HT20 (no secondary) for sensing.
     */
    esp_err_t err = esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Nhảy kênh tới %u thất bại: %s", (unsigned)channel, esp_err_to_name(err));
    } else if ((s_cb_count % 200) == 0) {
        /* Log định kỳ xác nhận nhảy kênh đang hoạt động (không phải mỗi lần nhảy). */
        ESP_LOGI(TAG, "Đã nhảy tới kênh %u (chỉ mục %u/%u)",
                 (unsigned)channel, (unsigned)s_hop_index, (unsigned)s_hop_count);
    }
}

/**
 * Timer callback for channel hopping.
 * Called every s_dwell_ms milliseconds from the esp_timer context.
 */
static void hop_timer_cb(void *arg)
{
    (void)arg;
    csi_hop_next_channel();
}

void csi_collector_start_hop_timer(void)
{
    if (s_hop_count <= 1) {
        ESP_LOGI(TAG, "Chế độ đơn kênh: bộ đếm nhảy không khởi động");
        return;
    }

    if (s_hop_timer != NULL) {
        ESP_LOGW(TAG, "Bộ đếm nhảy đã đang chạy");
        return;
    }

    esp_timer_create_args_t timer_args = {
        .callback = hop_timer_cb,
        .arg      = NULL,
        .name     = "csi_hop",
    };

    esp_err_t err = esp_timer_create(&timer_args, &s_hop_timer);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Tạo bộ đếm nhảy thất bại: %s", esp_err_to_name(err));
        return;
    }

    uint64_t period_us = (uint64_t)s_dwell_ms * 1000;
    err = esp_timer_start_periodic(s_hop_timer, period_us);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Khởi động bộ đếm nhảy thất bại: %s", esp_err_to_name(err));
        esp_timer_delete(s_hop_timer);
        s_hop_timer = NULL;
        return;
    }

    ESP_LOGI(TAG, "Bộ đếm nhảy đã khởi động: chu kỳ=%lu ms, số kênh=%u",
             (unsigned long)s_dwell_ms, (unsigned)s_hop_count);
}

/* ---- ADR-029: NDP frame injection stub ---- */

esp_err_t csi_inject_ndp_frame(void)
{
    /*
     * TODO: Construct a proper 802.11 Null Data Packet frame.
     *
     * A real NDP is preamble-only (~24 us airtime, no payload) and is the
     * sensing-first TX mechanism described in ADR-029. For now we send a
     * minimal null-data frame as a placeholder so the API is wired up.
     *
     * Frame structure (IEEE 802.11 Null Data):
     *   FC (2) | Duration (2) | Addr1 (6) | Addr2 (6) | Addr3 (6) | SeqCtl (2)
     *   = 24 bytes total, no body, no FCS (hardware appends FCS).
     */
    uint8_t ndp_frame[24];
    memset(ndp_frame, 0, sizeof(ndp_frame));

    /* Frame Control: Type=Data (0x02), Subtype=Null (0x04) -> 0x0048 */
    ndp_frame[0] = 0x48;
    ndp_frame[1] = 0x00;

    /* Duration: 0 (let hardware fill) */

    /* Addr1 (destination): broadcast */
    memset(&ndp_frame[4], 0xFF, 6);

    /* Addr2 (source): will be overwritten by hardware with own MAC */

    /* Addr3 (BSSID): broadcast */
    memset(&ndp_frame[16], 0xFF, 6);

    esp_err_t err = esp_wifi_80211_tx(WIFI_IF_STA, ndp_frame, sizeof(ndp_frame), false);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Phát NDP thất bại: %s", esp_err_to_name(err));
    }

    return err;
}
