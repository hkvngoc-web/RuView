"""
Trình xử lý WebSocket truyền phát tư thế
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import WebSocket
from pydantic import BaseModel, Field

from src.api.websocket.connection_manager import ConnectionManager
from src.services.pose_service import PoseService
from src.services.stream_service import StreamService

logger = logging.getLogger(__name__)


class PoseStreamData(BaseModel):
    """Mô hình dữ liệu luồng tư thế."""

    timestamp: datetime = Field(..., description="Dấu thời gian dữ liệu")
    zone_id: str = Field(..., description="Định danh khu vực")
    pose_data: Dict[str, Any] = Field(..., description="Dữ liệu ước lượng tư thế")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Điểm tin cậy")
    activity: Optional[str] = Field(default=None, description="Hoạt động đã phát hiện")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Siêu dữ liệu bổ sung")


class PoseStreamHandler:
    """Xử lý truyền phát dữ liệu tư thế đến máy khách WebSocket."""

    def __init__(
        self,
        connection_manager: ConnectionManager,
        pose_service: PoseService,
        stream_service: StreamService
    ):
        self.connection_manager = connection_manager
        self.pose_service = pose_service
        self.stream_service = stream_service
        self.is_streaming = False
        self.stream_task = None
        self.subscribers = {}
        self.stream_config = {
            "fps": 30,
            "min_confidence": 0.5,
            "include_metadata": True,
            "buffer_size": 100
        }

    async def start_streaming(self):
        """Bắt đầu truyền phát dữ liệu tư thế."""
        if self.is_streaming:
            logger.warning("Truyền phát tư thế đã đang hoạt động")
            return

        self.is_streaming = True
        self.stream_task = asyncio.create_task(self._stream_loop())
        logger.info("Truyền phát tư thế đã bắt đầu")

    async def stop_streaming(self):
        """Dừng truyền phát dữ liệu tư thế."""
        if not self.is_streaming:
            return

        self.is_streaming = False

        if self.stream_task:
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass

        logger.info("Truyền phát tư thế đã dừng")

    async def _stream_loop(self):
        """Vòng lặp truyền phát chính."""
        try:
            logger.info("Đang bắt đầu vòng lặp truyền phát tư thế")
            while self.is_streaming:
                try:
                    # Lấy dữ liệu tư thế hiện tại từ tất cả khu vực
                    logger.debug("Đang lấy dữ liệu tư thế hiện tại...")
                    pose_data = await self.pose_service.get_current_pose_data()
                    logger.debug(f"Đã nhận dữ liệu tư thế: {pose_data}")

                    if pose_data:
                        logger.debug("Đang phát sóng dữ liệu tư thế...")
                        await self._process_and_broadcast_pose_data(pose_data)
                    else:
                        logger.debug("Không nhận được dữ liệu tư thế")

                    # Kiểm soát tốc độ truyền phát
                    await asyncio.sleep(1.0 / self.stream_config["fps"])

                except Exception as e:
                    logger.error(f"Lỗi trong vòng lặp truyền phát tư thế: {e}")
                    await asyncio.sleep(1.0)  # Tạm dừng ngắn khi có lỗi

        except asyncio.CancelledError:
            logger.info("Vòng lặp truyền phát tư thế đã bị hủy")
        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng trong vòng lặp truyền phát tư thế: {e}")
        finally:
            logger.info("Vòng lặp truyền phát tư thế đã dừng")
            self.is_streaming = False

    async def _process_and_broadcast_pose_data(self, raw_pose_data: Dict[str, Any]):
        """Xử lý và phát sóng dữ liệu tư thế đến người đăng ký."""
        try:
            # Xử lý dữ liệu cho mỗi khu vực
            for zone_id, zone_data in raw_pose_data.items():
                if not zone_data:
                    continue

                # Tạo dữ liệu tư thế có cấu trúc
                pose_stream_data = PoseStreamData(
                    timestamp=datetime.utcnow(),
                    zone_id=zone_id,
                    pose_data=zone_data.get("pose", {}),
                    confidence=zone_data.get("confidence", 0.0),
                    activity=zone_data.get("activity"),
                    metadata=zone_data.get("metadata") if self.stream_config["include_metadata"] else None
                )

                # Lọc theo độ tin cậy tối thiểu
                if pose_stream_data.confidence < self.stream_config["min_confidence"]:
                    continue

                # Phát sóng đến người đăng ký
                await self._broadcast_pose_data(pose_stream_data)

        except Exception as e:
            logger.error(f"Lỗi khi xử lý dữ liệu tư thế: {e}")

    async def _broadcast_pose_data(self, pose_data: PoseStreamData):
        """Phát sóng dữ liệu tư thế đến máy khách WebSocket khớp."""
        try:
            logger.debug(f"Đang chuẩn bị phát sóng dữ liệu tư thế cho khu vực {pose_data.zone_id}")

            # Chuẩn bị dữ liệu phát sóng
            broadcast_data = {
                "type": "pose_data",
                "timestamp": pose_data.timestamp.isoformat(),
                "zone_id": pose_data.zone_id,
                "data": {
                    "pose": pose_data.pose_data,
                    "confidence": pose_data.confidence,
                    "activity": pose_data.activity
                }
            }

            # Thêm siêu dữ liệu nếu được bật
            if pose_data.metadata and self.stream_config["include_metadata"]:
                broadcast_data["metadata"] = pose_data.metadata

            logger.debug(f"Đang phát sóng dữ liệu: {broadcast_data}")

            # Phát sóng đến người đăng ký luồng tư thế
            sent_count = await self.connection_manager.broadcast(
                data=broadcast_data,
                stream_type="pose",
                zone_ids=[pose_data.zone_id]
            )

            logger.info(f"Đã phát sóng dữ liệu tư thế cho khu vực {pose_data.zone_id} đến {sent_count} máy khách")

        except Exception as e:
            logger.error(f"Lỗi khi phát sóng dữ liệu tư thế: {e}")

    async def handle_client_subscription(
        self,
        client_id: str,
        subscription_config: Dict[str, Any]
    ):
        """Xử lý cấu hình đăng ký máy khách."""
        try:
            # Lưu cấu hình đăng ký máy khách
            self.subscribers[client_id] = {
                "zone_ids": subscription_config.get("zone_ids", []),
                "min_confidence": subscription_config.get("min_confidence", 0.5),
                "max_fps": subscription_config.get("max_fps", 30),
                "include_metadata": subscription_config.get("include_metadata", True),
                "stream_types": subscription_config.get("stream_types", ["pose_data"]),
                "subscribed_at": datetime.utcnow()
            }

            logger.info(f"Đã cập nhật đăng ký cho máy khách {client_id}")

            # Gửi xác nhận
            confirmation = {
                "type": "subscription_updated",
                "client_id": client_id,
                "config": self.subscribers[client_id],
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.connection_manager.send_to_client(client_id, confirmation)

        except Exception as e:
            logger.error(f"Lỗi khi xử lý đăng ký máy khách: {e}")

    async def handle_client_disconnect(self, client_id: str):
        """Xử lý ngắt kết nối máy khách."""
        if client_id in self.subscribers:
            del self.subscribers[client_id]
            logger.info(f"Đã xóa đăng ký cho máy khách đã ngắt kết nối {client_id}")

    async def send_historical_data(
        self,
        client_id: str,
        zone_id: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 100
    ):
        """Gửi dữ liệu tư thế lịch sử đến máy khách."""
        try:
            # Lấy dữ liệu lịch sử từ dịch vụ tư thế
            historical_data = await self.pose_service.get_historical_data(
                zone_id=zone_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit
            )

            # Gửi dữ liệu theo từng phần để tránh làm quá tải máy khách
            chunk_size = 10
            for i in range(0, len(historical_data), chunk_size):
                chunk = historical_data[i:i + chunk_size]

                message = {
                    "type": "historical_data",
                    "zone_id": zone_id,
                    "chunk_index": i // chunk_size,
                    "total_chunks": (len(historical_data) + chunk_size - 1) // chunk_size,
                    "data": chunk,
                    "timestamp": datetime.utcnow().isoformat()
                }

                await self.connection_manager.send_to_client(client_id, message)

                # Tạm dừng nhỏ giữa các phần
                await asyncio.sleep(0.1)

            # Gửi thông báo hoàn tất
            completion_message = {
                "type": "historical_data_complete",
                "zone_id": zone_id,
                "total_records": len(historical_data),
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.connection_manager.send_to_client(client_id, completion_message)

        except Exception as e:
            logger.error(f"Lỗi khi gửi dữ liệu lịch sử: {e}")

            # Gửi thông báo lỗi đến máy khách
            error_message = {
                "type": "error",
                "message": f"Lấy dữ liệu lịch sử thất bại: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.connection_manager.send_to_client(client_id, error_message)

    async def send_zone_statistics(self, client_id: str, zone_id: str):
        """Gửi thống kê khu vực đến máy khách."""
        try:
            # Lấy thống kê khu vực
            stats = await self.pose_service.get_zone_statistics(zone_id)

            message = {
                "type": "zone_statistics",
                "zone_id": zone_id,
                "statistics": stats,
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.connection_manager.send_to_client(client_id, message)

        except Exception as e:
            logger.error(f"Lỗi khi gửi thống kê khu vực: {e}")

    async def broadcast_system_event(self, event_type: str, event_data: Dict[str, Any]):
        """Phát sóng sự kiện hệ thống đến tất cả máy khách đã kết nối."""
        try:
            message = {
                "type": "system_event",
                "event_type": event_type,
                "data": event_data,
                "timestamp": datetime.utcnow().isoformat()
            }

            # Phát sóng đến tất cả máy khách luồng tư thế
            sent_count = await self.connection_manager.broadcast(
                data=message,
                stream_type="pose"
            )

            logger.info(f"Đã phát sóng sự kiện hệ thống '{event_type}' đến {sent_count} máy khách")

        except Exception as e:
            logger.error(f"Lỗi khi phát sóng sự kiện hệ thống: {e}")

    async def update_stream_config(self, config: Dict[str, Any]):
        """Cập nhật cấu hình truyền phát."""
        try:
            # Xác thực và cập nhật cấu hình
            if "fps" in config:
                fps = max(1, min(60, config["fps"]))
                self.stream_config["fps"] = fps

            if "min_confidence" in config:
                confidence = max(0.0, min(1.0, config["min_confidence"]))
                self.stream_config["min_confidence"] = confidence

            if "include_metadata" in config:
                self.stream_config["include_metadata"] = bool(config["include_metadata"])

            if "buffer_size" in config:
                buffer_size = max(10, min(1000, config["buffer_size"]))
                self.stream_config["buffer_size"] = buffer_size

            logger.info(f"Đã cập nhật cấu hình truyền phát: {self.stream_config}")

            # Phát sóng cập nhật cấu hình đến máy khách
            await self.broadcast_system_event("stream_config_updated", {
                "new_config": self.stream_config
            })

        except Exception as e:
            logger.error(f"Lỗi khi cập nhật cấu hình truyền phát: {e}")

    def get_stream_status(self) -> Dict[str, Any]:
        """Lấy trạng thái truyền phát hiện tại."""
        return {
            "is_streaming": self.is_streaming,
            "config": self.stream_config,
            "subscriber_count": len(self.subscribers),
            "subscribers": {
                client_id: {
                    "zone_ids": sub["zone_ids"],
                    "min_confidence": sub["min_confidence"],
                    "subscribed_at": sub["subscribed_at"].isoformat()
                }
                for client_id, sub in self.subscribers.items()
            }
        }

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Lấy số liệu hiệu suất truyền phát."""
        try:
            # Lấy số liệu trình quản lý kết nối
            conn_metrics = await self.connection_manager.get_metrics()

            # Lấy số liệu dịch vụ tư thế
            pose_metrics = await self.pose_service.get_performance_metrics()

            return {
                "streaming": {
                    "is_active": self.is_streaming,
                    "fps": self.stream_config["fps"],
                    "subscriber_count": len(self.subscribers)
                },
                "connections": conn_metrics,
                "pose_service": pose_metrics,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Lỗi khi lấy số liệu hiệu suất: {e}")
            return {}

    async def shutdown(self):
        """Tắt trình xử lý luồng tư thế."""
        await self.stop_streaming()
        self.subscribers.clear()
        logger.info("Tắt trình xử lý luồng tư thế hoàn tất")
