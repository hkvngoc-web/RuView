"""
Dịch vụ thu thập số liệu cho WiFi-DensePose API
"""

import asyncio
import logging
import time
import psutil
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque

from src.config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Điểm dữ liệu số liệu đơn lẻ."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSeries:
    """Chuỗi thời gian của các điểm số liệu."""
    name: str
    description: str
    unit: str
    points: deque = field(default_factory=lambda: deque(maxlen=1000))

    def add_point(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Thêm một điểm số liệu."""
        point = MetricPoint(
            timestamp=datetime.utcnow(),
            value=value,
            labels=labels or {}
        )
        self.points.append(point)

    def get_latest(self) -> Optional[MetricPoint]:
        """Lấy điểm số liệu mới nhất."""
        return self.points[-1] if self.points else None

    def get_average(self, duration: timedelta) -> Optional[float]:
        """Lấy giá trị trung bình trong khoảng thời gian."""
        cutoff = datetime.utcnow() - duration
        relevant_points = [
            point for point in self.points
            if point.timestamp >= cutoff
        ]

        if not relevant_points:
            return None

        return sum(point.value for point in relevant_points) / len(relevant_points)

    def get_max(self, duration: timedelta) -> Optional[float]:
        """Lấy giá trị lớn nhất trong khoảng thời gian."""
        cutoff = datetime.utcnow() - duration
        relevant_points = [
            point for point in self.points
            if point.timestamp >= cutoff
        ]

        if not relevant_points:
            return None

        return max(point.value for point in relevant_points)


class MetricsService:
    """Dịch vụ thu thập và quản lý số liệu ứng dụng."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._metrics: Dict[str, MetricSeries] = {}
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._start_time = time.time()
        self._initialized = False
        self._running = False

        # Khởi tạo các số liệu tiêu chuẩn
        self._initialize_standard_metrics()

    def _initialize_standard_metrics(self):
        """Khởi tạo các số liệu hệ thống và ứng dụng tiêu chuẩn."""
        self._metrics.update({
            # Số liệu hệ thống
            "system_cpu_usage": MetricSeries(
                "system_cpu_usage", "Phần trăm sử dụng CPU hệ thống", "phần trăm"
            ),
            "system_memory_usage": MetricSeries(
                "system_memory_usage", "Phần trăm sử dụng bộ nhớ hệ thống", "phần trăm"
            ),
            "system_disk_usage": MetricSeries(
                "system_disk_usage", "Phần trăm sử dụng đĩa hệ thống", "phần trăm"
            ),
            "system_network_bytes_sent": MetricSeries(
                "system_network_bytes_sent", "Số byte mạng đã gửi", "byte"
            ),
            "system_network_bytes_recv": MetricSeries(
                "system_network_bytes_recv", "Số byte mạng đã nhận", "byte"
            ),

            # Số liệu ứng dụng
            "app_requests_total": MetricSeries(
                "app_requests_total", "Tổng số yêu cầu HTTP", "đếm"
            ),
            "app_request_duration": MetricSeries(
                "app_request_duration", "Thời gian xử lý yêu cầu HTTP", "giây"
            ),
            "app_active_connections": MetricSeries(
                "app_active_connections", "Kết nối WebSocket đang hoạt động", "đếm"
            ),
            "app_pose_detections": MetricSeries(
                "app_pose_detections", "Số lần phát hiện tư thế đã thực hiện", "đếm"
            ),
            "app_pose_processing_time": MetricSeries(
                "app_pose_processing_time", "Thời gian xử lý tư thế", "giây"
            ),
            "app_csi_data_points": MetricSeries(
                "app_csi_data_points", "Số điểm dữ liệu CSI đã xử lý", "đếm"
            ),
            "app_stream_fps": MetricSeries(
                "app_stream_fps", "Số khung hình truyền phát mỗi giây", "fps"
            ),

            # Số liệu lỗi
            "app_errors_total": MetricSeries(
                "app_errors_total", "Tổng số lỗi ứng dụng", "đếm"
            ),
            "app_http_errors": MetricSeries(
                "app_http_errors", "Số lỗi HTTP", "đếm"
            ),
        })

    async def initialize(self):
        """Khởi tạo dịch vụ số liệu."""
        if self._initialized:
            return

        logger.info("Đang khởi tạo dịch vụ số liệu")
        self._initialized = True
        logger.info("Dịch vụ số liệu đã khởi tạo")

    async def start(self):
        """Khởi động dịch vụ số liệu."""
        if not self._initialized:
            await self.initialize()

        self._running = True
        logger.info("Dịch vụ số liệu đã khởi động")

    async def shutdown(self):
        """Tắt dịch vụ số liệu."""
        self._running = False
        logger.info("Dịch vụ số liệu đã tắt")

    async def collect_metrics(self):
        """Thu thập tất cả số liệu."""
        if not self._running:
            return

        logger.debug("Đang thu thập số liệu")

        # Thu thập số liệu hệ thống
        await self._collect_system_metrics()

        # Thu thập số liệu ứng dụng
        await self._collect_application_metrics()

        logger.debug("Thu thập số liệu hoàn tất")

    async def _collect_system_metrics(self):
        """Thu thập số liệu cấp hệ thống."""
        try:
            # Sử dụng CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            self._metrics["system_cpu_usage"].add_point(cpu_percent)

            # Sử dụng bộ nhớ
            memory = psutil.virtual_memory()
            self._metrics["system_memory_usage"].add_point(memory.percent)

            # Sử dụng đĩa
            disk = psutil.disk_usage('/')
            disk_percent = (disk.used / disk.total) * 100
            self._metrics["system_disk_usage"].add_point(disk_percent)

            # I/O mạng
            network = psutil.net_io_counters()
            self._metrics["system_network_bytes_sent"].add_point(network.bytes_sent)
            self._metrics["system_network_bytes_recv"].add_point(network.bytes_recv)

        except Exception as e:
            logger.error(f"Lỗi khi thu thập số liệu hệ thống: {e}")

    async def _collect_application_metrics(self):
        """Thu thập số liệu cụ thể của ứng dụng."""
        try:
            # Import tại đây để tránh import vòng
            from src.api.websocket.connection_manager import connection_manager

            # Kết nối đang hoạt động
            connection_stats = await connection_manager.get_connection_stats()
            active_connections = connection_stats.get("active_connections", 0)
            self._metrics["app_active_connections"].add_point(active_connections)

            # Cập nhật bộ đếm thành số liệu
            for name, value in self._counters.items():
                if name in self._metrics:
                    self._metrics[name].add_point(value)

            # Cập nhật gauge thành số liệu
            for name, value in self._gauges.items():
                if name in self._metrics:
                    self._metrics[name].add_point(value)

        except Exception as e:
            logger.error(f"Lỗi khi thu thập số liệu ứng dụng: {e}")

    def increment_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Tăng số liệu bộ đếm."""
        self._counters[name] += value

        if name in self._metrics:
            self._metrics[name].add_point(self._counters[name], labels)

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Đặt giá trị số liệu gauge."""
        self._gauges[name] = value

        if name in self._metrics:
            self._metrics[name].add_point(value, labels)

    def record_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Ghi nhận giá trị histogram."""
        self._histograms[name].append(value)

        # Chỉ giữ 1000 giá trị gần nhất
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-1000:]

        if name in self._metrics:
            self._metrics[name].add_point(value, labels)

    def time_function(self, metric_name: str):
        """Decorator để đo thời gian thực thi hàm."""
        def decorator(func):
            import functools

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start_time
                    self.record_histogram(metric_name, duration)

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start_time
                    self.record_histogram(metric_name, duration)

            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

        return decorator

    def get_metric(self, name: str) -> Optional[MetricSeries]:
        """Lấy chuỗi số liệu theo tên."""
        return self._metrics.get(name)

    def get_metric_value(self, name: str) -> Optional[float]:
        """Lấy giá trị mới nhất của số liệu."""
        metric = self._metrics.get(name)
        if metric:
            latest = metric.get_latest()
            return latest.value if latest else None
        return None

    def get_counter_value(self, name: str) -> float:
        """Lấy giá trị bộ đếm hiện tại."""
        return self._counters.get(name, 0.0)

    def get_gauge_value(self, name: str) -> Optional[float]:
        """Lấy giá trị gauge hiện tại."""
        return self._gauges.get(name)

    def get_histogram_stats(self, name: str) -> Dict[str, float]:
        """Lấy thống kê histogram."""
        values = self._histograms.get(name, [])
        if not values:
            return {}

        sorted_values = sorted(values)
        count = len(sorted_values)

        return {
            "count": count,
            "sum": sum(sorted_values),
            "min": sorted_values[0],
            "max": sorted_values[-1],
            "mean": sum(sorted_values) / count,
            "p50": sorted_values[int(count * 0.5)],
            "p90": sorted_values[int(count * 0.9)],
            "p95": sorted_values[int(count * 0.95)],
            "p99": sorted_values[int(count * 0.99)],
        }

    async def get_all_metrics(self) -> Dict[str, Any]:
        """Lấy tất cả số liệu hiện tại."""
        metrics = {}

        # Giá trị số liệu hiện tại
        for name, metric_series in self._metrics.items():
            latest = metric_series.get_latest()
            if latest:
                metrics[name] = {
                    "value": latest.value,
                    "timestamp": latest.timestamp.isoformat(),
                    "description": metric_series.description,
                    "unit": metric_series.unit,
                    "labels": latest.labels
                }

        # Giá trị bộ đếm
        metrics.update({
            f"counter_{name}": value
            for name, value in self._counters.items()
        })

        # Giá trị gauge
        metrics.update({
            f"gauge_{name}": value
            for name, value in self._gauges.items()
        })

        # Thống kê histogram
        for name, values in self._histograms.items():
            if values:
                stats = self.get_histogram_stats(name)
                metrics[f"histogram_{name}"] = stats

        return metrics

    async def get_system_metrics(self) -> Dict[str, Any]:
        """Lấy tóm tắt số liệu hệ thống."""
        return {
            "cpu_usage": self.get_metric_value("system_cpu_usage"),
            "memory_usage": self.get_metric_value("system_memory_usage"),
            "disk_usage": self.get_metric_value("system_disk_usage"),
            "network_bytes_sent": self.get_metric_value("system_network_bytes_sent"),
            "network_bytes_recv": self.get_metric_value("system_network_bytes_recv"),
        }

    async def get_application_metrics(self) -> Dict[str, Any]:
        """Lấy tóm tắt số liệu ứng dụng."""
        return {
            "requests_total": self.get_counter_value("app_requests_total"),
            "active_connections": self.get_metric_value("app_active_connections"),
            "pose_detections": self.get_counter_value("app_pose_detections"),
            "csi_data_points": self.get_counter_value("app_csi_data_points"),
            "errors_total": self.get_counter_value("app_errors_total"),
            "uptime_seconds": time.time() - self._start_time,
            "request_duration_stats": self.get_histogram_stats("app_request_duration"),
            "pose_processing_time_stats": self.get_histogram_stats("app_pose_processing_time"),
        }

    async def get_performance_summary(self) -> Dict[str, Any]:
        """Lấy tóm tắt số liệu hiệu suất."""
        one_hour = timedelta(hours=1)

        return {
            "system": {
                "cpu_avg_1h": self._metrics["system_cpu_usage"].get_average(one_hour),
                "memory_avg_1h": self._metrics["system_memory_usage"].get_average(one_hour),
                "cpu_max_1h": self._metrics["system_cpu_usage"].get_max(one_hour),
                "memory_max_1h": self._metrics["system_memory_usage"].get_max(one_hour),
            },
            "application": {
                "avg_request_duration": self.get_histogram_stats("app_request_duration").get("mean"),
                "avg_pose_processing_time": self.get_histogram_stats("app_pose_processing_time").get("mean"),
                "total_requests": self.get_counter_value("app_requests_total"),
                "total_errors": self.get_counter_value("app_errors_total"),
                "error_rate": (
                    self.get_counter_value("app_errors_total") /
                    max(self.get_counter_value("app_requests_total"), 1)
                ) * 100,
            }
        }

    async def get_status(self) -> Dict[str, Any]:
        """Lấy trạng thái dịch vụ số liệu."""
        return {
            "status": "healthy" if self._running else "stopped",
            "initialized": self._initialized,
            "running": self._running,
            "metrics_count": len(self._metrics),
            "counters_count": len(self._counters),
            "gauges_count": len(self._gauges),
            "histograms_count": len(self._histograms),
            "uptime": time.time() - self._start_time
        }

    def reset_metrics(self):
        """Đặt lại tất cả số liệu."""
        logger.info("Đang đặt lại tất cả số liệu")

        # Xóa các điểm số liệu nhưng giữ định nghĩa chuỗi
        for metric_series in self._metrics.values():
            metric_series.points.clear()

        # Đặt lại bộ đếm, gauge và histogram
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()

        logger.info("Tất cả số liệu đã được đặt lại")
