"""
Tác vụ sao lưu cho WiFi-DensePose API
"""

import asyncio
import logging
import os
import shutil
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.database.connection import get_database_manager
from src.database.models import Device, Session, CSIData, PoseDetection, SystemMetric, AuditLog
from src.logger import get_logger

logger = get_logger(__name__)


class BackupTask:
    """Lớp cơ sở cho các tác vụ sao lưu."""

    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.settings = settings
        self.enabled = True
        self.last_run = None
        self.run_count = 0
        self.error_count = 0
        self.backup_dir = Path(settings.backup_directory)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    async def execute_backup(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi tác vụ sao lưu."""
        raise NotImplementedError

    async def run(self, session: AsyncSession) -> Dict[str, Any]:
        """Chạy tác vụ sao lưu với xử lý lỗi."""
        start_time = datetime.utcnow()

        try:
            logger.info(f"Đang bắt đầu tác vụ sao lưu: {self.name}")

            result = await self.execute_backup(session)

            self.last_run = start_time
            self.run_count += 1

            logger.info(
                f"Tác vụ sao lưu {self.name} hoàn tất: "
                f"đã sao lưu {result.get('backup_size_mb', 0):.2f} MB"
            )

            return {
                "task": self.name,
                "status": "success",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                **result
            }

        except Exception as e:
            self.error_count += 1
            logger.error(f"Tác vụ sao lưu {self.name} thất bại: {e}", exc_info=True)

            return {
                "task": self.name,
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                "error": str(e),
                "backup_size_mb": 0
            }

    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê tác vụ."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "backup_directory": str(self.backup_dir),
        }

    def _get_backup_filename(self, prefix: str, extension: str = ".gz") -> str:
        """Tạo tên file sao lưu với dấu thời gian."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}{extension}"

    def _get_file_size_mb(self, file_path: Path) -> float:
        """Lấy kích thước file tính bằng MB."""
        if file_path.exists():
            return file_path.stat().st_size / (1024 * 1024)
        return 0.0

    def _cleanup_old_backups(self, pattern: str, retention_days: int):
        """Dọn dẹp các file sao lưu cũ."""
        if retention_days <= 0:
            return

        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        for backup_file in self.backup_dir.glob(pattern):
            if backup_file.stat().st_mtime < cutoff_date.timestamp():
                try:
                    backup_file.unlink()
                    logger.debug(f"Đã xóa bản sao lưu cũ: {backup_file}")
                except Exception as e:
                    logger.warning(f"Xóa bản sao lưu cũ {backup_file} thất bại: {e}")


class DatabaseBackup(BackupTask):
    """Sao lưu toàn bộ cơ sở dữ liệu sử dụng pg_dump."""

    def __init__(self, settings: Settings):
        super().__init__("database_backup", settings)
        self.retention_days = settings.database_backup_retention_days

    async def execute_backup(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi sao lưu cơ sở dữ liệu."""
        backup_filename = self._get_backup_filename("database_full", ".sql.gz")
        backup_path = self.backup_dir / backup_filename

        # Xây dựng lệnh pg_dump
        pg_dump_cmd = [
            "pg_dump",
            "--verbose",
            "--no-password",
            "--format=custom",
            "--compress=9",
            "--file", str(backup_path),
        ]

        # Thêm tham số kết nối
        if self.settings.database_url:
            pg_dump_cmd.append(self.settings.database_url)
        else:
            pg_dump_cmd.extend([
                "--host", self.settings.db_host,
                "--port", str(self.settings.db_port),
                "--username", self.settings.db_user,
                "--dbname", self.settings.db_name,
            ])

        # Đặt biến môi trường
        env = os.environ.copy()
        if self.settings.db_password:
            env["PGPASSWORD"] = self.settings.db_password

        # Thực thi pg_dump
        process = await asyncio.create_subprocess_exec(
            *pg_dump_cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Lỗi pg_dump không xác định"
            raise Exception(f"pg_dump thất bại: {error_msg}")

        backup_size_mb = self._get_file_size_mb(backup_path)

        # Dọn dẹp bản sao lưu cũ
        self._cleanup_old_backups("database_full_*.sql.gz", self.retention_days)

        return {
            "backup_file": backup_filename,
            "backup_path": str(backup_path),
            "backup_size_mb": backup_size_mb,
            "retention_days": self.retention_days,
        }


class ConfigurationBackup(BackupTask):
    """Sao lưu file cấu hình và thiết lập."""

    def __init__(self, settings: Settings):
        super().__init__("configuration_backup", settings)
        self.retention_days = settings.config_backup_retention_days
        self.config_files = [
            "src/config/settings.py",
            ".env",
            "pyproject.toml",
            "docker-compose.yml",
            "Dockerfile",
        ]

    async def execute_backup(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi sao lưu cấu hình."""
        backup_filename = self._get_backup_filename("configuration", ".tar.gz")
        backup_path = self.backup_dir / backup_filename

        # Tạo thư mục tạm cho file cấu hình
        temp_dir = self.backup_dir / "temp_config"
        temp_dir.mkdir(exist_ok=True)

        try:
            copied_files = []

            # Sao chép file cấu hình
            for config_file in self.config_files:
                source_path = Path(config_file)
                if source_path.exists():
                    dest_path = temp_dir / source_path.name
                    shutil.copy2(source_path, dest_path)
                    copied_files.append(config_file)

            # Tạo bản kết xuất thiết lập
            settings_dump = {
                "backup_timestamp": datetime.utcnow().isoformat(),
                "environment": self.settings.environment,
                "debug": self.settings.debug,
                "version": self.settings.version,
                "database_settings": {
                    "db_host": self.settings.db_host,
                    "db_port": self.settings.db_port,
                    "db_name": self.settings.db_name,
                    "db_pool_size": self.settings.db_pool_size,
                },
                "redis_settings": {
                    "redis_enabled": self.settings.redis_enabled,
                    "redis_host": self.settings.redis_host,
                    "redis_port": self.settings.redis_port,
                    "redis_db": self.settings.redis_db,
                },
                "monitoring_settings": {
                    "monitoring_interval_seconds": self.settings.monitoring_interval_seconds,
                    "cleanup_interval_seconds": self.settings.cleanup_interval_seconds,
                },
            }

            settings_file = temp_dir / "settings_dump.json"
            with open(settings_file, 'w') as f:
                json.dump(settings_dump, f, indent=2)

            # Tạo kho lưu trữ tar.gz
            tar_cmd = [
                "tar", "-czf", str(backup_path),
                "-C", str(temp_dir),
                "."
            ]

            process = await asyncio.create_subprocess_exec(
                *tar_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Lỗi tar không xác định"
                raise Exception(f"tar thất bại: {error_msg}")

            backup_size_mb = self._get_file_size_mb(backup_path)

            # Dọn dẹp bản sao lưu cũ
            self._cleanup_old_backups("configuration_*.tar.gz", self.retention_days)

            return {
                "backup_file": backup_filename,
                "backup_path": str(backup_path),
                "backup_size_mb": backup_size_mb,
                "copied_files": copied_files,
                "retention_days": self.retention_days,
            }

        finally:
            # Dọn dẹp thư mục tạm
            if temp_dir.exists():
                shutil.rmtree(temp_dir)


class DataExportBackup(BackupTask):
    """Xuất dữ liệu bảng cụ thể sang định dạng JSON."""

    def __init__(self, settings: Settings):
        super().__init__("data_export_backup", settings)
        self.retention_days = settings.data_export_retention_days
        self.export_batch_size = 1000

    async def execute_backup(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi sao lưu xuất dữ liệu."""
        backup_filename = self._get_backup_filename("data_export", ".json.gz")
        backup_path = self.backup_dir / backup_filename

        export_data = {
            "backup_timestamp": datetime.utcnow().isoformat(),
            "export_version": "1.0",
            "tables": {}
        }

        # Xuất thiết bị
        devices_data = await self._export_table_data(session, Device, "devices")
        export_data["tables"]["devices"] = devices_data

        # Xuất phiên
        sessions_data = await self._export_table_data(session, Session, "sessions")
        export_data["tables"]["sessions"] = sessions_data

        # Xuất dữ liệu CSI gần đây (7 ngày gần nhất)
        recent_date = datetime.utcnow() - timedelta(days=7)
        csi_query = select(CSIData).where(CSIData.created_at >= recent_date)
        csi_data = await self._export_query_data(session, csi_query, "csi_data")
        export_data["tables"]["csi_data_recent"] = csi_data

        # Xuất phát hiện tư thế gần đây (7 ngày gần nhất)
        pose_query = select(PoseDetection).where(PoseDetection.created_at >= recent_date)
        pose_data = await self._export_query_data(session, pose_query, "pose_detections")
        export_data["tables"]["pose_detections_recent"] = pose_data

        # Ghi JSON nén
        with gzip.open(backup_path, 'wt', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str)

        backup_size_mb = self._get_file_size_mb(backup_path)

        # Dọn dẹp bản sao lưu cũ
        self._cleanup_old_backups("data_export_*.json.gz", self.retention_days)

        total_records = sum(
            table_data["record_count"]
            for table_data in export_data["tables"].values()
        )

        return {
            "backup_file": backup_filename,
            "backup_path": str(backup_path),
            "backup_size_mb": backup_size_mb,
            "total_records": total_records,
            "tables_exported": list(export_data["tables"].keys()),
            "retention_days": self.retention_days,
        }

    async def _export_table_data(self, session: AsyncSession, model_class, table_name: str) -> Dict[str, Any]:
        """Xuất tất cả dữ liệu từ một bảng."""
        query = select(model_class)
        return await self._export_query_data(session, query, table_name)

    async def _export_query_data(self, session: AsyncSession, query, table_name: str) -> Dict[str, Any]:
        """Xuất dữ liệu từ một truy vấn."""
        result = await session.execute(query)
        records = result.scalars().all()

        exported_records = []
        for record in records:
            if hasattr(record, 'to_dict'):
                exported_records.append(record.to_dict())
            else:
                # Dự phòng cho bản ghi không có phương thức to_dict
                record_dict = {}
                for column in record.__table__.columns:
                    value = getattr(record, column.name)
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    record_dict[column.name] = value
                exported_records.append(record_dict)

        return {
            "table_name": table_name,
            "record_count": len(exported_records),
            "export_timestamp": datetime.utcnow().isoformat(),
            "records": exported_records,
        }


class LogsBackup(BackupTask):
    """Sao lưu nhật ký ứng dụng."""

    def __init__(self, settings: Settings):
        super().__init__("logs_backup", settings)
        self.retention_days = settings.logs_backup_retention_days
        self.logs_directory = Path(settings.log_directory)

    async def execute_backup(self, session: AsyncSession) -> Dict[str, Any]:
        """Thực thi sao lưu nhật ký."""
        if not self.logs_directory.exists():
            return {
                "backup_file": None,
                "backup_path": None,
                "backup_size_mb": 0,
                "message": "Thư mục nhật ký không tồn tại",
            }

        backup_filename = self._get_backup_filename("logs", ".tar.gz")
        backup_path = self.backup_dir / backup_filename

        # Tạo kho lưu trữ tar.gz của nhật ký
        tar_cmd = [
            "tar", "-czf", str(backup_path),
            "-C", str(self.logs_directory.parent),
            self.logs_directory.name
        ]

        process = await asyncio.create_subprocess_exec(
            *tar_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Lỗi tar không xác định"
            raise Exception(f"tar thất bại: {error_msg}")

        backup_size_mb = self._get_file_size_mb(backup_path)

        # Đếm file nhật ký
        log_files = list(self.logs_directory.glob("*.log*"))

        # Dọn dẹp bản sao lưu cũ
        self._cleanup_old_backups("logs_*.tar.gz", self.retention_days)

        return {
            "backup_file": backup_filename,
            "backup_path": str(backup_path),
            "backup_size_mb": backup_size_mb,
            "log_files_count": len(log_files),
            "retention_days": self.retention_days,
        }


class BackupManager:
    """Trình quản lý cho tất cả tác vụ sao lưu."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_manager = get_database_manager(settings)
        self.tasks = self._initialize_tasks()
        self.running = False
        self.last_run = None
        self.run_count = 0
        self.total_backup_size = 0

    def _initialize_tasks(self) -> List[BackupTask]:
        """Khởi tạo tất cả tác vụ sao lưu."""
        tasks = [
            DatabaseBackup(self.settings),
            ConfigurationBackup(self.settings),
            DataExportBackup(self.settings),
            LogsBackup(self.settings),
        ]

        # Lọc tác vụ được bật
        enabled_tasks = [task for task in tasks if task.enabled]

        logger.info(f"Đã khởi tạo {len(enabled_tasks)} tác vụ sao lưu")
        return enabled_tasks

    async def run_all_tasks(self) -> Dict[str, Any]:
        """Chạy tất cả tác vụ sao lưu."""
        if self.running:
            return {"status": "already_running", "message": "Sao lưu đang tiến hành"}

        self.running = True
        start_time = datetime.utcnow()

        try:
            logger.info("Đang bắt đầu các tác vụ sao lưu")

            results = []
            total_backup_size = 0

            async with self.db_manager.get_async_session() as session:
                for task in self.tasks:
                    if not task.enabled:
                        continue

                    result = await task.run(session)
                    results.append(result)
                    total_backup_size += result.get("backup_size_mb", 0)

            self.last_run = start_time
            self.run_count += 1
            self.total_backup_size += total_backup_size

            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                f"Tác vụ sao lưu hoàn tất: đã tạo {total_backup_size:.2f} MB "
                f"trong {duration:.2f} giây"
            )

            return {
                "status": "completed",
                "start_time": start_time.isoformat(),
                "duration_seconds": duration,
                "total_backup_size_mb": total_backup_size,
                "task_results": results,
            }

        except Exception as e:
            logger.error(f"Tác vụ sao lưu thất bại: {e}", exc_info=True)
            return {
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
                "error": str(e),
                "total_backup_size_mb": 0,
            }

        finally:
            self.running = False

    async def run_task(self, task_name: str) -> Dict[str, Any]:
        """Chạy tác vụ sao lưu cụ thể."""
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
                "error": f"Tác vụ '{task_name}' bị vô hiệu hóa"
            }

        async with self.db_manager.get_async_session() as session:
            return await task.run(session)

    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê trình quản lý sao lưu."""
        return {
            "manager": {
                "running": self.running,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "run_count": self.run_count,
                "total_backup_size_mb": self.total_backup_size,
            },
            "tasks": [task.get_stats() for task in self.tasks],
        }

    def list_backups(self) -> Dict[str, List[Dict[str, Any]]]:
        """Liệt kê tất cả file sao lưu."""
        backup_files = {}

        for task in self.tasks:
            task_backups = []

            # Định nghĩa mẫu cho mỗi loại tác vụ
            patterns = {
                "database_backup": "database_full_*.sql.gz",
                "configuration_backup": "configuration_*.tar.gz",
                "data_export_backup": "data_export_*.json.gz",
                "logs_backup": "logs_*.tar.gz",
            }

            pattern = patterns.get(task.name, f"{task.name}_*")

            for backup_file in task.backup_dir.glob(pattern):
                stat = backup_file.stat()
                task_backups.append({
                    "filename": backup_file.name,
                    "path": str(backup_file),
                    "size_mb": stat.st_size / (1024 * 1024),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

            # Sắp xếp theo thời gian tạo (mới nhất trước)
            task_backups.sort(key=lambda x: x["created_at"], reverse=True)
            backup_files[task.name] = task_backups

        return backup_files


# Thể hiện trình quản lý sao lưu toàn cục
_backup_manager: Optional[BackupManager] = None


def get_backup_manager(settings: Settings) -> BackupManager:
    """Lấy thể hiện trình quản lý sao lưu."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager(settings)
    return _backup_manager


async def run_periodic_backup(settings: Settings):
    """Chạy tác vụ sao lưu định kỳ."""
    backup_manager = get_backup_manager(settings)

    while True:
        try:
            await backup_manager.run_all_tasks()

            # Chờ đến khoảng thời gian sao lưu tiếp theo
            await asyncio.sleep(settings.backup_interval_seconds)

        except asyncio.CancelledError:
            logger.info("Sao lưu định kỳ đã bị hủy")
            break
        except Exception as e:
            logger.error(f"Lỗi sao lưu định kỳ: {e}", exc_info=True)
            # Chờ trước khi thử lại
            await asyncio.sleep(300)  # 5 phút
