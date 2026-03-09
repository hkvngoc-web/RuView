/**
 * @file edge_processing.c
 * @brief ADR-039 Trí Tuệ Biên — đường ống xử lý CSI hai nhân.
 *
 * Nhân 0 (tác vụ WiFi): Đẩy khung CSI thô vào bộ đệm vòng SPSC không khóa.
 * Nhân 1 (tác vụ DSP):  Lấy khung ra, chạy đường ống xử lý tín hiệu:
 *   1. Trích xuất pha từ cặp I/Q
 *   2. Mở gói pha (pha liên tục)
 *   3. Theo dõi phương sai Welford theo từng sóng mang phụ
 *   4. Chọn Top-K sóng mang phụ theo phương sai
 *   5. Biquad IIR thông dải → nhịp thở (0.1-0.5 Hz), nhịp tim (0.8-2.0 Hz)
 *   6. Ước lượng BPM bằng cắt zero
 *   7. Phát hiện hiện diện (ngưỡng thích ứng hoặc cố định)
 *   8. Phát hiện ngã (gia tốc pha)
 *   9. Sinh hiệu đa người qua phân nhóm sóng mang phụ
 *  10. Nén delta (XOR + RLE) để giảm băng thông
 *  11. Phát gói sinh hiệu (magic 0xC5110002)
 */

#include "edge_processing.h"
#include "wasm_runtime.h"
#include "stream_sender.h"

#include <math.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"

static const char *TAG = "edge_proc";

/* ======================================================================
 * Bộ Đệm Vòng SPSC (không khóa, một-sản-xuất một-tiêu-thụ)
 * ====================================================================== */

static edge_ring_buf_t s_ring;

static inline bool ring_push(const uint8_t *iq, uint16_t len,
                             int8_t rssi, uint8_t channel)
{
    uint32_t next = (s_ring.head + 1) % EDGE_RING_SLOTS;
    if (next == s_ring.tail) {
        return false;  /* Đầy — bỏ khung. */
    }

    edge_ring_slot_t *slot = &s_ring.slots[s_ring.head];
    uint16_t copy_len = (len > EDGE_MAX_IQ_BYTES) ? EDGE_MAX_IQ_BYTES : len;
    memcpy(slot->iq_data, iq, copy_len);
    slot->iq_len = copy_len;
    slot->rssi = rssi;
    slot->channel = channel;
    slot->timestamp_us = (uint32_t)(esp_timer_get_time() & 0xFFFFFFFF);

    /* Rào bộ nhớ: đảm bảo dữ liệu khe hiển thị trước khi tiến head. */
    __sync_synchronize();
    s_ring.head = next;
    return true;
}

static inline bool ring_pop(edge_ring_slot_t *out)
{
    if (s_ring.tail == s_ring.head) {
        return false;  /* Trống. */
    }

    memcpy(out, &s_ring.slots[s_ring.tail], sizeof(edge_ring_slot_t));

    __sync_synchronize();
    s_ring.tail = (s_ring.tail + 1) % EDGE_RING_SLOTS;
    return true;
}

/* ======================================================================
 * Bộ Lọc Biquad IIR
 * ====================================================================== */

/**
 * Thiết kế biquad thông dải Butterworth bậc 2.
 *
 * @param bq   Trạng thái biquad đầu ra.
 * @param fs   Tần số lấy mẫu (Hz).
 * @param f_lo Tần số cắt thấp (Hz).
 * @param f_hi Tần số cắt cao (Hz).
 */
static void biquad_bandpass_design(edge_biquad_t *bq, float fs,
                                   float f_lo, float f_hi)
{
    float w0 = 2.0f * M_PI * (f_lo + f_hi) / 2.0f / fs;
    float bw = 2.0f * M_PI * (f_hi - f_lo) / fs;
    float alpha = sinf(w0) * sinhf(logf(2.0f) / 2.0f * bw / sinf(w0));

    float a0_inv = 1.0f / (1.0f + alpha);
    bq->b0 =  alpha * a0_inv;
    bq->b1 =  0.0f;
    bq->b2 = -alpha * a0_inv;
    bq->a1 = -2.0f * cosf(w0) * a0_inv;
    bq->a2 =  (1.0f - alpha) * a0_inv;

    bq->x1 = bq->x2 = 0.0f;
    bq->y1 = bq->y2 = 0.0f;
}

static inline float biquad_process(edge_biquad_t *bq, float x)
{
    float y = bq->b0 * x + bq->b1 * bq->x1 + bq->b2 * bq->x2
            - bq->a1 * bq->y1 - bq->a2 * bq->y2;
    bq->x2 = bq->x1;
    bq->x1 = x;
    bq->y2 = bq->y1;
    bq->y1 = y;
    return y;
}

/* ======================================================================
 * Trích Xuất và Mở Gói Pha
 * ====================================================================== */

/** Trích xuất pha (radian) từ cặp I/Q tại offset byte. */
static inline float extract_phase(const uint8_t *iq, uint16_t idx)
{
    int8_t i_val = (int8_t)iq[idx * 2];
    int8_t q_val = (int8_t)iq[idx * 2 + 1];
    return atan2f((float)q_val, (float)i_val);
}

/** Mở gói pha để duy trì tính liên tục (tránh nhảy 2*pi). */
static inline float unwrap_phase(float prev, float curr)
{
    float diff = curr - prev;
    if (diff > M_PI)       diff -= 2.0f * M_PI;
    else if (diff < -M_PI) diff += 2.0f * M_PI;
    return prev + diff;
}

/* ======================================================================
 * Thống Kê Chạy Welford
 * ====================================================================== */

static inline void welford_reset(edge_welford_t *w)
{
    w->mean = 0.0;
    w->m2   = 0.0;
    w->count = 0;
}

static inline void welford_update(edge_welford_t *w, double x)
{
    w->count++;
    double delta = x - w->mean;
    w->mean += delta / (double)w->count;
    double delta2 = x - w->mean;
    w->m2 += delta * delta2;
}

static inline double welford_variance(const edge_welford_t *w)
{
    return (w->count > 1) ? (w->m2 / (double)(w->count - 1)) : 0.0;
}

/* ======================================================================
 * Ước Lượng BPM Bằng Cắt Zero
 * ====================================================================== */

/**
 * Ước lượng BPM từ tín hiệu đã lọc sử dụng cắt zero dương.
 *
 * @param history     Bộ đệm tín hiệu (pha đã lọc).
 * @param len         Số lượng mẫu.
 * @param sample_rate Tốc độ lấy mẫu tính bằng Hz.
 * @return BPM ước lượng, hoặc 0 nếu không đủ điểm cắt.
 */
static float estimate_bpm_zero_crossing(const float *history, uint16_t len,
                                        float sample_rate)
{
    if (len < 4) return 0.0f;

    uint16_t crossings[128];
    uint16_t n_cross = 0;

    for (uint16_t i = 1; i < len && n_cross < 128; i++) {
        if (history[i - 1] <= 0.0f && history[i] > 0.0f) {
            crossings[n_cross++] = i;
        }
    }

    if (n_cross < 2) return 0.0f;

    /* Chu kỳ trung bình từ các điểm cắt liên tiếp. */
    float total_period = 0.0f;
    for (uint16_t i = 1; i < n_cross; i++) {
        total_period += (float)(crossings[i] - crossings[i - 1]);
    }
    float avg_period_samples = total_period / (float)(n_cross - 1);

    if (avg_period_samples < 1.0f) return 0.0f;

    float freq_hz = sample_rate / avg_period_samples;
    return freq_hz * 60.0f;  /* Hz sang BPM. */
}

/* ======================================================================
 * Trạng Thái Đường Ống DSP
 * ====================================================================== */

/** Cấu hình xử lý biên. */
static edge_config_t s_cfg;

/** Phương sai chạy theo sóng mang phụ (cho chọn top-K). */
static edge_welford_t s_subcarrier_var[EDGE_MAX_SUBCARRIERS];

/** Pha trước đó theo sóng mang phụ (để mở gói). */
static float s_prev_phase[EDGE_MAX_SUBCARRIERS];
static bool  s_phase_initialized;

/** Chỉ số sóng mang phụ Top-K (sắp xếp theo phương sai, giảm dần). */
static uint8_t s_top_k[EDGE_TOP_K];
static uint8_t s_top_k_count;

/** Lịch sử pha cho sóng mang phụ chính (phương sai cao nhất). */
static float s_phase_history[EDGE_PHASE_HISTORY_LEN];
static uint16_t s_history_len;
static uint16_t s_history_idx;

/** Bộ lọc biquad cho nhịp thở và nhịp tim. */
static edge_biquad_t s_bq_breathing;
static edge_biquad_t s_bq_heartrate;

/** Lịch sử tín hiệu đã lọc cho ước lượng BPM. */
static float s_breathing_filtered[EDGE_PHASE_HISTORY_LEN];
static float s_heartrate_filtered[EDGE_PHASE_HISTORY_LEN];

/** Trạng thái sinh hiệu mới nhất. */
static float    s_breathing_bpm;
static float    s_heartrate_bpm;
static float    s_motion_energy;
static float    s_presence_score;
static bool     s_presence_detected;
static bool     s_fall_detected;
static int8_t   s_latest_rssi;
static uint32_t s_frame_count;

/** Vận tốc pha trước đó cho phát hiện ngã (gia tốc). */
static float s_prev_phase_velocity;

/** Trạng thái hiệu chuẩn thích ứng. */
static bool     s_calibrated;
static float    s_calib_sum;
static float    s_calib_sum_sq;
static uint32_t s_calib_count;
static float    s_adaptive_threshold;

/** Nhãn thời gian gửi sinh hiệu cuối. */
static int64_t s_last_vitals_send_us;

/** Trạng thái nén delta. */
static uint8_t s_prev_iq[EDGE_MAX_IQ_BYTES];
static uint16_t s_prev_iq_len;
static bool s_has_prev_iq;

/** Trạng thái sinh hiệu đa người. */
static edge_person_vitals_t s_persons[EDGE_MAX_PERSONS];
static edge_biquad_t s_person_bq_br[EDGE_MAX_PERSONS];
static edge_biquad_t s_person_bq_hr[EDGE_MAX_PERSONS];
static float s_person_br_filt[EDGE_MAX_PERSONS][EDGE_PHASE_HISTORY_LEN];
static float s_person_hr_filt[EDGE_MAX_PERSONS][EDGE_PHASE_HISTORY_LEN];

/** Gói sinh hiệu mới nhất (an toàn luồng qua bản sao volatile). */
static volatile edge_vitals_pkt_t s_latest_pkt;
static volatile bool s_pkt_valid;

/* ======================================================================
 * Chọn Sóng Mang Phụ Top-K
 * ====================================================================== */

/**
 * Chọn sóng mang phụ top-K theo phương sai (giảm dần).
 * Sử dụng sắp xếp chèn từng phần — O(n*K), phù hợp cho n <= 128.
 */
static void update_top_k(uint16_t n_subcarriers)
{
    uint8_t k = s_cfg.top_k_count;
    if (k > EDGE_TOP_K) k = EDGE_TOP_K;
    if (k > n_subcarriers) k = (uint8_t)n_subcarriers;

    /* Chọn đơn giản: tìm K phương sai lớn nhất. */
    bool used[EDGE_MAX_SUBCARRIERS];
    memset(used, 0, sizeof(used));

    for (uint8_t ki = 0; ki < k; ki++) {
        double best_var = -1.0;
        uint8_t best_idx = 0;

        for (uint16_t sc = 0; sc < n_subcarriers; sc++) {
            if (!used[sc]) {
                double v = welford_variance(&s_subcarrier_var[sc]);
                if (v > best_var) {
                    best_var = v;
                    best_idx = (uint8_t)sc;
                }
            }
        }

        s_top_k[ki] = best_idx;
        used[best_idx] = true;
    }

    s_top_k_count = k;
}

/* ======================================================================
 * Hiệu Chuẩn Hiện Diện Thích Ứng
 * ====================================================================== */

static void calibration_update(float motion)
{
    if (s_calibrated) return;

    s_calib_sum += motion;
    s_calib_sum_sq += motion * motion;
    s_calib_count++;

    if (s_calib_count >= EDGE_CALIB_FRAMES) {
        float mean = s_calib_sum / (float)s_calib_count;
        float var = (s_calib_sum_sq / (float)s_calib_count) - (mean * mean);
        float sigma = (var > 0.0f) ? sqrtf(var) : 0.001f;

        s_adaptive_threshold = mean + EDGE_CALIB_SIGMA_MULT * sigma;
        if (s_adaptive_threshold < 0.01f) {
            s_adaptive_threshold = 0.01f;
        }

        s_calibrated = true;
        ESP_LOGI(TAG, "Hiệu chuẩn thích ứng hoàn tất: mean=%.4f sigma=%.4f "
                 "ngưỡng=%.4f (từ %lu khung)",
                 mean, sigma, s_adaptive_threshold,
                 (unsigned long)s_calib_count);
    }
}

/* ======================================================================
 * Nén Delta (XOR + RLE)
 * ====================================================================== */

/**
 * Nén delta dữ liệu I/Q so với khung trước.
 * Định dạng: [byte XOR], sau đó mã hóa RLE.
 *
 * @param curr       Dữ liệu I/Q hiện tại.
 * @param len        Độ dài dữ liệu I/Q.
 * @param out        Bộ đệm nén đầu ra.
 * @param out_max    Kích thước tối đa bộ đệm đầu ra.
 * @return Kích thước nén, hoặc 0 nếu nén sẽ tăng kích thước dữ liệu.
 */
static uint16_t delta_compress(const uint8_t *curr, uint16_t len,
                               uint8_t *out, uint16_t out_max)
{
    if (!s_has_prev_iq || len != s_prev_iq_len || len == 0) {
        return 0;
    }

    /* Delta XOR. */
    uint8_t xor_buf[EDGE_MAX_IQ_BYTES];
    for (uint16_t i = 0; i < len; i++) {
        xor_buf[i] = curr[i] ^ s_prev_iq[i];
    }

    /* Mã hóa RLE: cặp [giá trị, số lượng].
     * Nếu số lượng > 255, phát nhiều cặp. */
    uint16_t out_idx = 0;

    uint16_t i = 0;
    while (i < len) {
        uint8_t val = xor_buf[i];
        uint16_t run = 1;
        while (i + run < len && xor_buf[i + run] == val && run < 255) {
            run++;
        }

        if (out_idx + 2 > out_max) return 0;  /* Sẽ tràn bộ đệm. */
        out[out_idx++] = val;
        out[out_idx++] = (uint8_t)run;
        i += run;
    }

    /* Chỉ dùng nén nếu thực sự tiết kiệm dung lượng. */
    if (out_idx >= len) {
        return 0;
    }

    return out_idx;
}

/**
 * Gửi khung CSI đã nén (magic 0xC5110003).
 *
 * Header:
 *   [0..3]   Magic 0xC5110003 (LE)
 *   [4]      Node ID
 *   [5]      Channel
 *   [6..7]   Original I/Q length (LE u16)
 *   [8..9]   Compressed length (LE u16)
 *   [10..]   Compressed data
 */
static void send_compressed_frame(const uint8_t *iq_data, uint16_t iq_len,
                                  uint8_t channel)
{
    uint8_t comp_buf[EDGE_MAX_IQ_BYTES];
    uint16_t comp_len = delta_compress(iq_data, iq_len,
                                       comp_buf, sizeof(comp_buf));
    if (comp_len == 0) {
        /* Nén không hiệu quả — bỏ qua gửi phiên bản nén. */
        goto store_prev;
    }

    /* Tạo gói khung nén. */
    uint16_t pkt_size = 10 + comp_len;
    uint8_t pkt[10 + EDGE_MAX_IQ_BYTES];

    uint32_t magic = EDGE_COMPRESSED_MAGIC;
    memcpy(&pkt[0], &magic, 4);

#ifdef CONFIG_CSI_NODE_ID
    pkt[4] = (uint8_t)CONFIG_CSI_NODE_ID;
#else
    pkt[4] = 0;
#endif
    pkt[5] = channel;
    memcpy(&pkt[6], &iq_len, 2);
    memcpy(&pkt[8], &comp_len, 2);
    memcpy(&pkt[10], comp_buf, comp_len);

    stream_sender_send(pkt, pkt_size);

    ESP_LOGD(TAG, "Khung nén: %u → %u byte (giảm %.0f%%)",
             iq_len, comp_len,
             (1.0f - (float)comp_len / (float)iq_len) * 100.0f);

store_prev:
    /* Lưu khung hiện tại làm tham chiếu cho delta tiếp theo. */
    memcpy(s_prev_iq, iq_data, iq_len);
    s_prev_iq_len = iq_len;
    s_has_prev_iq = true;
}

/* ======================================================================
 * Sinh Hiệu Đa Người
 * ====================================================================== */

/**
 * Cập nhật sinh hiệu đa người bằng cách gán sóng mang phụ top-K cho các nhóm người.
 *
 * Chiến lược phân chia: sóng mang phụ top-K được chia đều cho
 * tối đa EDGE_MAX_PERSONS nhóm. Mỗi nhóm theo dõi
 * lịch sử pha và ước lượng BPM độc lập.
 */
static void update_multi_person_vitals(const uint8_t *iq_data, uint16_t n_sc,
                                       float sample_rate)
{
    if (s_top_k_count < 2) return;

    /* Xác định số người hoạt động dựa trên sóng mang phụ khả dụng. */
    uint8_t n_persons = s_top_k_count / 2;
    if (n_persons > EDGE_MAX_PERSONS) n_persons = EDGE_MAX_PERSONS;
    if (n_persons < 1) n_persons = 1;

    uint8_t subs_per_person = s_top_k_count / n_persons;

    for (uint8_t p = 0; p < n_persons; p++) {
        edge_person_vitals_t *pv = &s_persons[p];
        pv->active = true;
        pv->subcarrier_idx = s_top_k[p * subs_per_person];

        /* Pha trung bình qua nhóm sóng mang phụ của người này. */
        float avg_phase = 0.0f;
        uint8_t count = 0;
        for (uint8_t s = 0; s < subs_per_person; s++) {
            uint8_t sc_idx = s_top_k[p * subs_per_person + s];
            if (sc_idx < n_sc) {
                avg_phase += extract_phase(iq_data, sc_idx);
                count++;
            }
        }
        if (count > 0) avg_phase /= (float)count;

        /* Mở gói và lưu vào lịch sử. */
        if (pv->history_len > 0) {
            uint16_t prev_idx = (pv->history_idx + EDGE_PHASE_HISTORY_LEN - 1)
                                % EDGE_PHASE_HISTORY_LEN;
            avg_phase = unwrap_phase(pv->phase_history[prev_idx], avg_phase);
        }

        pv->phase_history[pv->history_idx] = avg_phase;
        pv->history_idx = (pv->history_idx + 1) % EDGE_PHASE_HISTORY_LEN;
        if (pv->history_len < EDGE_PHASE_HISTORY_LEN) pv->history_len++;

        /* Lọc và ước lượng BPM. */
        float br_val = biquad_process(&s_person_bq_br[p], avg_phase);
        float hr_val = biquad_process(&s_person_bq_hr[p], avg_phase);

        uint16_t idx = (pv->history_idx + EDGE_PHASE_HISTORY_LEN - 1)
                       % EDGE_PHASE_HISTORY_LEN;
        s_person_br_filt[p][idx] = br_val;
        s_person_hr_filt[p][idx] = hr_val;

        /* Ước lượng BPM khi có đủ lịch sử. */
        if (pv->history_len >= 64) {
            /* Tạo bộ đệm liên tục cho cắt zero. */
            float br_buf[EDGE_PHASE_HISTORY_LEN];
            float hr_buf[EDGE_PHASE_HISTORY_LEN];
            uint16_t buf_len = pv->history_len;

            for (uint16_t i = 0; i < buf_len; i++) {
                uint16_t ri = (pv->history_idx + EDGE_PHASE_HISTORY_LEN
                               - buf_len + i) % EDGE_PHASE_HISTORY_LEN;
                br_buf[i] = s_person_br_filt[p][ri];
                hr_buf[i] = s_person_hr_filt[p][ri];
            }

            float br = estimate_bpm_zero_crossing(br_buf, buf_len, sample_rate);
            float hr = estimate_bpm_zero_crossing(hr_buf, buf_len, sample_rate);

            /* Giới hạn hợp lý. */
            if (br >= 6.0f && br <= 40.0f) pv->breathing_bpm = br;
            if (hr >= 40.0f && hr <= 180.0f) pv->heartrate_bpm = hr;
        }
    }

    /* Đánh dấu những người còn lại là không hoạt động. */
    for (uint8_t p = n_persons; p < EDGE_MAX_PERSONS; p++) {
        s_persons[p].active = false;
    }
}

/* ======================================================================
 * Gửi Gói Sinh Hiệu
 * ====================================================================== */

static void send_vitals_packet(void)
{
    edge_vitals_pkt_t pkt;
    memset(&pkt, 0, sizeof(pkt));

    pkt.magic = EDGE_VITALS_MAGIC;
#ifdef CONFIG_CSI_NODE_ID
    pkt.node_id = (uint8_t)CONFIG_CSI_NODE_ID;
#else
    pkt.node_id = 0;
#endif

    pkt.flags = 0;
    if (s_presence_detected) pkt.flags |= 0x01;
    if (s_fall_detected)     pkt.flags |= 0x02;
    if (s_motion_energy > 0.01f) pkt.flags |= 0x04;

    pkt.breathing_rate = (uint16_t)(s_breathing_bpm * 100.0f);
    pkt.heartrate = (uint32_t)(s_heartrate_bpm * 10000.0f);
    pkt.rssi = s_latest_rssi;

    /* Đếm số người hoạt động. */
    uint8_t n_active = 0;
    for (uint8_t p = 0; p < EDGE_MAX_PERSONS; p++) {
        if (s_persons[p].active) n_active++;
    }
    pkt.n_persons = n_active;

    pkt.motion_energy = s_motion_energy;
    pkt.presence_score = s_presence_score;
    pkt.timestamp_ms = (uint32_t)(esp_timer_get_time() / 1000);

    /* Cập nhật bản sao an toàn luồng. */
    s_latest_pkt = pkt;
    s_pkt_valid = true;

    /* Gửi qua UDP. */
    stream_sender_send((const uint8_t *)&pkt, sizeof(pkt));
}

/* ======================================================================
 * Đường Ống DSP Chính (chạy trên Nhân 1)
 * ====================================================================== */

static void process_frame(const edge_ring_slot_t *slot)
{
    uint16_t n_subcarriers = slot->iq_len / 2;
    if (n_subcarriers == 0 || n_subcarriers > EDGE_MAX_SUBCARRIERS) return;

    s_frame_count++;
    s_latest_rssi = slot->rssi;

    /* Tốc độ lấy mẫu CSI giả định (~20 Hz cho ESP32 CSI thông thường). */
    const float sample_rate = 20.0f;

    /* --- Bước 1-2: Trích xuất pha + mở gói theo sóng mang phụ --- */
    float phases[EDGE_MAX_SUBCARRIERS];
    for (uint16_t sc = 0; sc < n_subcarriers; sc++) {
        float raw_phase = extract_phase(slot->iq_data, sc);

        if (s_phase_initialized) {
            phases[sc] = unwrap_phase(s_prev_phase[sc], raw_phase);
        } else {
            phases[sc] = raw_phase;
        }
        s_prev_phase[sc] = phases[sc];
    }
    s_phase_initialized = true;

    /* --- Bước 3: Cập nhật phương sai Welford theo sóng mang phụ --- */
    for (uint16_t sc = 0; sc < n_subcarriers; sc++) {
        welford_update(&s_subcarrier_var[sc], (double)phases[sc]);
    }

    /* --- Bước 4: Chọn Top-K (mỗi 100 khung để phân bổ chi phí) --- */
    if ((s_frame_count % 100) == 1 || s_top_k_count == 0) {
        update_top_k(n_subcarriers);
    }

    if (s_top_k_count == 0) return;

    /* --- Bước 5: Pha của sóng mang phụ chính (phương sai cao nhất) --- */
    float primary_phase = phases[s_top_k[0]];

    /* Lưu vào bộ đệm vòng lịch sử pha. */
    s_phase_history[s_history_idx] = primary_phase;
    s_history_idx = (s_history_idx + 1) % EDGE_PHASE_HISTORY_LEN;
    if (s_history_len < EDGE_PHASE_HISTORY_LEN) s_history_len++;

    /* --- Bước 6: Lọc thông dải biquad --- */
    float br_val = biquad_process(&s_bq_breathing, primary_phase);
    float hr_val = biquad_process(&s_bq_heartrate, primary_phase);

    uint16_t filt_idx = (s_history_idx + EDGE_PHASE_HISTORY_LEN - 1)
                        % EDGE_PHASE_HISTORY_LEN;
    s_breathing_filtered[filt_idx] = br_val;
    s_heartrate_filtered[filt_idx] = hr_val;

    /* --- Bước 7: Ước lượng BPM (cắt zero) --- */
    if (s_history_len >= 64) {
        /* Tạo bộ đệm liên tục từ vòng. */
        float br_buf[EDGE_PHASE_HISTORY_LEN];
        float hr_buf[EDGE_PHASE_HISTORY_LEN];
        uint16_t buf_len = s_history_len;

        for (uint16_t i = 0; i < buf_len; i++) {
            uint16_t ri = (s_history_idx + EDGE_PHASE_HISTORY_LEN
                           - buf_len + i) % EDGE_PHASE_HISTORY_LEN;
            br_buf[i] = s_breathing_filtered[ri];
            hr_buf[i] = s_heartrate_filtered[ri];
        }

        float br_bpm = estimate_bpm_zero_crossing(br_buf, buf_len, sample_rate);
        float hr_bpm = estimate_bpm_zero_crossing(hr_buf, buf_len, sample_rate);

        /* Giới hạn hợp lý: nhịp thở 6-40 BPM, nhịp tim 40-180 BPM. */
        if (br_bpm >= 6.0f && br_bpm <= 40.0f) s_breathing_bpm = br_bpm;
        if (hr_bpm >= 40.0f && hr_bpm <= 180.0f) s_heartrate_bpm = hr_bpm;
    }

    /* --- Bước 8: Năng lượng chuyển động (phương sai pha gần đây) --- */
    if (s_history_len >= 10) {
        float sum = 0.0f, sum2 = 0.0f;
        uint16_t window = (s_history_len < 20) ? s_history_len : 20;
        for (uint16_t i = 0; i < window; i++) {
            uint16_t ri = (s_history_idx + EDGE_PHASE_HISTORY_LEN
                           - window + i) % EDGE_PHASE_HISTORY_LEN;
            float v = s_phase_history[ri];
            sum += v;
            sum2 += v * v;
        }
        float mean = sum / (float)window;
        s_motion_energy = (sum2 / (float)window) - (mean * mean);
        if (s_motion_energy < 0.0f) s_motion_energy = 0.0f;
    }

    /* --- Bước 9: Phát hiện hiện diện --- */
    s_presence_score = s_motion_energy;

    /* Hiệu chuẩn thích ứng: học mức nhiễu môi trường từ N khung đầu. */
    if (!s_calibrated && s_cfg.presence_thresh == 0.0f) {
        calibration_update(s_motion_energy);
    }

    float threshold = s_cfg.presence_thresh;
    if (threshold == 0.0f && s_calibrated) {
        threshold = s_adaptive_threshold;
    } else if (threshold == 0.0f) {
        threshold = 0.05f;  /* Mặc định cho đến khi hiệu chuẩn. */
    }
    s_presence_detected = (s_presence_score > threshold);

    /* --- Step 10: Phát hiện ngã (gia tốc pha) --- */
    if (s_history_len >= 3) {
        uint16_t i0 = (s_history_idx + EDGE_PHASE_HISTORY_LEN - 1) % EDGE_PHASE_HISTORY_LEN;
        uint16_t i1 = (s_history_idx + EDGE_PHASE_HISTORY_LEN - 2) % EDGE_PHASE_HISTORY_LEN;
        float velocity = s_phase_history[i0] - s_phase_history[i1];
        float accel = fabsf(velocity - s_prev_phase_velocity);
        s_prev_phase_velocity = velocity;

        s_fall_detected = (accel > s_cfg.fall_thresh);
        if (s_fall_detected) {
            ESP_LOGW(TAG, "Phát hiện ngã! gia_tốc=%.4f > ngưỡng=%.4f",
                     accel, s_cfg.fall_thresh);
        }
    }

    /* --- Bước 11: Sinh hiệu đa người --- */
    update_multi_person_vitals(slot->iq_data, n_subcarriers, sample_rate);

    /* --- Bước 12: Nén delta --- */
    if (s_cfg.tier >= 2) {
        send_compressed_frame(slot->iq_data, slot->iq_len, slot->channel);
    }

    /* --- Bước 13: Gửi gói sinh hiệu theo khoảng cách cấu hình --- */
    int64_t now_us = esp_timer_get_time();
    int64_t interval_us = (int64_t)s_cfg.vital_interval_ms * 1000;
    if ((now_us - s_last_vitals_send_us) >= interval_us) {
        send_vitals_packet();
        s_last_vitals_send_us = now_us;

        if ((s_frame_count % 200) == 0) {
            ESP_LOGI(TAG, "Sinh hiệu: thở=%.1f tim=%.1f chuyển_động=%.4f hiện_diện=%s "
                     "ngã=%s người=%u khung=%lu",
                     s_breathing_bpm, s_heartrate_bpm, s_motion_energy,
                     s_presence_detected ? "YES" : "no",
                     s_fall_detected ? "YES" : "no",
                     (unsigned)s_latest_pkt.n_persons,
                     (unsigned long)s_frame_count);
        }
    }

    /* --- Bước 14 (ADR-040): Gửi đến module WASM --- */
    if (s_cfg.tier >= 2 && s_pkt_valid) {
        /* Trích xuất biên độ từ I/Q cho WASM host API. */
        float amplitudes[EDGE_MAX_SUBCARRIERS];
        for (uint16_t sc = 0; sc < n_subcarriers; sc++) {
            int8_t i_val = (int8_t)slot->iq_data[sc * 2];
            int8_t q_val = (int8_t)slot->iq_data[sc * 2 + 1];
            amplitudes[sc] = sqrtf((float)(i_val * i_val + q_val * q_val));
        }

        /* Tạo mảng phương sai từ trạng thái Welford. */
        float variances[EDGE_MAX_SUBCARRIERS];
        for (uint16_t sc = 0; sc < n_subcarriers; sc++) {
            variances[sc] = (float)welford_variance(&s_subcarrier_var[sc]);
        }

        wasm_runtime_on_frame(phases, amplitudes, variances,
                              n_subcarriers,
                              (const edge_vitals_pkt_t *)&s_latest_pkt);
    }
}

/* ======================================================================
 * Tác Vụ Xử Lý Biên (ghim vào Nhân 1)
 * ====================================================================== */

static void edge_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "Tác vụ DSP biên đã khởi động trên nhân %d (tầng=%u)",
             xPortGetCoreID(), s_cfg.tier);

    edge_ring_slot_t slot;

    while (1) {
        if (ring_pop(&slot)) {
            process_frame(&slot);
        } else {
            /* Không có khung — nhường CPU ngắn. */
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    }
}

/* ======================================================================
 * API Công Khai
 * ====================================================================== */

bool edge_enqueue_csi(const uint8_t *iq_data, uint16_t iq_len,
                      int8_t rssi, uint8_t channel)
{
    return ring_push(iq_data, iq_len, rssi, channel);
}

bool edge_get_vitals(edge_vitals_pkt_t *pkt)
{
    if (!s_pkt_valid || pkt == NULL) return false;
    memcpy(pkt, (const void *)&s_latest_pkt, sizeof(edge_vitals_pkt_t));
    return true;
}

void edge_get_multi_person(edge_person_vitals_t *persons, uint8_t *n_active)
{
    uint8_t active = 0;
    for (uint8_t p = 0; p < EDGE_MAX_PERSONS; p++) {
        if (persons) persons[p] = s_persons[p];
        if (s_persons[p].active) active++;
    }
    if (n_active) *n_active = active;
}

void edge_get_phase_history(const float **out_buf, uint16_t *out_len,
                            uint16_t *out_idx)
{
    if (out_buf) *out_buf = s_phase_history;
    if (out_len) *out_len = s_history_len;
    if (out_idx) *out_idx = s_history_idx;
}

void edge_get_variances(float *out_variances, uint16_t n_subcarriers)
{
    if (out_variances == NULL) return;
    uint16_t n = (n_subcarriers > EDGE_MAX_SUBCARRIERS) ? EDGE_MAX_SUBCARRIERS : n_subcarriers;
    for (uint16_t i = 0; i < n; i++) {
        out_variances[i] = (float)welford_variance(&s_subcarrier_var[i]);
    }
}

esp_err_t edge_processing_init(const edge_config_t *cfg)
{
    if (cfg == NULL) {
        ESP_LOGE(TAG, "edge_processing_init: cấu hình là NULL");
        return ESP_ERR_INVALID_ARG;
    }

    /* Lưu cấu hình. */
    s_cfg = *cfg;

    ESP_LOGI(TAG, "Khởi tạo xử lý biên (tầng=%u, top_k=%u, "
             "khoảng_sinh_hiệu=%ums, ngưỡng_hiện_diện=%.3f)",
             s_cfg.tier, s_cfg.top_k_count,
             s_cfg.vital_interval_ms, s_cfg.presence_thresh);

    /* Đặt lại tất cả trạng thái. */
    memset(&s_ring, 0, sizeof(s_ring));
    memset(s_subcarrier_var, 0, sizeof(s_subcarrier_var));
    memset(s_prev_phase, 0, sizeof(s_prev_phase));
    s_phase_initialized = false;
    s_top_k_count = 0;
    s_history_len = 0;
    s_history_idx = 0;
    s_breathing_bpm = 0.0f;
    s_heartrate_bpm = 0.0f;
    s_motion_energy = 0.0f;
    s_presence_score = 0.0f;
    s_presence_detected = false;
    s_fall_detected = false;
    s_latest_rssi = 0;
    s_frame_count = 0;
    s_prev_phase_velocity = 0.0f;
    s_last_vitals_send_us = 0;
    s_has_prev_iq = false;
    s_prev_iq_len = 0;
    s_pkt_valid = false;

    /* Đặt lại trạng thái hiệu chuẩn. */
    s_calibrated = false;
    s_calib_sum = 0.0f;
    s_calib_sum_sq = 0.0f;
    s_calib_count = 0;
    s_adaptive_threshold = 0.05f;

    /* Đặt lại trạng thái đa người. */
    memset(s_persons, 0, sizeof(s_persons));
    for (uint8_t p = 0; p < EDGE_MAX_PERSONS; p++) {
        s_persons[p].active = false;
    }

    /* Thiết kế bộ lọc thông dải biquad.
     * Tốc độ lấy mẫu ~20 Hz (tốc độ callback CSI ESP32 thông thường). */
    const float fs = 20.0f;
    biquad_bandpass_design(&s_bq_breathing, fs, 0.1f, 0.5f);
    biquad_bandpass_design(&s_bq_heartrate, fs, 0.8f, 2.0f);

    /* Thiết kế bộ lọc theo người. */
    for (uint8_t p = 0; p < EDGE_MAX_PERSONS; p++) {
        biquad_bandpass_design(&s_person_bq_br[p], fs, 0.1f, 0.5f);
        biquad_bandpass_design(&s_person_bq_hr[p], fs, 0.8f, 2.0f);
    }

    if (s_cfg.tier == 0) {
        ESP_LOGI(TAG, "Tầng biên 0: chuyển tiếp thô (không có tác vụ DSP)");
        return ESP_OK;
    }

    /* Khởi động tác vụ DSP trên Nhân 1. */
    BaseType_t ret = xTaskCreatePinnedToCore(
        edge_task,
        "edge_dsp",
        8192,       /* Stack 8 KB — đủ cho đường ống DSP. */
        NULL,
        5,          /* Ưu tiên 5 — trên idle, dưới WiFi. */
        NULL,
        1           /* Ghim vào Nhân 1. */
    );

    if (ret != pdPASS) {
        ESP_LOGE(TAG, "Không thể tạo tác vụ DSP biên");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Tác vụ DSP biên đã tạo trên Nhân 1 (stack=8192, ưu_tiên=5)");
    return ESP_OK;
}
