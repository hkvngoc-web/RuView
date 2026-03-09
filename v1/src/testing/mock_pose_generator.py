"""
Trình tạo dữ liệu tư thế giả lập cho kiểm thử và phát triển.

Module này cung cấp dữ liệu ước lượng tư thế tổng hợp để sử dụng trong môi trường
phát triển và kiểm thử CHỈ. Dữ liệu được tạo mô phỏng kết quả phát hiện tư thế
con người thực tế bao gồm điểm mấu chốt, hộp bao, và hoạt động.

CẢNH BÁO: Module này sử dụng tạo số ngẫu nhiên có chủ đích cho dữ liệu kiểm thử.
KHÔNG sử dụng module này trong đường dẫn dữ liệu sản xuất.
"""

import random
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Biểu ngữ hiển thị khi chế độ tư thế giả lập đang hoạt động
MOCK_POSE_BANNER = """
================================================================================
  CẢNH BÁO: CHẾ ĐỘ TƯ THẾ GIẢ LẬP ĐANG HOẠT ĐỘNG - Sử dụng dữ liệu tư thế tổng hợp

  Tất cả phát hiện tư thế được tạo ngẫu nhiên và KHÔNG đại diện cho con người thực.
  Để ước lượng tư thế thực, cung cấp trọng số mô hình đã huấn luyện và dữ liệu CSI thực.
  Xem docs/hardware-setup.md để biết hướng dẫn cấu hình.
================================================================================
"""

_banner_shown = False


def _show_banner() -> None:
    """Hiển thị biểu ngữ cảnh báo chế độ tư thế giả lập (một lần mỗi phiên)."""
    global _banner_shown
    if not _banner_shown:
        logger.warning(MOCK_POSE_BANNER)
        _banner_shown = True


def generate_mock_keypoints() -> List[Dict[str, Any]]:
    """Tạo điểm mấu chốt giả lập cho một người.

    Trả về:
        Danh sách 17 dictionary điểm mấu chốt định dạng COCO với tên, x, y, độ tin cậy.
    """
    keypoint_names = [
        "nose", "left_eye", "right_eye", "left_ear", "right_ear",
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
    ]

    keypoints = []
    for name in keypoint_names:
        keypoints.append({
            "name": name,
            "x": random.uniform(0.1, 0.9),
            "y": random.uniform(0.1, 0.9),
            "confidence": random.uniform(0.5, 0.95),
        })

    return keypoints


def generate_mock_bounding_box() -> Dict[str, float]:
    """Tạo hộp bao giả lập cho một người.

    Trả về:
        Dictionary với x, y, width, height dưới dạng tọa độ chuẩn hóa.
    """
    x = random.uniform(0.1, 0.6)
    y = random.uniform(0.1, 0.6)
    width = random.uniform(0.2, 0.4)
    height = random.uniform(0.3, 0.5)

    return {"x": x, "y": y, "width": width, "height": height}


def generate_mock_poses(max_persons: int = 3) -> List[Dict[str, Any]]:
    """Tạo phát hiện tư thế giả lập cho kiểm thử.

    Tham số:
        max_persons: Số người tối đa để tạo (1 đến max_persons).

    Trả về:
        Danh sách dictionary phát hiện tư thế.
    """
    _show_banner()

    num_persons = random.randint(1, min(3, max_persons))
    poses = []

    for i in range(num_persons):
        confidence = random.uniform(0.3, 0.95)

        pose = {
            "person_id": i,
            "confidence": confidence,
            "keypoints": generate_mock_keypoints(),
            "bounding_box": generate_mock_bounding_box(),
            "activity": random.choice(["standing", "sitting", "walking", "lying"]),
            "timestamp": datetime.now().isoformat(),
        }

        poses.append(pose)

    return poses


def generate_mock_zone_occupancy(zone_id: str) -> Dict[str, Any]:
    """Tạo dữ liệu chiếm dụng khu vực giả lập.

    Tham số:
        zone_id: Mã định danh khu vực.

    Trả về:
        Dictionary với số lượng chiếm dụng và chi tiết từng người.
    """
    _show_banner()

    count = random.randint(0, 5)
    persons = []

    for i in range(count):
        persons.append({
            "person_id": f"person_{i}",
            "confidence": random.uniform(0.7, 0.95),
            "activity": random.choice(["standing", "sitting", "walking"]),
        })

    return {
        "count": count,
        "max_occupancy": 10,
        "persons": persons,
        "timestamp": datetime.now(),
    }


def generate_mock_zones_summary(
    zone_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Tạo tóm tắt dữ liệu các khu vực giả lập.

    Tham số:
        zone_ids: Danh sách mã định danh khu vực. Mặc định là zone_1 đến zone_4.

    Trả về:
        Dictionary với chiếm dụng theo khu vực và tổng hợp số lượng.
    """
    _show_banner()

    zones = zone_ids or ["zone_1", "zone_2", "zone_3", "zone_4"]
    zone_data = {}
    total_persons = 0
    active_zones = 0

    for zone_id in zones:
        count = random.randint(0, 3)
        zone_data[zone_id] = {
            "occupancy": count,
            "max_occupancy": 10,
            "status": "active" if count > 0 else "inactive",
        }
        total_persons += count
        if count > 0:
            active_zones += 1

    return {
        "total_persons": total_persons,
        "zones": zone_data,
        "active_zones": active_zones,
    }


def generate_mock_historical_data(
    start_time: datetime,
    end_time: datetime,
    zone_ids: Optional[List[str]] = None,
    aggregation_interval: int = 300,
    include_raw_data: bool = False,
) -> Dict[str, Any]:
    """Tạo dữ liệu tư thế lịch sử giả lập.

    Tham số:
        start_time: Thời điểm bắt đầu khoảng thời gian.
        end_time: Thời điểm kết thúc khoảng thời gian.
        zone_ids: Các khu vực cần bao gồm. Mặc định là zone_1, zone_2, zone_3.
        aggregation_interval: Số giây giữa các điểm dữ liệu.
        include_raw_data: Có bao gồm phát hiện thô mô phỏng hay không.

    Trả về:
        Dictionary với aggregated_data, raw_data tùy chọn, và total_records.
    """
    _show_banner()

    zones = zone_ids or ["zone_1", "zone_2", "zone_3"]
    current_time = start_time
    aggregated_data = []
    raw_data = [] if include_raw_data else None

    while current_time < end_time:
        data_point = {
            "timestamp": current_time,
            "total_persons": random.randint(0, 8),
            "zones": {},
        }

        for zone_id in zones:
            data_point["zones"][zone_id] = {
                "occupancy": random.randint(0, 3),
                "avg_confidence": random.uniform(0.7, 0.95),
            }

        aggregated_data.append(data_point)

        if include_raw_data:
            for _ in range(random.randint(0, 5)):
                raw_data.append({
                    "timestamp": current_time + timedelta(seconds=random.randint(0, aggregation_interval)),
                    "person_id": f"person_{random.randint(1, 10)}",
                    "zone_id": random.choice(zones),
                    "confidence": random.uniform(0.5, 0.95),
                    "activity": random.choice(["standing", "sitting", "walking"]),
                })

        current_time += timedelta(seconds=aggregation_interval)

    return {
        "aggregated_data": aggregated_data,
        "raw_data": raw_data,
        "total_records": len(aggregated_data),
    }


def generate_mock_recent_activities(
    zone_id: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Tạo dữ liệu hoạt động gần đây giả lập.

    Tham số:
        zone_id: Bộ lọc khu vực tùy chọn. Nếu None, các khu vực ngẫu nhiên được sử dụng.
        limit: Số hoạt động cần tạo.

    Trả về:
        Danh sách dictionary hoạt động.
    """
    _show_banner()

    activities = []

    for i in range(limit):
        activity = {
            "activity_id": f"activity_{i}",
            "person_id": f"person_{random.randint(1, 5)}",
            "zone_id": zone_id or random.choice(["zone_1", "zone_2", "zone_3"]),
            "activity": random.choice(["standing", "sitting", "walking", "lying"]),
            "confidence": random.uniform(0.6, 0.95),
            "timestamp": datetime.now() - timedelta(minutes=random.randint(0, 60)),
            "duration_seconds": random.randint(10, 300),
        }
        activities.append(activity)

    return activities


def generate_mock_statistics(
    start_time: datetime,
    end_time: datetime,
) -> Dict[str, Any]:
    """Tạo thống kê ước lượng tư thế giả lập.

    Tham số:
        start_time: Thời điểm bắt đầu khoảng thống kê.
        end_time: Thời điểm kết thúc khoảng thống kê.

    Trả về:
        Dictionary với số lượng phát hiện, tỷ lệ, và phân bố.
    """
    _show_banner()

    total_detections = random.randint(100, 1000)
    successful_detections = int(total_detections * random.uniform(0.8, 0.95))

    return {
        "total_detections": total_detections,
        "successful_detections": successful_detections,
        "failed_detections": total_detections - successful_detections,
        "success_rate": successful_detections / total_detections,
        "average_confidence": random.uniform(0.75, 0.90),
        "average_processing_time_ms": random.uniform(50, 200),
        "unique_persons": random.randint(5, 20),
        "most_active_zone": random.choice(["zone_1", "zone_2", "zone_3"]),
        "activity_distribution": {
            "standing": random.uniform(0.3, 0.5),
            "sitting": random.uniform(0.2, 0.4),
            "walking": random.uniform(0.1, 0.3),
            "lying": random.uniform(0.0, 0.1),
        },
    }
