"""
Các endpoint API truyền phát WebSocket
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.dependencies import (
    get_stream_service,
    get_pose_service,
    get_current_user_ws,
    require_auth
)
from src.api.websocket.connection_manager import connection_manager
from src.services.stream_service import StreamService
from src.services.pose_service import PoseService

logger = logging.getLogger(__name__)
router = APIRouter()


# Mô hình yêu cầu/phản hồi
class StreamSubscriptionRequest(BaseModel):
    """Mô hình yêu cầu cho đăng ký luồng."""

    zone_ids: Optional[List[str]] = Field(
        default=None,
        description="Các khu vực đăng ký (tất cả khu vực nếu không chỉ định)"
    )
    stream_types: List[str] = Field(
        default=["pose_data"],
        description="Các loại dữ liệu để truyền phát"
    )
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Ngưỡng độ tin cậy tối thiểu cho truyền phát"
    )
    max_fps: int = Field(
        default=30,
        ge=1,
        le=60,
        description="Số khung hình tối đa mỗi giây"
    )
    include_metadata: bool = Field(
        default=True,
        description="Bao gồm siêu dữ liệu trong luồng"
    )


class StreamStatus(BaseModel):
    """Mô hình trạng thái luồng."""

    is_active: bool = Field(..., description="Truyền phát có đang hoạt động không")
    connected_clients: int = Field(..., description="Số máy khách đã kết nối")
    streams: List[Dict[str, Any]] = Field(..., description="Các luồng đang hoạt động")
    uptime_seconds: float = Field(..., description="Thời gian hoạt động luồng tính bằng giây")


# Các endpoint WebSocket
@router.websocket("/pose")
async def websocket_pose_stream(
    websocket: WebSocket,
    zone_ids: Optional[str] = Query(None, description="ID khu vực phân cách bằng dấu phẩy"),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    max_fps: int = Query(30, ge=1, le=60),
    token: Optional[str] = Query(None, description="Token xác thực")
):
    """Endpoint WebSocket cho truyền phát dữ liệu tư thế thời gian thực."""
    client_id = None

    try:
        # Chấp nhận kết nối WebSocket
        await websocket.accept()

        # Kiểm tra xác thực nếu được bật
        from src.config.settings import get_settings
        settings = get_settings()

        if settings.enable_authentication and not token:
            await websocket.send_json({
                "type": "error",
                "message": "Yêu cầu token xác thực"
            })
            await websocket.close(code=1008)
            return

        # Phân tích ID khu vực
        zone_list = None
        if zone_ids:
            zone_list = [zone.strip() for zone in zone_ids.split(",") if zone.strip()]

        # Đăng ký máy khách với trình quản lý kết nối
        client_id = await connection_manager.connect(
            websocket=websocket,
            stream_type="pose",
            zone_ids=zone_list,
            min_confidence=min_confidence,
            max_fps=max_fps
        )

        logger.info(f"Máy khách WebSocket {client_id} đã kết nối để truyền phát tư thế")

        # Gửi xác nhận kết nối ban đầu
        await websocket.send_json({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "config": {
                "zone_ids": zone_list,
                "min_confidence": min_confidence,
                "max_fps": max_fps
            }
        })

        # Giữ kết nối và xử lý tin nhắn đến
        while True:
            try:
                # Chờ tin nhắn từ máy khách (ping, cập nhật cấu hình, v.v.)
                message = await websocket.receive_text()
                data = json.loads(message)

                await handle_websocket_message(client_id, data, websocket)

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Định dạng JSON không hợp lệ"
                })
            except Exception as e:
                logger.error(f"Lỗi khi xử lý tin nhắn WebSocket: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Lỗi máy chủ nội bộ"
                })

    except WebSocketDisconnect:
        logger.info(f"Máy khách WebSocket {client_id} đã ngắt kết nối")
    except Exception as e:
        logger.error(f"Lỗi WebSocket: {e}")
    finally:
        if client_id:
            await connection_manager.disconnect(client_id)


@router.websocket("/events")
async def websocket_events_stream(
    websocket: WebSocket,
    event_types: Optional[str] = Query(None, description="Các loại sự kiện phân cách bằng dấu phẩy"),
    zone_ids: Optional[str] = Query(None, description="ID khu vực phân cách bằng dấu phẩy"),
    token: Optional[str] = Query(None, description="Token xác thực")
):
    """Endpoint WebSocket cho truyền phát sự kiện thời gian thực."""
    client_id = None

    try:
        await websocket.accept()

        # Kiểm tra xác thực nếu được bật
        from src.config.settings import get_settings
        settings = get_settings()

        if settings.enable_authentication and not token:
            await websocket.send_json({
                "type": "error",
                "message": "Yêu cầu token xác thực"
            })
            await websocket.close(code=1008)
            return

        # Phân tích tham số
        event_list = None
        if event_types:
            event_list = [event.strip() for event in event_types.split(",") if event.strip()]

        zone_list = None
        if zone_ids:
            zone_list = [zone.strip() for zone in zone_ids.split(",") if zone.strip()]

        # Đăng ký máy khách
        client_id = await connection_manager.connect(
            websocket=websocket,
            stream_type="events",
            zone_ids=zone_list,
            event_types=event_list
        )

        logger.info(f"Máy khách WebSocket {client_id} đã kết nối để truyền phát sự kiện")

        # Gửi xác nhận
        await websocket.send_json({
            "type": "connection_established",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "config": {
                "event_types": event_list,
                "zone_ids": zone_list
            }
        })

        # Xử lý tin nhắn
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                await handle_websocket_message(client_id, data, websocket)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Lỗi trong WebSocket sự kiện: {e}")

    except WebSocketDisconnect:
        logger.info(f"Máy khách WebSocket sự kiện {client_id} đã ngắt kết nối")
    except Exception as e:
        logger.error(f"Lỗi WebSocket sự kiện: {e}")
    finally:
        if client_id:
            await connection_manager.disconnect(client_id)


async def handle_websocket_message(client_id: str, data: Dict[str, Any], websocket: WebSocket):
    """Xử lý tin nhắn WebSocket đến."""
    message_type = data.get("type")

    if message_type == "ping":
        await websocket.send_json({
            "type": "pong",
            "timestamp": datetime.utcnow().isoformat()
        })

    elif message_type == "update_config":
        # Cập nhật cấu hình máy khách
        config = data.get("config", {})
        await connection_manager.update_client_config(client_id, config)

        await websocket.send_json({
            "type": "config_updated",
            "timestamp": datetime.utcnow().isoformat(),
            "config": config
        })

    elif message_type == "get_status":
        # Gửi trạng thái hiện tại
        status = await connection_manager.get_client_status(client_id)
        await websocket.send_json({
            "type": "status",
            "timestamp": datetime.utcnow().isoformat(),
            "status": status
        })

    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Loại tin nhắn không xác định: {message_type}"
        })


# Các endpoint HTTP cho quản lý luồng
@router.get("/status", response_model=StreamStatus)
async def get_stream_status(
    stream_service: StreamService = Depends(get_stream_service)
):
    """Lấy trạng thái truyền phát hiện tại."""
    try:
        status = await stream_service.get_status()
        connections = await connection_manager.get_connection_stats()

        # Tính thời gian hoạt động (đơn giản hóa tạm thời)
        uptime_seconds = 0.0
        if status.get("running", False):
            uptime_seconds = 3600.0  # Mặc định 1 giờ cho demo

        return StreamStatus(
            is_active=status.get("running", False),
            connected_clients=connections.get("total_clients", status["connections"]["active"]),
            streams=[{
                "type": "pose_stream",
                "active": status.get("running", False),
                "buffer_size": status["buffers"]["pose_buffer_size"]
            }],
            uptime_seconds=uptime_seconds
        )

    except Exception as e:
        logger.error(f"Lỗi khi lấy trạng thái luồng: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy trạng thái luồng: {str(e)}"
        )


@router.post("/start")
async def start_streaming(
    stream_service: StreamService = Depends(get_stream_service),
    current_user: Dict = Depends(require_auth)
):
    """Khởi động dịch vụ truyền phát."""
    try:
        logger.info(f"Đang khởi động dịch vụ truyền phát bởi người dùng: {current_user['id']}")

        if await stream_service.is_active():
            return JSONResponse(
                status_code=200,
                content={"message": "Dịch vụ truyền phát đã đang hoạt động"}
            )

        await stream_service.start()

        return {
            "message": "Dịch vụ truyền phát đã khởi động thành công",
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Lỗi khi khởi động truyền phát: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể khởi động truyền phát: {str(e)}"
        )


@router.post("/stop")
async def stop_streaming(
    stream_service: StreamService = Depends(get_stream_service),
    current_user: Dict = Depends(require_auth)
):
    """Dừng dịch vụ truyền phát."""
    try:
        logger.info(f"Đang dừng dịch vụ truyền phát bởi người dùng: {current_user['id']}")

        await stream_service.stop()
        await connection_manager.disconnect_all()

        return {
            "message": "Dịch vụ truyền phát đã dừng thành công",
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Lỗi khi dừng truyền phát: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể dừng truyền phát: {str(e)}"
        )


@router.get("/clients")
async def get_connected_clients(
    current_user: Dict = Depends(require_auth)
):
    """Lấy danh sách máy khách WebSocket đã kết nối."""
    try:
        clients = await connection_manager.get_connected_clients()

        return {
            "total_clients": len(clients),
            "clients": clients,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách máy khách đã kết nối: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy danh sách máy khách đã kết nối: {str(e)}"
        )


@router.delete("/clients/{client_id}")
async def disconnect_client(
    client_id: str,
    current_user: Dict = Depends(require_auth)
):
    """Ngắt kết nối một máy khách WebSocket cụ thể."""
    try:
        logger.info(f"Đang ngắt kết nối máy khách {client_id} bởi người dùng: {current_user['id']}")

        success = await connection_manager.disconnect(client_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy máy khách {client_id}"
            )

        return {
            "message": f"Máy khách {client_id} đã ngắt kết nối thành công",
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi ngắt kết nối máy khách: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể ngắt kết nối máy khách: {str(e)}"
        )


@router.post("/broadcast")
async def broadcast_message(
    message: Dict[str, Any],
    stream_type: Optional[str] = Query(None, description="Loại luồng đích"),
    zone_ids: Optional[List[str]] = Query(None, description="ID khu vực đích"),
    current_user: Dict = Depends(require_auth)
):
    """Phát sóng tin nhắn đến các máy khách WebSocket đã kết nối."""
    try:
        logger.info(f"Đang phát sóng tin nhắn bởi người dùng: {current_user['id']}")

        # Thêm siêu dữ liệu vào tin nhắn
        broadcast_data = {
            **message,
            "broadcast_timestamp": datetime.utcnow().isoformat(),
            "sender": current_user["id"]
        }

        # Phát sóng đến các máy khách phù hợp
        sent_count = await connection_manager.broadcast(
            data=broadcast_data,
            stream_type=stream_type,
            zone_ids=zone_ids
        )

        return {
            "message": "Phát sóng thành công",
            "recipients": sent_count,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Lỗi khi phát sóng tin nhắn: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể phát sóng tin nhắn: {str(e)}"
        )


@router.get("/metrics")
async def get_streaming_metrics():
    """Lấy số liệu hiệu suất truyền phát."""
    try:
        metrics = await connection_manager.get_metrics()

        return {
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy số liệu truyền phát: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy số liệu truyền phát: {str(e)}"
        )
