"""
Tác vụ dọn dẹp định kỳ cho WiFi-DensePose API
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager

from sqlalchemy import delete, select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.database.connection import get_database_manager
from src.database.models import (
    CSIData, PoseDetection, SystemMetric, AuditLog, Session, Device
)
from src.logger import get_logger

logger = get_logger(__name__)


class CleanupTask:
    """Lớp cơ sở cho các tác vụ dọn dẹp."""

    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.settings = settings
        self.enabled = True
        self.last_run = None
        self.run_count = 0
        self.error_count = 0
        self.total_cleaned = 0

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi tác vụ dọn dẹp."""
        raise NotImplementedError

    async def run(self, session: AsyncSession) -> Dict[str, Any]:
        """Chạy tác vụ dọn dẹp với xử lý lỗi."""
        start_time = datetime.utcnow()

        try:
            logger.info(f"Đang bắt đầu tác vụ dọn dẹp: {self.name}")

            result = await self.execute(session)

            self.last_run = start_time
            self.run_count += 1

            if result.get("cleaned_count", 0) > 0:
                self.total_cleaned += result["cleaned_count"]
                logger.info(
                    f"Tác vụ dọn dẹp {self.name} hoàn tất: "
                    f"đã dọn {result['cleaned_count']} mục"
                )
            else:
                logger.debug(f"Tác vụ dọn dẹp {self.name} hoàn tất: không có mục cần dọn")

            return {
                "task": self.name,
                "status": "success",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                **result
            }

        except Exception as e:
            self.error_count += 1
            logger.error(f"Tác vụ dọn dẹp {self.name} thất bại: {e}", exc_info=True)

            return {
                "task": self.name,
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                "error": str(e),
                "cleaned_count": 0
            }

    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê tác vụ."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "total_cleaned": self.total_cleaned,
        }


class OldCSIDataCleanup(CleanupTask):
    """Dọn dẹp bản ghi dữ liệu CSI cũ."""

    def __init__(self, settings: Settings):
        super().__init__("old_csi_data_cleanup", settings)
        self.retention_days = settings.csi_data_retention_days
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp dữ liệu CSI."""
        if self.retention_days <= 0:
            return {"cleaned_count": 0, "message": "Lưu giữ dữ liệu CSI đã tắt"}

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)

        # Đếm bản ghi cần xóa
        count_query = select(func.count(CSIData.id)).where(
            CSIData.created_at < cutoff_date
        )
        total_count = await session.scalar(count_query)

        if total_count == 0:
            return {"cleaned_count": 0, "message": "Không có dữ liệu CSI cũ cần dọn"}

        # Xóa theo lô
        cleaned_count = 0
        while cleaned_count < total_count:
            # Lấy lô ID cần xóa
            id_query = select(CSIData.id).where(
                CSIData.created_at < cutoff_date
            ).limit(self.batch_size)

            result = await session.execute(id_query)
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Xóa lô
            delete_query = delete(CSIData).where(CSIData.id.in_(ids_to_delete))
            await session.execute(delete_query)
            await session.commit()

            batch_size = len(ids_to_delete)
            cleaned_count += batch_size

            logger.debug(f"Đã xóa {batch_size} bản ghi dữ liệu CSI (tổng: {cleaned_count})")

            # Tạm dừng nhỏ để tránh quá tải cơ sở dữ liệu
            await asyncio.sleep(0.1)

        return {
            "cleaned_count": cleaned_count,
            "retention_days": self.retention_days,
            "cutoff_date": cutoff_date.isoformat()
        }


class OldPoseDetectionCleanup(CleanupTask):
    """Dọn dẹp bản ghi phát hiện tư thế cũ."""

    def __init__(self, settings: Settings):
        super().__init__("old_pose_detection_cleanup", settings)
        self.retention_days = settings.pose_detection_retention_days
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp phát hiện tư thế."""
        if self.retention_days <= 0:
            return {"cleaned_count": 0, "message": "Lưu giữ phát hiện tư thế đã tắt"}

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)

        # Đếm bản ghi cần xóa
        count_query = select(func.count(PoseDetection.id)).where(
            PoseDetection.created_at < cutoff_date
        )
        total_count = await session.scalar(count_query)

        if total_count == 0:
            return {"cleaned_count": 0, "message": "Không có phát hiện tư thế cũ cần dọn"}

        # Xóa theo lô
        cleaned_count = 0
        while cleaned_count < total_count:
            # Lấy lô ID cần xóa
            id_query = select(PoseDetection.id).where(
                PoseDetection.created_at < cutoff_date
            ).limit(self.batch_size)

            result = await session.execute(id_query)
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Xóa lô
            delete_query = delete(PoseDetection).where(PoseDetection.id.in_(ids_to_delete))
            await session.execute(delete_query)
            await session.commit()

            batch_size = len(ids_to_delete)
            cleaned_count += batch_size

            logger.debug(f"Đã xóa {batch_size} bản ghi phát hiện tư thế (tổng: {cleaned_count})")

            # Tạm dừng nhỏ để tránh quá tải cơ sở dữ liệu
            await asyncio.sleep(0.1)

        return {
            "cleaned_count": cleaned_count,
            "retention_days": self.retention_days,
            "cutoff_date": cutoff_date.isoformat()
        }


class OldMetricsCleanup(CleanupTask):
    """Dọn dẹp số liệu hệ thống cũ."""

    def __init__(self, settings: Settings):
        super().__init__("old_metrics_cleanup", settings)
        self.retention_days = settings.metrics_retention_days
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp số liệu."""
        if self.retention_days <= 0:
            return {"cleaned_count": 0, "message": "Lưu giữ số liệu đã tắt"}

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)

        # Đếm bản ghi cần xóa
        count_query = select(func.count(SystemMetric.id)).where(
            SystemMetric.created_at < cutoff_date
        )
        total_count = await session.scalar(count_query)

        if total_count == 0:
            return {"cleaned_count": 0, "message": "Không có số liệu cũ cần dọn"}

        # Xóa theo lô
        cleaned_count = 0
        while cleaned_count < total_count:
            # Lấy lô ID cần xóa
            id_query = select(SystemMetric.id).where(
                SystemMetric.created_at < cutoff_date
            ).limit(self.batch_size)

            result = await session.execute(id_query)
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Xóa lô
            delete_query = delete(SystemMetric).where(SystemMetric.id.in_(ids_to_delete))
            await session.execute(delete_query)
            await session.commit()

            batch_size = len(ids_to_delete)
            cleaned_count += batch_size

            logger.debug(f"Đã xóa {batch_size} bản ghi số liệu (tổng: {cleaned_count})")

            # Tạm dừng nhỏ để tránh quá tải cơ sở dữ liệu
            await asyncio.sleep(0.1)

        return {
            "cleaned_count": cleaned_count,
            "retention_days": self.retention_days,
            "cutoff_date": cutoff_date.isoformat()
        }


class OldAuditLogCleanup(CleanupTask):
    """Dọn dẹp nhật ký kiểm toán cũ."""

    def __init__(self, settings: Settings):
        super().__init__("old_audit_log_cleanup", settings)
        self.retention_days = settings.audit_log_retention_days
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp nhật ký kiểm toán."""
        if self.retention_days <= 0:
            return {"cleaned_count": 0, "message": "Lưu giữ nhật ký kiểm toán đã tắt"}

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)

        # Đếm bản ghi cần xóa
        count_query = select(func.count(AuditLog.id)).where(
            AuditLog.created_at < cutoff_date
        )
        total_count = await session.scalar(count_query)

        if total_count == 0:
            return {"cleaned_count": 0, "message": "Không có nhật ký kiểm toán cũ cần dọn"}

        # Xóa theo lô
        cleaned_count = 0
        while cleaned_count < total_count:
            # Lấy lô ID cần xóa
            id_query = select(AuditLog.id).where(
                AuditLog.created_at < cutoff_date
            ).limit(self.batch_size)

            result = await session.execute(id_query)
            ids_to_delete = [row[0] for row in result.fetchall()]

            if not ids_to_delete:
                break

            # Xóa lô
            delete_query = delete(AuditLog).where(AuditLog.id.in_(ids_to_delete))
            await session.execute(delete_query)
            await session.commit()

            batch_size = len(ids_to_delete)
            cleaned_count += batch_size

            logger.debug(f"Đã xóa {batch_size} bản ghi nhật ký kiểm toán (tổng: {cleaned_count})")

            # Tạm dừng nhỏ để tránh quá tải cơ sở dữ liệu
            await asyncio.sleep(0.1)

        return {
            "cleaned_count": cleaned_count,
            "retention_days": self.retention_days,
            "cutoff_date": cutoff_date.isoformat()
        }


class OrphanedSessionCleanup(CleanupTask):
    """Dọn dẹp phiên mồ côi (phiên không có dữ liệu liên kết)."""

    def __init__(self, settings: Settings):
        super().__init__("orphaned_session_cleanup", settings)
        self.orphan_threshold_days = settings.orphaned_session_threshold_days
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp phiên mồ côi."""
        if self.orphan_threshold_days <= 0:
            return {"cleaned_count": 0, "message": "Dọn dẹp phiên mồ côi đã tắt"}

        cutoff_date = datetime.utcnow() - timedelta(days=self.orphan_threshold_days)

        # Tìm phiên cũ và không có dữ liệu CSI hoặc phát hiện tư thế liên kết
        orphaned_sessions_query = select(Session.id).where(
            and_(
                Session.created_at < cutoff_date,
                Session.status.in_(["completed", "failed", "cancelled"]),
                ~Session.id.in_(select(CSIData.session_id).where(CSIData.session_id.isnot(None))),
                ~Session.id.in_(select(PoseDetection.session_id))
            )
        )

        result = await session.execute(orphaned_sessions_query)
        orphaned_ids = [row[0] for row in result.fetchall()]

        if not orphaned_ids:
            return {"cleaned_count": 0, "message": "Không có phiên mồ côi cần dọn"}

        # Xóa phiên mồ côi
        delete_query = delete(Session).where(Session.id.in_(orphaned_ids))
        await session.execute(delete_query)
        await session.commit()

        cleaned_count = len(orphaned_ids)

        return {
            "cleaned_count": cleaned_count,
            "orphan_threshold_days": self.orphan_threshold_days,
            "cutoff_date": cutoff_date.isoformat()
        }


class InvalidDataCleanup(CleanupTask):
    """Dọn dẹp bản ghi dữ liệu không hợp lệ hoặc bị hỏng."""

    def __init__(self, settings: Settings):
        super().__init__("invalid_data_cleanup", settings)
        self.batch_size = settings.cleanup_batch_size

    async def execute(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi dọn dẹp dữ liệu không hợp lệ."""
        total_cleaned = 0

        # Dọn dữ liệu CSI không hợp lệ
        invalid_csi_query = select(CSIData.id).where(
            or_(
                CSIData.is_valid == False,
                CSIData.amplitude == None,
                CSIData.phase == None,
                CSIData.frequency <= 0,
                CSIData.bandwidth <= 0,
                CSIData.num_subcarriers <= 0
            )
        )

        result = await session.execute(invalid_csi_query)
        invalid_csi_ids = [row[0] for row in result.fetchall()]

        if invalid_csi_ids:
            delete_query = delete(CSIData).where(CSIData.id.in_(invalid_csi_ids))
            await session.execute(delete_query)
            total_cleaned += len(invalid_csi_ids)
            logger.debug(f"Đã xóa {len(invalid_csi_ids)} bản ghi dữ liệu CSI không hợp lệ")

        # Dọn phát hiện tư thế không hợp lệ
        invalid_pose_query = select(PoseDetection.id).where(
            or_(
                PoseDetection.is_valid == False,
                PoseDetection.person_count < 0,
                and_(
                    PoseDetection.detection_confidence.isnot(None),
                    or_(
                        PoseDetection.detection_confidence < 0,
                        PoseDetection.detection_confidence > 1
                    )
                )
            )
        )

        result = await session.execute(invalid_pose_query)
        invalid_pose_ids = [row[0] for row in result.fetchall()]

        if invalid_pose_ids:
            delete_query = delete(PoseDetection).where(PoseDetection.id.in_(invalid_pose_ids))
            await session.execute(delete_query)
            total_cleaned += len(invalid_pose_ids)
            logger.debug(f"Đã xóa {len(invalid_pose_ids)} bản ghi phát hiện tư thế không hợp lệ")

        await session.commit()

        return {
            "cleaned_count": total_cleaned,
            "invalid_csi_count": len(invalid_csi_ids) if invalid_csi_ids else 0,
            "invalid_pose_count": len(invalid_pose_ids) if invalid_pose_ids else 0,
        }


class CleanupManager:
    """Trình quản lý tất cả tác vụ dọn dẹp."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_manager = get_database_manager(settings)
        self.tasks = self._initialize_tasks()
        self.running = False
        self.last_run = None
        self.run_count = 0
        self.total_cleaned = 0

    def _initialize_tasks(self) -> List[CleanupTask]:
        """Khởi tạo tất cả tác vụ dọn dẹp."""
        tasks = [
            OldCSIDataCleanup(self.settings),
            OldPoseDetectionCleanup(self.settings),
            OldMetricsCleanup(self.settings),
            OldAuditLogCleanup(self.settings),
            OrphanedSessionCleanup(self.settings),
            InvalidDataCleanup(self.settings),
        ]

        # Lọc tác vụ đã bật
        enabled_tasks = [task for task in tasks if task.enabled]

        logger.info(f"Đã khởi tạo {len(enabled_tasks)} tác vụ dọn dẹp")
        return enabled_tasks

    async def run_all_tasks(self) -> Dict[str, Any]:
        """Chạy tất cả tác vụ dọn dẹp."""
        if self.running:
            return {"status": "already_running", "message": "Dọn dẹp đang tiến hành"}

        self.running = True
        start_time = datetime.utcnow()

        try:
            logger.info("Đang bắt đầu các tác vụ dọn dẹp")

            results = []
            total_cleaned = 0

            async with self.db_manager.get_async_session() as session:
                for task in self.tasks:
                    if not task.enabled:
                        continue

                    result = await task.run(session)
                    results.append(result)
                    total_cleaned += result.get("cleaned_count", 0)

            self.last_run = start_time
            self.run_count += 1
            self.total_cleaned += total_cleaned

            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                f"Các tác vụ dọn dẹp hoàn tất: đã dọn {total_cleaned} mục "
                f"trong {duration:.2f} giây"
            )

            return {
                "status": "completed",
                "start_time": start_time.isoformat(),
                "duration_seconds": duration,
                "total_cleaned": total_cleaned,
                "task_results": results,
            }

        except Exception as e:
            logger.error(f"Các tác vụ dọn dẹp thất bại: {e}", exc_info=True)
            return {
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
                "error": str(e),
                "total_cleaned": 0,
            }

        finally:
            self.running = False

    async def run_task(self, task_name: str) -> Dict[str, Any]:
        """Chạy một tác vụ dọn dẹp cụ thể."""
        task = next((t for t in self.tasks if t.name == task_name), None)

        if not task:
            return {
                "status": "error",
                "error": f"Không tìm thấy tác vụ '{task_name}'",
                "available_tasks": [t.name for t in self.tasks]
            }

        if not task.enabled:
            return {
                "status": "error",
                "error": f"Tác vụ '{task_name}' đã bị tắt"
            }

        async with self.db_manager.get_async_session() as session:
            return await task.run(session)

    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê trình quản lý dọn dẹp."""
        return {
            "manager": {
                "running": self.running,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "run_count": self.run_count,
                "total_cleaned": self.total_cleaned,
            },
            "tasks": [task.get_stats() for task in self.tasks],
        }

    def enable_task(self, task_name: str) -> bool:
        """Bật một tác vụ cụ thể."""
        task = next((t for t in self.tasks if t.name == task_name), None)
        if task:
            task.enabled = True
            return True
        return False

    def disable_task(self, task_name: str) -> bool:
        """Tắt một tác vụ cụ thể."""
        task = next((t for t in self.tasks if t.name == task_name), None)
        if task:
            task.enabled = False
            return True
        return False


# Thể hiện trình quản lý dọn dẹp toàn cục
_cleanup_manager: Optional[CleanupManager] = None


def get_cleanup_manager(settings: Settings) -> CleanupManager:
    """Lấy thể hiện trình quản lý dọn dẹp."""
    global _cleanup_manager
    if _cleanup_manager is None:
        _cleanup_manager = CleanupManager(settings)
    return _cleanup_manager


async def run_periodic_cleanup(settings: Settings):
    """Chạy tác vụ dọn dẹp định kỳ."""
    cleanup_manager = get_cleanup_manager(settings)

    while True:
        try:
            await cleanup_manager.run_all_tasks()

            # Chờ đến khoảng dọn dẹp tiếp theo
            await asyncio.sleep(settings.cleanup_interval_seconds)

        except asyncio.CancelledError:
            logger.info("Dọn dẹp định kỳ đã bị hủy")
            break
        except Exception as e:
            logger.error(f"Lỗi dọn dẹp định kỳ: {e}", exc_info=True)
            # Chờ trước khi thử lại
            await asyncio.sleep(60)
