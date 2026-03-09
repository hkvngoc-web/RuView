"""
Tiện ích kiểm thử cho WiFi-DensePose.

Module này chứa các bộ tạo dữ liệu giả lập và trợ giúp kiểm thử
CHỈ dành cho sử dụng trong môi trường phát triển/kiểm thử. Các bộ tạo
này sản xuất dữ liệu tổ hợp mô phỏng các mẫu dữ liệu CSI và tư thế thực.

CẢNH BÁO: Mã trong module này sử dụng sinh số ngẫu nhiên có chủ đích
cho dữ liệu giả lập/kiểm thử. KHÔNG import từ module này trong các đường dẫn
mã sản xuất trừ khi nằm sau cờ mock_mode rõ ràng với logging phù hợp.
"""

from .mock_csi_generator import MockCSIGenerator
from .mock_pose_generator import generate_mock_poses, generate_mock_keypoints, generate_mock_bounding_box

__all__ = [
    "MockCSIGenerator",
    "generate_mock_poses",
    "generate_mock_keypoints",
    "generate_mock_bounding_box",
]
