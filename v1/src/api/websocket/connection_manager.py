"""
Trình quản lý kết nối WebSocket cho WiFi-DensePose API
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """Đại diện một kết nối WebSocket với siêu dữ liệu."""

    def __init__(
        self,
        websocket: WebSocket,
        client_id: str,
        stream_type: str,
        zone_ids: Optional[List[str]] = None,
        **config
    ):
        self.websocket = websocket
        self.client_id = client_id
        self.stream_type = stream_type
        self.zone_ids = zone_ids or []
        self.config = config
        self.connected_at = datetime.utcnow()
        self.last_ping = datetime.utcnow()
        self.message_count = 0
        self.is_active = True

    async def send_json(self, data: Dict[str, Any]):
        """Gửi dữ liệu JSON đến máy khách."""
        try:
            await self.websocket.send_json(data)
            self.message_count += 1
        except Exception as e:
            logger.error(f"Lỗi khi gửi đến máy khách {self.client_id}: {e}")
            self.is_active = False
            raise

    async def send_text(self, message: str):
        """Gửi tin nhắn văn bản đến máy khách."""
        try:
            await self.websocket.send_text(message)
            self.message_count += 1
        except Exception as e:
            logger.error(f"Lỗi khi gửi văn bản đến máy khách {self.client_id}: {e}")
            self.is_active = False
            raise

    def update_config(self, config: Dict[str, Any]):
        """Cập nhật cấu hình kết nối."""
        self.config.update(config)

        # Cập nhật ID khu vực nếu được cung cấp
        if "zone_ids" in config:
            self.zone_ids = config["zone_ids"] or []

    def matches_filter(
        self,
        stream_type: Optional[str] = None,
        zone_ids: Optional[List[str]] = None,
        **filters
    ) -> bool:
        """Kiểm tra xem kết nối có khớp với bộ lọc đã cho không."""
        # Kiểm tra loại luồng
        if stream_type and self.stream_type != stream_type:
            return False

        # Kiểm tra ID khu vực
        if zone_ids:
            if not self.zone_ids:  # Kết nối lắng nghe tất cả khu vực
                return True
            # Kiểm tra xem có khu vực nào được yêu cầu nằm trong khu vực của kết nối không
            if not any(zone in self.zone_ids for zone in zone_ids):
                return False

        # Kiểm tra bộ lọc bổ sung
        for key, value in filters.items():
            if key in self.config and self.config[key] != value:
                return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """Lấy thông tin kết nối."""
        return {
            "client_id": self.client_id,
            "stream_type": self.stream_type,
            "zone_ids": self.zone_ids,
            "config": self.config,
            "connected_at": self.connected_at.isoformat(),
            "last_ping": self.last_ping.isoformat(),
            "message_count": self.message_count,
            "is_active": self.is_active,
            "uptime_seconds": (datetime.utcnow() - self.connected_at).total_seconds()
        }


class ConnectionManager:
    """Quản lý kết nối WebSocket cho truyền phát thời gian thực."""

    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.connections_by_type: Dict[str, Set[str]] = defaultdict(set)
        self.connections_by_zone: Dict[str, Set[str]] = defaultdict(set)
        self.metrics = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_sent": 0,
            "errors": 0,
            "start_time": datetime.utcnow()
        }
        self._cleanup_task = None
        self._started = False

    async def connect(
        self,
        websocket: WebSocket,
        stream_type: str,
        zone_ids: Optional[List[str]] = None,
        **config
    ) -> str:
        """Đăng ký kết nối WebSocket mới."""
        client_id = str(uuid.uuid4())

        try:
            # Tạo đối tượng kết nối
            connection = WebSocketConnection(
                websocket=websocket,
                client_id=client_id,
                stream_type=stream_type,
                zone_ids=zone_ids,
                **config
            )

            # Lưu trữ kết nối
            self.connections[client_id] = connection
            self.connections_by_type[stream_type].add(client_id)

            # Lập chỉ mục theo khu vực
            if zone_ids:
                for zone_id in zone_ids:
                    self.connections_by_zone[zone_id].add(client_id)

            # Cập nhật số liệu
            self.metrics["total_connections"] += 1
            self.metrics["active_connections"] = len(self.connections)

            logger.info(f"Máy khách WebSocket {client_id} đã kết nối cho {stream_type}")

            return client_id

        except Exception as e:
            logger.error(f"Lỗi khi kết nối máy khách WebSocket: {e}")
            raise

    async def disconnect(self, client_id: str) -> bool:
        """Ngắt kết nối máy khách WebSocket."""
        if client_id not in self.connections:
            return False

        try:
            connection = self.connections[client_id]

            # Xóa khỏi chỉ mục
            self.connections_by_type[connection.stream_type].discard(client_id)

            for zone_id in connection.zone_ids:
                self.connections_by_zone[zone_id].discard(client_id)

            # Đóng WebSocket nếu vẫn đang hoạt động
            if connection.is_active:
                try:
                    await connection.websocket.close()
                except Exception:
                    pass  # Kết nối có thể đã đóng

            # Xóa kết nối
            del self.connections[client_id]

            # Cập nhật số liệu
            self.metrics["active_connections"] = len(self.connections)

            logger.info(f"Máy khách WebSocket {client_id} đã ngắt kết nối")

            return True

        except Exception as e:
            logger.error(f"Lỗi khi ngắt kết nối máy khách {client_id}: {e}")
            return False

    async def disconnect_all(self):
        """Ngắt kết nối tất cả máy khách WebSocket."""
        client_ids = list(self.connections.keys())

        for client_id in client_ids:
            await self.disconnect(client_id)

        logger.info("Tất cả máy khách WebSocket đã ngắt kết nối")

    async def send_to_client(self, client_id: str, data: Dict[str, Any]) -> bool:
        """Gửi dữ liệu đến máy khách cụ thể."""
        if client_id not in self.connections:
            return False

        connection = self.connections[client_id]

        try:
            await connection.send_json(data)
            self.metrics["messages_sent"] += 1
            return True

        except Exception as e:
            logger.error(f"Lỗi khi gửi đến máy khách {client_id}: {e}")
            self.metrics["errors"] += 1

            # Đánh dấu kết nối không hoạt động và lên lịch dọn dẹp
            connection.is_active = False
            return False

    async def broadcast(
        self,
        data: Dict[str, Any],
        stream_type: Optional[str] = None,
        zone_ids: Optional[List[str]] = None,
        **filters
    ) -> int:
        """Phát sóng dữ liệu đến các máy khách khớp."""
        sent_count = 0
        failed_clients = []

        # Lấy các kết nối khớp
        matching_clients = self._get_matching_clients(
            stream_type=stream_type,
            zone_ids=zone_ids,
            **filters
        )

        # Gửi đến tất cả máy khách khớp
        for client_id in matching_clients:
            try:
                success = await self.send_to_client(client_id, data)
                if success:
                    sent_count += 1
                else:
                    failed_clients.append(client_id)
            except Exception as e:
                logger.error(f"Lỗi khi phát sóng đến máy khách {client_id}: {e}")
                failed_clients.append(client_id)

        # Dọn dẹp kết nối thất bại
        for client_id in failed_clients:
            await self.disconnect(client_id)

        return sent_count

    async def update_client_config(self, client_id: str, config: Dict[str, Any]) -> bool:
        """Cập nhật cấu hình máy khách."""
        if client_id not in self.connections:
            return False

        connection = self.connections[client_id]
        old_zones = set(connection.zone_ids)

        # Cập nhật cấu hình
        connection.update_config(config)

        # Cập nhật chỉ mục khu vực nếu khu vực thay đổi
        new_zones = set(connection.zone_ids)

        # Xóa khỏi khu vực cũ
        for zone_id in old_zones - new_zones:
            self.connections_by_zone[zone_id].discard(client_id)

        # Thêm vào khu vực mới
        for zone_id in new_zones - old_zones:
            self.connections_by_zone[zone_id].add(client_id)

        return True

    async def get_client_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Lấy trạng thái của máy khách cụ thể."""
        if client_id not in self.connections:
            return None

        return self.connections[client_id].get_info()

    async def get_connected_clients(self) -> List[Dict[str, Any]]:
        """Lấy danh sách tất cả máy khách đã kết nối."""
        return [conn.get_info() for conn in self.connections.values()]

    async def get_connection_stats(self) -> Dict[str, Any]:
        """Lấy thống kê kết nối."""
        stats = {
            "total_clients": len(self.connections),
            "clients_by_type": {
                stream_type: len(clients)
                for stream_type, clients in self.connections_by_type.items()
            },
            "clients_by_zone": {
                zone_id: len(clients)
                for zone_id, clients in self.connections_by_zone.items()
                if clients  # Chỉ bao gồm khu vực có máy khách đang hoạt động
            },
            "active_clients": sum(1 for conn in self.connections.values() if conn.is_active),
            "inactive_clients": sum(1 for conn in self.connections.values() if not conn.is_active)
        }

        return stats

    async def get_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu chi tiết."""
        uptime = (datetime.utcnow() - self.metrics["start_time"]).total_seconds()

        return {
            **self.metrics,
            "active_connections": len(self.connections),
            "uptime_seconds": uptime,
            "messages_per_second": self.metrics["messages_sent"] / max(uptime, 1),
            "error_rate": self.metrics["errors"] / max(self.metrics["messages_sent"], 1)
        }

    def _get_matching_clients(
        self,
        stream_type: Optional[str] = None,
        zone_ids: Optional[List[str]] = None,
        **filters
    ) -> List[str]:
        """Lấy ID máy khách khớp với bộ lọc đã cho."""
        candidates = set(self.connections.keys())

        # Lọc theo loại luồng
        if stream_type:
            type_clients = self.connections_by_type.get(stream_type, set())
            candidates &= type_clients

        # Lọc theo khu vực
        if zone_ids:
            zone_clients = set()
            for zone_id in zone_ids:
                zone_clients.update(self.connections_by_zone.get(zone_id, set()))

            # Cũng bao gồm máy khách lắng nghe tất cả khu vực (danh sách khu vực rỗng)
            all_zone_clients = {
                client_id for client_id, conn in self.connections.items()
                if not conn.zone_ids
            }
            zone_clients.update(all_zone_clients)

            candidates &= zone_clients

        # Áp dụng bộ lọc bổ sung
        matching_clients = []
        for client_id in candidates:
            connection = self.connections[client_id]
            if connection.is_active and connection.matches_filter(**filters):
                matching_clients.append(client_id)

        return matching_clients

    async def ping_clients(self):
        """Gửi ping đến tất cả máy khách đã kết nối."""
        ping_data = {
            "type": "ping",
            "timestamp": datetime.utcnow().isoformat()
        }

        failed_clients = []

        for client_id, connection in self.connections.items():
            try:
                await connection.send_json(ping_data)
                connection.last_ping = datetime.utcnow()
            except Exception as e:
                logger.warning(f"Ping thất bại cho máy khách {client_id}: {e}")
                failed_clients.append(client_id)

        # Dọn dẹp kết nối thất bại
        for client_id in failed_clients:
            await self.disconnect(client_id)

    async def cleanup_inactive_connections(self):
        """Dọn dẹp kết nối không hoạt động hoặc cũ."""
        now = datetime.utcnow()
        stale_threshold = timedelta(minutes=5)  # 5 phút không có ping

        stale_clients = []

        for client_id, connection in self.connections.items():
            # Kiểm tra xem kết nối có không hoạt động không
            if not connection.is_active:
                stale_clients.append(client_id)
                continue

            # Kiểm tra xem kết nối có cũ không (không có phản hồi ping)
            if now - connection.last_ping > stale_threshold:
                logger.warning(f"Máy khách {client_id} có vẻ đã cũ, đang ngắt kết nối")
                stale_clients.append(client_id)

        # Dọn dẹp kết nối cũ
        for client_id in stale_clients:
            await self.disconnect(client_id)

        if stale_clients:
            logger.info(f"Đã dọn dẹp {len(stale_clients)} kết nối cũ")

    async def start(self):
        """Khởi động trình quản lý kết nối."""
        if not self._started:
            self._start_cleanup_task()
            self._started = True
            logger.info("Trình quản lý kết nối đã khởi động")

    def _start_cleanup_task(self):
        """Khởi động tác vụ dọn dẹp nền."""
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(60)  # Chạy mỗi phút
                    await self.cleanup_inactive_connections()

                    # Gửi ping định kỳ mỗi 2 phút
                    if datetime.utcnow().minute % 2 == 0:
                        await self.ping_clients()

                except Exception as e:
                    logger.error(f"Lỗi trong tác vụ dọn dẹp: {e}")

        try:
            self._cleanup_task = asyncio.create_task(cleanup_loop())
        except RuntimeError:
            # Không có vòng lặp sự kiện đang chạy, sẽ khởi động sau
            logger.debug("Không có vòng lặp sự kiện đang chạy, tác vụ dọn dẹp sẽ khởi động sau")

    async def shutdown(self):
        """Tắt trình quản lý kết nối."""
        # Hủy tác vụ dọn dẹp
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Ngắt kết nối tất cả máy khách
        await self.disconnect_all()

        logger.info("Tắt trình quản lý kết nối hoàn tất")


# Thể hiện trình quản lý kết nối toàn cục
connection_manager = ConnectionManager()
