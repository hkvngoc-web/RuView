/**
 * @file stream_sender.h
 * @brief Bộ gửi luồng UDP cho các khung CSI.
 */

#ifndef STREAM_SENDER_H
#define STREAM_SENDER_H

#include <stdint.h>
#include <stddef.h>

/**
 * Khởi tạo bộ gửi UDP.
 * Tạo socket UDP hướng tới bộ tổng hợp đã cấu hình.
 *
 * @return 0 on success, -1 on error.
 */
int stream_sender_init(void);

/**
 * Khởi tạo bộ gửi UDP với IP và cổng chỉ định.
 * Dùng khi cấu hình được tải từ NVS lúc chạy.
 *
 * @param ip   Aggregator IP address string (e.g. "192.168.1.20").
 * @param port Aggregator UDP port.
 * @return 0 on success, -1 on error.
 */
int stream_sender_init_with(const char *ip, uint16_t port);

/**
 * Gửi khung CSI đã tuần tự hóa qua UDP.
 *
 * @param data Frame data buffer.
 * @param len  Length of data to send.
 * @return Number of bytes sent, or -1 on error.
 */
int stream_sender_send(const uint8_t *data, size_t len);

/**
 * Đóng socket bộ gửi UDP.
 */
void stream_sender_deinit(void);

#endif /* STREAM_SENDER_H */
