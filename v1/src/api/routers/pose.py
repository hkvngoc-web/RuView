"""
Các endpoint API ước lượng tư thế
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.dependencies import (
    get_pose_service,
    get_hardware_service,
    get_current_user,
    require_auth
)
from src.services.pose_service import PoseService
from src.services.hardware_service import HardwareService
from src.config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Mô hình yêu cầu/phản hồi
class PoseEstimationRequest(BaseModel):
    """Mô hình yêu cầu cho ước lượng tư thế."""

    zone_ids: Optional[List[str]] = Field(
        default=None,
        description="Các khu vực cụ thể để phân tích (tất cả khu vực nếu không chỉ định)"
    )
    confidence_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Ngưỡng độ tin cậy tối thiểu cho phát hiện"
    )
    max_persons: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Số người tối đa để phát hiện"
    )
    include_keypoints: bool = Field(
        default=True,
        description="Bao gồm dữ liệu điểm mấu chốt chi tiết"
    )
    include_segmentation: bool = Field(
        default=False,
        description="Bao gồm mặt nạ phân đoạn DensePose"
    )


class PersonPose(BaseModel):
    """Mô hình dữ liệu tư thế người."""

    person_id: str = Field(..., description="Định danh người duy nhất")
    confidence: float = Field(..., description="Điểm độ tin cậy phát hiện")
    bounding_box: Dict[str, float] = Field(..., description="Khung giới hạn người")
    keypoints: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Điểm mấu chốt cơ thể với tọa độ và độ tin cậy"
    )
    segmentation: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dữ liệu phân đoạn DensePose"
    )
    zone_id: Optional[str] = Field(
        default=None,
        description="Khu vực nơi người được phát hiện"
    )
    activity: Optional[str] = Field(
        default=None,
        description="Hoạt động được phát hiện"
    )
    timestamp: datetime = Field(..., description="Thời gian phát hiện")


class PoseEstimationResponse(BaseModel):
    """Mô hình phản hồi cho ước lượng tư thế."""

    timestamp: datetime = Field(..., description="Thời gian phân tích")
    frame_id: str = Field(..., description="Định danh khung hình duy nhất")
    persons: List[PersonPose] = Field(..., description="Những người được phát hiện")
    zone_summary: Dict[str, int] = Field(..., description="Số người mỗi khu vực")
    processing_time_ms: float = Field(..., description="Thời gian xử lý tính bằng mili giây")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Siêu dữ liệu bổ sung")


class HistoricalDataRequest(BaseModel):
    """Mô hình yêu cầu cho dữ liệu tư thế lịch sử."""

    start_time: datetime = Field(..., description="Thời gian bắt đầu cho truy vấn dữ liệu")
    end_time: datetime = Field(..., description="Thời gian kết thúc cho truy vấn dữ liệu")
    zone_ids: Optional[List[str]] = Field(
        default=None,
        description="Lọc theo khu vực cụ thể"
    )
    aggregation_interval: Optional[int] = Field(
        default=300,
        ge=60,
        le=3600,
        description="Khoảng thời gian tổng hợp tính bằng giây"
    )
    include_raw_data: bool = Field(
        default=False,
        description="Bao gồm dữ liệu phát hiện thô"
    )


# Các endpoint
@router.get("/current", response_model=PoseEstimationResponse)
async def get_current_pose_estimation(
    request: PoseEstimationRequest = Depends(),
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy ước lượng tư thế hiện tại từ tín hiệu WiFi."""
    try:
        logger.info(f"Đang xử lý yêu cầu ước lượng tư thế từ người dùng: {current_user.get('id') if current_user else 'ẩn danh'}")

        # Lấy ước lượng tư thế hiện tại
        result = await pose_service.estimate_poses(
            zone_ids=request.zone_ids,
            confidence_threshold=request.confidence_threshold,
            max_persons=request.max_persons,
            include_keypoints=request.include_keypoints,
            include_segmentation=request.include_segmentation
        )

        return PoseEstimationResponse(**result)

    except Exception as e:
        logger.error(f"Lỗi trong ước lượng tư thế: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Ước lượng tư thế thất bại: {str(e)}"
        )


@router.post("/analyze", response_model=PoseEstimationResponse)
async def analyze_pose_data(
    request: PoseEstimationRequest,
    background_tasks: BackgroundTasks,
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Dict = Depends(require_auth)
):
    """Kích hoạt phân tích tư thế với tham số tùy chỉnh."""
    try:
        logger.info(f"Phân tích tư thế tùy chỉnh được yêu cầu bởi người dùng: {current_user['id']}")

        # Kích hoạt phân tích
        result = await pose_service.analyze_with_params(
            zone_ids=request.zone_ids,
            confidence_threshold=request.confidence_threshold,
            max_persons=request.max_persons,
            include_keypoints=request.include_keypoints,
            include_segmentation=request.include_segmentation
        )

        # Lên lịch xử lý nền nếu cần
        if request.include_segmentation:
            background_tasks.add_task(
                pose_service.process_segmentation_data,
                result["frame_id"]
            )

        return PoseEstimationResponse(**result)

    except Exception as e:
        logger.error(f"Lỗi trong phân tích tư thế: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Phân tích tư thế thất bại: {str(e)}"
        )


@router.get("/zones/{zone_id}/occupancy")
async def get_zone_occupancy(
    zone_id: str,
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy số người hiện tại cho khu vực cụ thể."""
    try:
        occupancy = await pose_service.get_zone_occupancy(zone_id)

        if occupancy is None:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy khu vực '{zone_id}'"
            )

        return {
            "zone_id": zone_id,
            "current_occupancy": occupancy["count"],
            "max_occupancy": occupancy.get("max_occupancy"),
            "persons": occupancy["persons"],
            "timestamp": occupancy["timestamp"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi lấy số người khu vực: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy số người khu vực: {str(e)}"
        )


@router.get("/zones/summary")
async def get_zones_summary(
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy tóm tắt số người cho tất cả khu vực."""
    try:
        summary = await pose_service.get_zones_summary()

        return {
            "timestamp": datetime.utcnow(),
            "total_persons": summary["total_persons"],
            "zones": summary["zones"],
            "active_zones": summary["active_zones"]
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy tóm tắt khu vực: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy tóm tắt khu vực: {str(e)}"
        )


@router.post("/historical")
async def get_historical_data(
    request: HistoricalDataRequest,
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Dict = Depends(require_auth)
):
    """Lấy dữ liệu ước lượng tư thế lịch sử."""
    try:
        # Xác thực phạm vi thời gian
        if request.end_time <= request.start_time:
            raise HTTPException(
                status_code=400,
                detail="Thời gian kết thúc phải sau thời gian bắt đầu"
            )

        # Giới hạn phạm vi truy vấn để tránh dữ liệu quá lớn
        max_range = timedelta(days=7)
        if request.end_time - request.start_time > max_range:
            raise HTTPException(
                status_code=400,
                detail="Phạm vi truy vấn không thể vượt quá 7 ngày"
            )

        data = await pose_service.get_historical_data(
            start_time=request.start_time,
            end_time=request.end_time,
            zone_ids=request.zone_ids,
            aggregation_interval=request.aggregation_interval,
            include_raw_data=request.include_raw_data
        )

        return {
            "query": {
                "start_time": request.start_time,
                "end_time": request.end_time,
                "zone_ids": request.zone_ids,
                "aggregation_interval": request.aggregation_interval
            },
            "data": data["aggregated_data"],
            "raw_data": data.get("raw_data") if request.include_raw_data else None,
            "total_records": data["total_records"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi lấy dữ liệu lịch sử: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy dữ liệu lịch sử: {str(e)}"
        )


@router.get("/activities")
async def get_detected_activities(
    zone_id: Optional[str] = Query(None, description="Lọc theo ID khu vực"),
    limit: int = Query(10, ge=1, le=100, description="Số hoạt động tối đa"),
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy các hoạt động được phát hiện gần đây."""
    try:
        activities = await pose_service.get_recent_activities(
            zone_id=zone_id,
            limit=limit
        )

        return {
            "activities": activities,
            "total_count": len(activities),
            "zone_id": zone_id
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy hoạt động: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy hoạt động: {str(e)}"
        )


@router.post("/calibrate")
async def calibrate_pose_system(
    background_tasks: BackgroundTasks,
    pose_service: PoseService = Depends(get_pose_service),
    hardware_service: HardwareService = Depends(get_hardware_service),
    current_user: Dict = Depends(require_auth)
):
    """Hiệu chuẩn hệ thống ước lượng tư thế."""
    try:
        logger.info(f"Hiệu chuẩn hệ thống tư thế được khởi tạo bởi người dùng: {current_user['id']}")

        # Kiểm tra xem hiệu chuẩn có đang diễn ra không
        if await pose_service.is_calibrating():
            raise HTTPException(
                status_code=409,
                detail="Hiệu chuẩn đang diễn ra"
            )

        # Bắt đầu quá trình hiệu chuẩn
        calibration_id = await pose_service.start_calibration()

        # Lên lịch tác vụ hiệu chuẩn nền
        background_tasks.add_task(
            pose_service.run_calibration,
            calibration_id
        )

        return {
            "calibration_id": calibration_id,
            "status": "đã bắt đầu",
            "estimated_duration_minutes": 5,
            "message": "Quá trình hiệu chuẩn đã bắt đầu"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi bắt đầu hiệu chuẩn: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể bắt đầu hiệu chuẩn: {str(e)}"
        )


@router.get("/calibration/status")
async def get_calibration_status(
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Dict = Depends(require_auth)
):
    """Lấy trạng thái hiệu chuẩn hiện tại."""
    try:
        status = await pose_service.get_calibration_status()

        return {
            "is_calibrating": status["is_calibrating"],
            "calibration_id": status.get("calibration_id"),
            "progress_percent": status.get("progress_percent", 0),
            "current_step": status.get("current_step"),
            "estimated_remaining_minutes": status.get("estimated_remaining_minutes"),
            "last_calibration": status.get("last_calibration")
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy trạng thái hiệu chuẩn: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy trạng thái hiệu chuẩn: {str(e)}"
        )


@router.get("/stats")
async def get_pose_statistics(
    hours: int = Query(24, ge=1, le=168, description="Số giờ dữ liệu để phân tích"),
    pose_service: PoseService = Depends(get_pose_service),
    current_user: Optional[Dict] = Depends(get_current_user)
):
    """Lấy thống kê ước lượng tư thế."""
    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        stats = await pose_service.get_statistics(
            start_time=start_time,
            end_time=end_time
        )

        return {
            "period": {
                "start_time": start_time,
                "end_time": end_time,
                "hours": hours
            },
            "statistics": stats
        }

    except Exception as e:
        logger.error(f"Lỗi khi lấy thống kê: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Không thể lấy thống kê: {str(e)}"
        )
