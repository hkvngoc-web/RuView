"""
Dịch vụ truyền phát thời gian thực cho WiFi-DensePose API
"""

import logging
import asyncio
import json
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from collections import deque

import numpy as np
from fastapi import WebSocket

from src.config.settings import Settings
from src.config.domains import DomainConfig

logger = logging.getLogger(__name__)


class StreamService:
    """Dịch vụ cho truyền phát dữ liệu thời gian thực."""

    def __init__(self, settings: Settings, domain_config: DomainConfig):
        """Khởi tạo dịch vụ truyền phát."""
        self.settings = settings
        self.domain_config = domain_config
        self.logger = logging.getLogger(__name__)

        # Kết nối WebSocket
        self.connections: Set[WebSocket] = set()
        self.connection_metadata: Dict[WebSocket, Dict[str, Any]] = {}

        # Bộ đệm luồng
        self.pose_buffer = deque(maxlen=self.settings.stream_buffer_size)
        self.csi_buffer = deque(maxlen=self.settings.stream_buffer_size)

        # Trạng thái dịch vụ
        self.is_running = False
        self.last_error = None

        # Thống kê truyền phát
        self.stats = {
            "active_connections": 0,
            "total_connections": 0,
            "messages_sent": 0,
            "messages_failed": 0,
            "data_points_streamed": 0,
            "average_latency_ms": 0.0
        }

        # Tác vụ nền
        self.streaming_task = None

    async def initialize(self):
        """Khởi tạo dịch vụ truyền phát."""
        self.logger.info("Dịch vụ truyền phát đã khởi tạo")

    async def start(self):
        """Khởi động dịch vụ truyền phát."""
        if self.is_running:
            return

        self.is_running = True
        self.logger.info("Dịch vụ truyền phát đã khởi động")

        # Khởi động tác vụ truyền phát nền
        if self.settings.enable_real_time_processing:
            self.streaming_task = asyncio.create_task(self._streaming_loop())

    async def stop(self):
        """Dừng dịch vụ truyền phát."""
        self.is_running = False

        # Hủy tác vụ nền
        if self.streaming_task:
            self.streaming_task.cancel()
            try:
                await self.streaming_task
            except asyncio.CancelledError:
                pass

        # Đóng tất cả kết nối
        await self._close_all_connections()

        self.logger.info("Dịch vụ truyền phát đã dừng")

    async def add_connection(self, websocket: WebSocket, metadata: Dict[str, Any] = None):
        """Thêm kết nối WebSocket mới."""
        try:
            await websocket.accept()
            self.connections.add(websocket)
            self.connection_metadata[websocket] = metadata or {}

            self.stats["active_connections"] = len(self.connections)
            self.stats["total_connections"] += 1

            self.logger.info(f"Đã thêm kết nối WebSocket mới. Tổng: {len(self.connections)}")

            # Gửi dữ liệu ban đầu nếu có
            await self._send_initial_data(websocket)

        except Exception as e:
            self.logger.error(f"Lỗi khi thêm kết nối WebSocket: {e}")
            raise

    async def remove_connection(self, websocket: WebSocket):
        """Xóa kết nối WebSocket."""
        try:
            if websocket in self.connections:
                self.connections.remove(websocket)
                self.connection_metadata.pop(websocket, None)

                self.stats["active_connections"] = len(self.connections)

                self.logger.info(f"Đã xóa kết nối WebSocket. Tổng: {len(self.connections)}")

        except Exception as e:
            self.logger.error(f"Lỗi khi xóa kết nối WebSocket: {e}")

    async def broadcast_pose_data(self, pose_data: Dict[str, Any]):
        """Phát sóng dữ liệu tư thế đến tất cả máy khách đã kết nối."""
        if not self.is_running:
            return

        # Thêm vào bộ đệm
        self.pose_buffer.append({
            "type": "pose_data",
            "timestamp": datetime.now().isoformat(),
            "data": pose_data
        })

        # Phát sóng đến tất cả kết nối
        await self._broadcast_message({
            "type": "pose_update",
            "timestamp": datetime.now().isoformat(),
            "data": pose_data
        })

    async def broadcast_csi_data(self, csi_data: np.ndarray, metadata: Dict[str, Any]):
        """Phát sóng dữ liệu CSI đến tất cả máy khách đã kết nối."""
        if not self.is_running:
            return

        # Chuyển đổi mảng numpy sang danh sách cho tuần tự hóa JSON
        csi_list = csi_data.tolist() if isinstance(csi_data, np.ndarray) else csi_data

        # Thêm vào bộ đệm
        self.csi_buffer.append({
            "type": "csi_data",
            "timestamp": datetime.now().isoformat(),
            "data": csi_list,
            "metadata": metadata
        })

        # Phát sóng đến tất cả kết nối
        await self._broadcast_message({
            "type": "csi_update",
            "timestamp": datetime.now().isoformat(),
            "data": csi_list,
            "metadata": metadata
        })

    async def broadcast_system_status(self, status_data: Dict[str, Any]):
        """Phát sóng trạng thái hệ thống đến tất cả máy khách đã kết nối."""
        if not self.is_running:
            return

        await self._broadcast_message({
            "type": "system_status",
            "timestamp": datetime.now().isoformat(),
            "data": status_data
        })

    async def send_to_connection(self, websocket: WebSocket, message: Dict[str, Any]):
        """Gửi tin nhắn đến kết nối cụ thể."""
        try:
            if websocket in self.connections:
                await websocket.send_text(json.dumps(message))
                self.stats["messages_sent"] += 1

        except Exception as e:
            self.logger.error(f"Lỗi khi gửi tin nhắn đến kết nối: {e}")
            self.stats["messages_failed"] += 1
            await self.remove_connection(websocket)

    async def _broadcast_message(self, message: Dict[str, Any]):
        """Phát sóng tin nhắn đến tất cả máy khách đã kết nối."""
        if not self.connections:
            return

        disconnected = set()

        for websocket in self.connections.copy():
            try:
                await websocket.send_text(json.dumps(message))
                self.stats["messages_sent"] += 1

            except Exception as e:
                self.logger.warning(f"Gửi tin nhắn đến kết nối thất bại: {e}")
                self.stats["messages_failed"] += 1
                disconnected.add(websocket)

        # Xóa máy khách đã ngắt kết nối
        for websocket in disconnected:
            await self.remove_connection(websocket)

        if message.get("type") in ["pose_update", "csi_update"]:
            self.stats["data_points_streamed"] += 1

    async def _send_initial_data(self, websocket: WebSocket):
        """Gửi dữ liệu ban đầu đến kết nối mới."""
        try:
            # Gửi dữ liệu tư thế gần đây
            if self.pose_buffer:
                recent_poses = list(self.pose_buffer)[-10:]  # 10 tư thế gần nhất
                await self.send_to_connection(websocket, {
                    "type": "initial_poses",
                    "timestamp": datetime.now().isoformat(),
                    "data": recent_poses
                })

            # Gửi dữ liệu CSI gần đây
            if self.csi_buffer:
                recent_csi = list(self.csi_buffer)[-5:]  # 5 lần đọc CSI gần nhất
                await self.send_to_connection(websocket, {
                    "type": "initial_csi",
                    "timestamp": datetime.now().isoformat(),
                    "data": recent_csi
                })

            # Gửi trạng thái dịch vụ
            status = await self.get_status()
            await self.send_to_connection(websocket, {
                "type": "service_status",
                "timestamp": datetime.now().isoformat(),
                "data": status
            })

        except Exception as e:
            self.logger.error(f"Lỗi khi gửi dữ liệu ban đầu: {e}")

    async def _streaming_loop(self):
        """Vòng lặp truyền phát nền cho cập nhật định kỳ."""
        try:
            while self.is_running:
                # Gửi heartbeat định kỳ
                if self.connections:
                    await self._broadcast_message({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat(),
                        "active_connections": len(self.connections)
                    })

                # Chờ lần lặp tiếp theo
                await asyncio.sleep(self.settings.websocket_ping_interval)

        except asyncio.CancelledError:
            self.logger.info("Vòng lặp truyền phát đã bị hủy")
        except Exception as e:
            self.logger.error(f"Lỗi trong vòng lặp truyền phát: {e}")
            self.last_error = str(e)

    async def _close_all_connections(self):
        """Đóng tất cả kết nối WebSocket."""
        disconnected = []

        for websocket in self.connections.copy():
            try:
                await websocket.close()
                disconnected.append(websocket)
            except Exception as e:
                self.logger.warning(f"Lỗi khi đóng kết nối: {e}")
                disconnected.append(websocket)

        # Xóa tất cả kết nối
        for websocket in disconnected:
            await self.remove_connection(websocket)

    async def get_status(self) -> Dict[str, Any]:
        """Lấy trạng thái dịch vụ."""
        return {
            "status": "healthy" if self.is_running and not self.last_error else "unhealthy",
            "running": self.is_running,
            "last_error": self.last_error,
            "connections": {
                "active": len(self.connections),
                "total": self.stats["total_connections"]
            },
            "buffers": {
                "pose_buffer_size": len(self.pose_buffer),
                "csi_buffer_size": len(self.csi_buffer),
                "max_buffer_size": self.settings.stream_buffer_size
            },
            "statistics": self.stats.copy(),
            "configuration": {
                "stream_fps": self.settings.stream_fps,
                "buffer_size": self.settings.stream_buffer_size,
                "ping_interval": self.settings.websocket_ping_interval,
                "timeout": self.settings.websocket_timeout
            }
        }

    async def get_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu dịch vụ."""
        total_messages = self.stats["messages_sent"] + self.stats["messages_failed"]
        success_rate = self.stats["messages_sent"] / max(1, total_messages)

        return {
            "stream_service": {
                "active_connections": self.stats["active_connections"],
                "total_connections": self.stats["total_connections"],
                "messages_sent": self.stats["messages_sent"],
                "messages_failed": self.stats["messages_failed"],
                "message_success_rate": success_rate,
                "data_points_streamed": self.stats["data_points_streamed"],
                "average_latency_ms": self.stats["average_latency_ms"]
            }
        }

    async def get_connection_info(self) -> List[Dict[str, Any]]:
        """Lấy thông tin về các kết nối đang hoạt động."""
        connections_info = []

        for websocket in self.connections:
            metadata = self.connection_metadata.get(websocket, {})

            connection_info = {
                "id": id(websocket),
                "connected_at": metadata.get("connected_at", "không xác định"),
                "user_agent": metadata.get("user_agent", "không xác định"),
                "ip_address": metadata.get("ip_address", "không xác định"),
                "subscription_types": metadata.get("subscription_types", [])
            }

            connections_info.append(connection_info)

        return connections_info

    async def reset(self):
        """Đặt lại trạng thái dịch vụ."""
        # Xóa bộ đệm
        self.pose_buffer.clear()
        self.csi_buffer.clear()

        # Đặt lại thống kê
        self.stats = {
            "active_connections": len(self.connections),
            "total_connections": 0,
            "messages_sent": 0,
            "messages_failed": 0,
            "data_points_streamed": 0,
            "average_latency_ms": 0.0
        }

        self.last_error = None
        self.logger.info("Dịch vụ truyền phát đã đặt lại")

    def get_buffer_data(self, buffer_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Lấy dữ liệu từ bộ đệm."""
        if buffer_type == "pose":
            return list(self.pose_buffer)[-limit:]
        elif buffer_type == "csi":
            return list(self.csi_buffer)[-limit:]
        else:
            return []

    @property
    def is_active(self) -> bool:
        """Kiểm tra xem dịch vụ truyền phát có đang hoạt động không."""
        return self.is_running

    async def health_check(self) -> Dict[str, Any]:
        """Thực hiện kiểm tra sức khỏe."""
        try:
            status = "healthy" if self.is_running and not self.last_error else "unhealthy"

            return {
                "status": status,
                "message": self.last_error if self.last_error else "Dịch vụ truyền phát đang chạy bình thường",
                "active_connections": len(self.connections),
                "metrics": {
                    "messages_sent": self.stats["messages_sent"],
                    "messages_failed": self.stats["messages_failed"],
                    "data_points_streamed": self.stats["data_points_streamed"]
                }
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"Kiểm tra sức khỏe thất bại: {str(e)}"
            }

    async def is_ready(self) -> bool:
        """Kiểm tra xem dịch vụ có sẵn sàng không."""
        return self.is_running
