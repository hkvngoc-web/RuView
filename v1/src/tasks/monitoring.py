"""
Tác vụ giám sát cho WiFi-DensePose API
"""

import asyncio
import logging
import psutil
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import Settings
from src.database.connection import get_database_manager
from src.database.models import SystemMetric, Device, Session, CSIData, PoseDetection
from src.logger import get_logger

logger = get_logger(__name__)


class MonitoringTask:
    """Lớp cơ sở cho các tác vụ giám sát."""

    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.settings = settings
        self.enabled = True
        self.last_run = None
        self.run_count = 0
        self.error_count = 0
        self.interval_seconds = 60  # Khoảng mặc định

    async def collect_metrics(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Thu thập số liệu cho tác vụ này."""
        raise NotImplementedError

    async def run(self, session: AsyncSession) -> Dict[str, Any]:
        """Chạy tác vụ giám sát với xử lý lỗi."""
        start_time = datetime.utcnow()

        try:
            logger.debug(f"Đang bắt đầu tác vụ giám sát: {self.name}")

            metrics = await self.collect_metrics(session)

            # Lưu số liệu vào cơ sở dữ liệu
            for metric_data in metrics:
                metric = SystemMetric(
                    metric_name=metric_data["name"],
                    metric_type=metric_data["type"],
                    value=metric_data["value"],
                    unit=metric_data.get("unit"),
                    labels=metric_data.get("labels"),
                    tags=metric_data.get("tags"),
                    source=metric_data.get("source", self.name),
                    component=metric_data.get("component"),
                    description=metric_data.get("description"),
                    meta_data=metric_data.get("metadata"),
                )
                session.add(metric)

            await session.commit()

            self.last_run = start_time
            self.run_count += 1

            logger.debug(f"Tác vụ giám sát {self.name} hoàn tất: đã thu thập {len(metrics)} số liệu")

            return {
                "task": self.name,
                "status": "success",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                "metrics_collected": len(metrics),
            }

        except Exception as e:
            self.error_count += 1
            logger.error(f"Tác vụ giám sát {self.name} thất bại: {e}", exc_info=True)

            return {
                "task": self.name,
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
                "error": str(e),
                "metrics_collected": 0,
            }

    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê tác vụ."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
        }


class SystemResourceMonitoring(MonitoringTask):
    """Giám sát tài nguyên hệ thống (CPU, bộ nhớ, ổ đĩa, mạng)."""

    def __init__(self, settings: Settings):
        super().__init__("system_resources", settings)
        self.interval_seconds = settings.system_monitoring_interval

    async def collect_metrics(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Thu thập số liệu tài nguyên hệ thống."""
        metrics = []
        timestamp = datetime.utcnow()

        # Số liệu CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()

        metrics.extend([
            {
                "name": "system_cpu_usage_percent",
                "type": "gauge",
                "value": cpu_percent,
                "unit": "percent",
                "component": "cpu",
                "description": "Phần trăm sử dụng CPU",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_cpu_count",
                "type": "gauge",
                "value": cpu_count,
                "unit": "count",
                "component": "cpu",
                "description": "Số lõi CPU",
                "metadata": {"timestamp": timestamp.isoformat()}
            }
        ])

        if cpu_freq:
            metrics.append({
                "name": "system_cpu_frequency_mhz",
                "type": "gauge",
                "value": cpu_freq.current,
                "unit": "mhz",
                "component": "cpu",
                "description": "Tần số CPU hiện tại",
                "metadata": {"timestamp": timestamp.isoformat()}
            })

        # Số liệu bộ nhớ
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        metrics.extend([
            {
                "name": "system_memory_total_bytes",
                "type": "gauge",
                "value": memory.total,
                "unit": "bytes",
                "component": "memory",
                "description": "Tổng bộ nhớ hệ thống",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_memory_used_bytes",
                "type": "gauge",
                "value": memory.used,
                "unit": "bytes",
                "component": "memory",
                "description": "Bộ nhớ hệ thống đã sử dụng",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_memory_available_bytes",
                "type": "gauge",
                "value": memory.available,
                "unit": "bytes",
                "component": "memory",
                "description": "Bộ nhớ hệ thống khả dụng",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_memory_usage_percent",
                "type": "gauge",
                "value": memory.percent,
                "unit": "percent",
                "component": "memory",
                "description": "Phần trăm sử dụng bộ nhớ",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_swap_total_bytes",
                "type": "gauge",
                "value": swap.total,
                "unit": "bytes",
                "component": "memory",
                "description": "Tổng bộ nhớ swap",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_swap_used_bytes",
                "type": "gauge",
                "value": swap.used,
                "unit": "bytes",
                "component": "memory",
                "description": "Bộ nhớ swap đã sử dụng",
                "metadata": {"timestamp": timestamp.isoformat()}
            }
        ])

        # Số liệu ổ đĩa
        disk_usage = psutil.disk_usage('/')
        disk_io = psutil.disk_io_counters()

        metrics.extend([
            {
                "name": "system_disk_total_bytes",
                "type": "gauge",
                "value": disk_usage.total,
                "unit": "bytes",
                "component": "disk",
                "description": "Tổng dung lượng ổ đĩa",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_disk_used_bytes",
                "type": "gauge",
                "value": disk_usage.used,
                "unit": "bytes",
                "component": "disk",
                "description": "Dung lượng ổ đĩa đã sử dụng",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_disk_free_bytes",
                "type": "gauge",
                "value": disk_usage.free,
                "unit": "bytes",
                "component": "disk",
                "description": "Dung lượng ổ đĩa trống",
                "metadata": {"timestamp": timestamp.isoformat()}
            },
            {
                "name": "system_disk_usage_percent",
                "type": "gauge",
                "value": (disk_usage.used / disk_usage.total) * 100,
                "unit": "percent",
                "component": "disk",
                "description": "Phần trăm sử dụng ổ đĩa",
                "metadata": {"timestamp": timestamp.isoformat()}
            }
        ])

        if disk_io:
            metrics.extend([
                {
                    "name": "system_disk_read_bytes_total",
                    "type": "counter",
                    "value": disk_io.read_bytes,
                    "unit": "bytes",
                    "component": "disk",
                    "description": "Tổng byte đã đọc từ ổ đĩa",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "system_disk_write_bytes_total",
                    "type": "counter",
                    "value": disk_io.write_bytes,
                    "unit": "bytes",
                    "component": "disk",
                    "description": "Tổng byte đã ghi vào ổ đĩa",
                    "metadata": {"timestamp": timestamp.isoformat()}
                }
            ])

        # Số liệu mạng
        network_io = psutil.net_io_counters()

        if network_io:
            metrics.extend([
                {
                    "name": "system_network_bytes_sent_total",
                    "type": "counter",
                    "value": network_io.bytes_sent,
                    "unit": "bytes",
                    "component": "network",
                    "description": "Tổng byte đã gửi qua mạng",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "system_network_bytes_recv_total",
                    "type": "counter",
                    "value": network_io.bytes_recv,
                    "unit": "bytes",
                    "component": "network",
                    "description": "Tổng byte đã nhận qua mạng",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "system_network_packets_sent_total",
                    "type": "counter",
                    "value": network_io.packets_sent,
                    "unit": "count",
                    "component": "network",
                    "description": "Tổng gói đã gửi qua mạng",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "system_network_packets_recv_total",
                    "type": "counter",
                    "value": network_io.packets_recv,
                    "unit": "count",
                    "component": "network",
                    "description": "Tổng gói đã nhận qua mạng",
                    "metadata": {"timestamp": timestamp.isoformat()}
                }
            ])

        return metrics


class DatabaseMonitoring(MonitoringTask):
    """Giám sát hiệu suất và thống kê cơ sở dữ liệu."""

    def __init__(self, settings: Settings):
        super().__init__("database", settings)
        self.interval_seconds = settings.database_monitoring_interval

    async def collect_metrics(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Thu thập số liệu cơ sở dữ liệu."""
        metrics = []
        timestamp = datetime.utcnow()

        # Lấy thống kê kết nối cơ sở dữ liệu
        db_manager = get_database_manager(self.settings)
        connection_stats = await db_manager.get_connection_stats()

        # Số liệu kết nối PostgreSQL
        if "postgresql" in connection_stats:
            pg_stats = connection_stats["postgresql"]
            metrics.extend([
                {
                    "name": "database_connections_total",
                    "type": "gauge",
                    "value": pg_stats.get("total_connections", 0),
                    "unit": "count",
                    "component": "postgresql",
                    "description": "Tổng kết nối cơ sở dữ liệu",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "database_connections_active",
                    "type": "gauge",
                    "value": pg_stats.get("checked_out", 0),
                    "unit": "count",
                    "component": "postgresql",
                    "description": "Kết nối cơ sở dữ liệu đang hoạt động",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "database_connections_available",
                    "type": "gauge",
                    "value": pg_stats.get("available_connections", 0),
                    "unit": "count",
                    "component": "postgresql",
                    "description": "Kết nối cơ sở dữ liệu khả dụng",
                    "metadata": {"timestamp": timestamp.isoformat()}
                }
            ])

        # Số liệu kết nối Redis
        if "redis" in connection_stats and not connection_stats["redis"].get("error"):
            redis_stats = connection_stats["redis"]
            metrics.extend([
                {
                    "name": "redis_connections_active",
                    "type": "gauge",
                    "value": redis_stats.get("connected_clients", 0),
                    "unit": "count",
                    "component": "redis",
                    "description": "Kết nối Redis đang hoạt động",
                    "metadata": {"timestamp": timestamp.isoformat()}
                },
                {
                    "name": "redis_connections_blocked",
                    "type": "gauge",
                    "value": redis_stats.get("blocked_clients", 0),
                    "unit": "count",
                    "component": "redis",
                    "description": "Kết nối Redis bị chặn",
                    "metadata": {"timestamp": timestamp.isoformat()}
                }
            ])

        # Số hàng các bảng
        table_counts = await self._get_table_counts(session)
        for table_name, count in table_counts.items():
            metrics.append({
                "name": f"database_table_rows_{table_name}",
                "type": "gauge",
                "value": count,
                "unit": "count",
                "component": "postgresql",
                "description": f"Số hàng trong bảng {table_name}",
                "metadata": {"timestamp": timestamp.isoformat(), "table": table_name}
            })

        return metrics

    async def _get_table_counts(self, session: AsyncSession) -> Dict[str, int]:
        """Lấy số hàng cho tất cả các bảng."""
        counts = {}

        # Đếm thiết bị
        result = await session.execute(select(func.count(Device.id)))
        counts["devices"] = result.scalar() or 0

        # Đếm phiên
        result = await session.execute(select(func.count(Session.id)))
        counts["sessions"] = result.scalar() or 0

        # Đếm dữ liệu CSI
        result = await session.execute(select(func.count(CSIData.id)))
        counts["csi_data"] = result.scalar() or 0

        # Đếm phát hiện tư thế
        result = await session.execute(select(func.count(PoseDetection.id)))
        counts["pose_detections"] = result.scalar() or 0

        # Đếm số liệu hệ thống
        result = await session.execute(select(func.count(SystemMetric.id)))
        counts["system_metrics"] = result.scalar() or 0

        return counts


class ApplicationMonitoring(MonitoringTask):
    """Giám sát số liệu cụ thể của ứng dụng."""

    def __init__(self, settings: Settings):
        super().__init__("application", settings)
        self.interval_seconds = settings.application_monitoring_interval
        self.start_time = datetime.utcnow()

    async def collect_metrics(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Thu thập số liệu ứng dụng."""
        metrics = []
        timestamp = datetime.utcnow()

        # Thời gian hoạt động ứng dụng
        uptime_seconds = (timestamp - self.start_time).total_seconds()
        metrics.append({
            "name": "application_uptime_seconds",
            "type": "gauge",
            "value": uptime_seconds,
            "unit": "seconds",
            "component": "application",
            "description": "Thời gian hoạt động ứng dụng tính bằng giây",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Số phiên đang hoạt động
        active_sessions_query = select(func.count(Session.id)).where(
            Session.status == "active"
        )
        result = await session.execute(active_sessions_query)
        active_sessions = result.scalar() or 0

        metrics.append({
            "name": "application_active_sessions",
            "type": "gauge",
            "value": active_sessions,
            "unit": "count",
            "component": "application",
            "description": "Số phiên đang hoạt động",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Số thiết bị đang hoạt động
        active_devices_query = select(func.count(Device.id)).where(
            Device.status == "active"
        )
        result = await session.execute(active_devices_query)
        active_devices = result.scalar() or 0

        metrics.append({
            "name": "application_active_devices",
            "type": "gauge",
            "value": active_devices,
            "unit": "count",
            "component": "application",
            "description": "Số thiết bị đang hoạt động",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Số liệu xử lý dữ liệu gần đây (1 giờ qua)
        one_hour_ago = timestamp - timedelta(hours=1)

        # Số dữ liệu CSI gần đây
        recent_csi_query = select(func.count(CSIData.id)).where(
            CSIData.created_at >= one_hour_ago
        )
        result = await session.execute(recent_csi_query)
        recent_csi_count = result.scalar() or 0

        metrics.append({
            "name": "application_csi_data_hourly",
            "type": "gauge",
            "value": recent_csi_count,
            "unit": "count",
            "component": "application",
            "description": "Bản ghi dữ liệu CSI tạo trong giờ qua",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Số phát hiện tư thế gần đây
        recent_pose_query = select(func.count(PoseDetection.id)).where(
            PoseDetection.created_at >= one_hour_ago
        )
        result = await session.execute(recent_pose_query)
        recent_pose_count = result.scalar() or 0

        metrics.append({
            "name": "application_pose_detections_hourly",
            "type": "gauge",
            "value": recent_pose_count,
            "unit": "count",
            "component": "application",
            "description": "Phát hiện tư thế tạo trong giờ qua",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Số liệu trạng thái xử lý
        processing_statuses = ["pending", "processing", "completed", "failed"]
        for status in processing_statuses:
            status_query = select(func.count(CSIData.id)).where(
                CSIData.processing_status == status
            )
            result = await session.execute(status_query)
            status_count = result.scalar() or 0

            metrics.append({
                "name": f"application_csi_processing_{status}",
                "type": "gauge",
                "value": status_count,
                "unit": "count",
                "component": "application",
                "description": f"Bản ghi dữ liệu CSI có trạng thái xử lý {status}",
                "metadata": {"timestamp": timestamp.isoformat(), "status": status}
            })

        return metrics


class PerformanceMonitoring(MonitoringTask):
    """Giám sát số liệu hiệu suất và thời gian phản hồi."""

    def __init__(self, settings: Settings):
        super().__init__("performance", settings)
        self.interval_seconds = settings.performance_monitoring_interval
        self.response_times = []
        self.error_counts = {}

    async def collect_metrics(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Thu thập số liệu hiệu suất."""
        metrics = []
        timestamp = datetime.utcnow()

        # Kiểm tra hiệu suất truy vấn cơ sở dữ liệu
        start_time = time.time()
        test_query = select(func.count(Device.id))
        await session.execute(test_query)
        db_response_time = (time.time() - start_time) * 1000  # Chuyển sang mili giây

        metrics.append({
            "name": "performance_database_query_time_ms",
            "type": "gauge",
            "value": db_response_time,
            "unit": "milliseconds",
            "component": "database",
            "description": "Thời gian phản hồi truy vấn cơ sở dữ liệu",
            "metadata": {"timestamp": timestamp.isoformat()}
        })

        # Thời gian phản hồi trung bình (nếu có dữ liệu)
        if self.response_times:
            avg_response_time = sum(self.response_times) / len(self.response_times)
            metrics.append({
                "name": "performance_avg_response_time_ms",
                "type": "gauge",
                "value": avg_response_time,
                "unit": "milliseconds",
                "component": "api",
                "description": "Thời gian phản hồi API trung bình",
                "metadata": {"timestamp": timestamp.isoformat()}
            })

            # Xóa thời gian phản hồi cũ (chỉ giữ gần đây)
            self.response_times = self.response_times[-100:]  # Giữ 100 gần nhất

        # Tỷ lệ lỗi
        for error_type, count in self.error_counts.items():
            metrics.append({
                "name": f"performance_errors_{error_type}_total",
                "type": "counter",
                "value": count,
                "unit": "count",
                "component": "api",
                "description": f"Tổng lỗi {error_type}",
                "metadata": {"timestamp": timestamp.isoformat(), "error_type": error_type}
            })

        return metrics

    def record_response_time(self, response_time_ms: float):
        """Ghi nhận thời gian phản hồi API."""
        self.response_times.append(response_time_ms)

    def record_error(self, error_type: str):
        """Ghi nhận một sự kiện lỗi."""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1


class MonitoringManager:
    """Trình quản lý tất cả tác vụ giám sát."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_manager = get_database_manager(settings)
        self.tasks = self._initialize_tasks()
        self.running = False
        self.last_run = None
        self.run_count = 0

    def _initialize_tasks(self) -> List[MonitoringTask]:
        """Khởi tạo tất cả tác vụ giám sát."""
        tasks = [
            SystemResourceMonitoring(self.settings),
            DatabaseMonitoring(self.settings),
            ApplicationMonitoring(self.settings),
            PerformanceMonitoring(self.settings),
        ]

        # Lọc tác vụ đã bật
        enabled_tasks = [task for task in tasks if task.enabled]

        logger.info(f"Đã khởi tạo {len(enabled_tasks)} tác vụ giám sát")
        return enabled_tasks

    async def run_all_tasks(self) -> Dict[str, Any]:
        """Chạy tất cả tác vụ giám sát."""
        if self.running:
            return {"status": "already_running", "message": "Giám sát đang tiến hành"}

        self.running = True
        start_time = datetime.utcnow()

        try:
            logger.debug("Đang bắt đầu các tác vụ giám sát")

            results = []
            total_metrics = 0

            async with self.db_manager.get_async_session() as session:
                for task in self.tasks:
                    if not task.enabled:
                        continue

                    result = await task.run(session)
                    results.append(result)
                    total_metrics += result.get("metrics_collected", 0)

            self.last_run = start_time
            self.run_count += 1

            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.debug(
                f"Các tác vụ giám sát hoàn tất: đã thu thập {total_metrics} số liệu "
                f"trong {duration:.2f} giây"
            )

            return {
                "status": "completed",
                "start_time": start_time.isoformat(),
                "duration_seconds": duration,
                "total_metrics": total_metrics,
                "task_results": results,
            }

        except Exception as e:
            logger.error(f"Các tác vụ giám sát thất bại: {e}", exc_info=True)
            return {
                "status": "error",
                "start_time": start_time.isoformat(),
                "duration_seconds": (datetime.utcnow() - start_time).total_seconds(),
                "error": str(e),
                "total_metrics": 0,
            }

        finally:
            self.running = False

    async def run_task(self, task_name: str) -> Dict[str, Any]:
        """Chạy một tác vụ giám sát cụ thể."""
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
        """Lấy thống kê trình quản lý giám sát."""
        return {
            "manager": {
                "running": self.running,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "run_count": self.run_count,
            },
            "tasks": [task.get_stats() for task in self.tasks],
        }

    def get_performance_task(self) -> Optional[PerformanceMonitoring]:
        """Lấy tác vụ giám sát hiệu suất để ghi số liệu."""
        return next((t for t in self.tasks if isinstance(t, PerformanceMonitoring)), None)


# Thể hiện trình quản lý giám sát toàn cục
_monitoring_manager: Optional[MonitoringManager] = None


def get_monitoring_manager(settings: Settings) -> MonitoringManager:
    """Lấy thể hiện trình quản lý giám sát."""
    global _monitoring_manager
    if _monitoring_manager is None:
        _monitoring_manager = MonitoringManager(settings)
    return _monitoring_manager


async def run_periodic_monitoring(settings: Settings):
    """Chạy tác vụ giám sát định kỳ."""
    monitoring_manager = get_monitoring_manager(settings)

    while True:
        try:
            await monitoring_manager.run_all_tasks()

            # Chờ đến khoảng giám sát tiếp theo
            await asyncio.sleep(settings.monitoring_interval_seconds)

        except asyncio.CancelledError:
            logger.info("Giám sát định kỳ đã bị hủy")
            break
        except Exception as e:
            logger.error(f"Lỗi giám sát định kỳ: {e}", exc_info=True)
            # Chờ trước khi thử lại
            await asyncio.sleep(30)
