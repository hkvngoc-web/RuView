"""Mô-đun làm sạch pha cho hệ thống WiFi-DensePose sử dụng phương pháp TDD."""

import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from scipy import signal


class PhaseSanitizationError(Exception):
    """Ngoại lệ phát sinh khi làm sạch pha gặp lỗi."""
    pass


class PhaseSanitizer:
    """Làm sạch dữ liệu pha từ tín hiệu CSI để xử lý đáng tin cậy."""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """Khởi tạo bộ làm sạch pha.

        Args:
            config: Từ điển cấu hình
            logger: Thể hiện logger tùy chọn

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        self._validate_config(config)

        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Tham số xử lý
        self.unwrapping_method = config['unwrapping_method']
        self.outlier_threshold = config['outlier_threshold']
        self.smoothing_window = config['smoothing_window']

        # Tham số tùy chọn với giá trị mặc định
        self.enable_outlier_removal = config.get('enable_outlier_removal', True)
        self.enable_smoothing = config.get('enable_smoothing', True)
        self.enable_noise_filtering = config.get('enable_noise_filtering', False)
        self.noise_threshold = config.get('noise_threshold', 0.05)
        self.phase_range = config.get('phase_range', (-np.pi, np.pi))

        # Theo dõi thống kê
        self._total_processed = 0
        self._outliers_removed = 0
        self._sanitization_errors = 0

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Xác thực tham số cấu hình.

        Args:
            config: Cấu hình cần xác thực

        Raises:
            ValueError: Nếu cấu hình không hợp lệ
        """
        required_fields = ['unwrapping_method', 'outlier_threshold', 'smoothing_window']
        missing_fields = [field for field in required_fields if field not in config]

        if missing_fields:
            raise ValueError(f"Thiếu cấu hình bắt buộc: {missing_fields}")

        # Xác thực phương pháp mở gói pha
        valid_methods = ['numpy', 'scipy', 'custom']
        if config['unwrapping_method'] not in valid_methods:
            raise ValueError(f"Phương pháp mở gói pha không hợp lệ: {config['unwrapping_method']}. Phải là một trong {valid_methods}")

        # Xác thực ngưỡng
        if config['outlier_threshold'] <= 0:
            raise ValueError("outlier_threshold phải là số dương")

        if config['smoothing_window'] <= 0:
            raise ValueError("smoothing_window phải là số dương")

    def unwrap_phase(self, phase_data: np.ndarray) -> np.ndarray:
        """Mở gói dữ liệu pha để loại bỏ sự gián đoạn.

        Args:
            phase_data: Dữ liệu pha đã gói (mảng 2D)

        Returns:
            Dữ liệu pha đã mở gói

        Raises:
            PhaseSanitizationError: Nếu mở gói pha thất bại
        """
        try:
            if self.unwrapping_method == 'numpy':
                return self._unwrap_numpy(phase_data)
            elif self.unwrapping_method == 'scipy':
                return self._unwrap_scipy(phase_data)
            elif self.unwrapping_method == 'custom':
                return self._unwrap_custom(phase_data)
            else:
                raise ValueError(f"Phương pháp mở gói pha không xác định: {self.unwrapping_method}")

        except Exception as e:
            raise PhaseSanitizationError(f"Mở gói pha thất bại: {e}")

    def _unwrap_numpy(self, phase_data: np.ndarray) -> np.ndarray:
        """Mở gói pha sử dụng hàm unwrap của numpy."""
        if phase_data.size == 0:
            raise ValueError("Không thể mở gói dữ liệu pha rỗng")
        return np.unwrap(phase_data, axis=1)

    def _unwrap_scipy(self, phase_data: np.ndarray) -> np.ndarray:
        """Mở gói pha sử dụng hàm unwrap của scipy."""
        if phase_data.size == 0:
            raise ValueError("Không thể mở gói dữ liệu pha rỗng")
        return np.unwrap(phase_data, axis=1)

    def _unwrap_custom(self, phase_data: np.ndarray) -> np.ndarray:
        """Mở gói pha sử dụng thuật toán tùy chỉnh."""
        if phase_data.size == 0:
            raise ValueError("Không thể mở gói dữ liệu pha rỗng")
        # Thuật toán mở gói tùy chỉnh đơn giản
        unwrapped = phase_data.copy()
        for i in range(phase_data.shape[0]):
            unwrapped[i, :] = np.unwrap(phase_data[i, :])
        return unwrapped

    def remove_outliers(self, phase_data: np.ndarray) -> np.ndarray:
        """Loại bỏ ngoại lai khỏi dữ liệu pha.

        Args:
            phase_data: Dữ liệu pha (mảng 2D)

        Returns:
            Dữ liệu pha đã loại bỏ ngoại lai

        Raises:
            PhaseSanitizationError: Nếu loại bỏ ngoại lai thất bại
        """
        if not self.enable_outlier_removal:
            return phase_data

        try:
            # Phát hiện ngoại lai
            outlier_mask = self._detect_outliers(phase_data)

            # Nội suy ngoại lai
            clean_data = self._interpolate_outliers(phase_data, outlier_mask)

            return clean_data

        except Exception as e:
            raise PhaseSanitizationError(f"Loại bỏ ngoại lai thất bại: {e}")

    def _detect_outliers(self, phase_data: np.ndarray) -> np.ndarray:
        """Phát hiện ngoại lai sử dụng phương pháp thống kê."""
        # Sử dụng phương pháp Z-score để phát hiện ngoại lai
        z_scores = np.abs((phase_data - np.mean(phase_data, axis=1, keepdims=True)) /
                         (np.std(phase_data, axis=1, keepdims=True) + 1e-8))
        outlier_mask = z_scores > self.outlier_threshold

        # Cập nhật thống kê
        self._outliers_removed += np.sum(outlier_mask)

        return outlier_mask

    def _interpolate_outliers(self, phase_data: np.ndarray, outlier_mask: np.ndarray) -> np.ndarray:
        """Nội suy các giá trị ngoại lai."""
        clean_data = phase_data.copy()

        for i in range(phase_data.shape[0]):
            outliers = outlier_mask[i, :]
            if np.any(outliers):
                # Nội suy tuyến tính cho ngoại lai
                valid_indices = np.where(~outliers)[0]
                outlier_indices = np.where(outliers)[0]

                if len(valid_indices) > 1:
                    clean_data[i, outlier_indices] = np.interp(
                        outlier_indices, valid_indices, phase_data[i, valid_indices]
                    )

        return clean_data

    def smooth_phase(self, phase_data: np.ndarray) -> np.ndarray:
        """Làm mượt dữ liệu pha để giảm nhiễu.

        Args:
            phase_data: Dữ liệu pha (mảng 2D)

        Returns:
            Dữ liệu pha đã làm mượt

        Raises:
            PhaseSanitizationError: Nếu làm mượt thất bại
        """
        if not self.enable_smoothing:
            return phase_data

        try:
            smoothed_data = self._apply_moving_average(phase_data, self.smoothing_window)
            return smoothed_data

        except Exception as e:
            raise PhaseSanitizationError(f"Làm mượt pha thất bại: {e}")

    def _apply_moving_average(self, phase_data: np.ndarray, window_size: int) -> np.ndarray:
        """Áp dụng làm mượt trung bình trượt."""
        smoothed_data = phase_data.copy()

        # Đảm bảo kích thước cửa sổ là số lẻ
        if window_size % 2 == 0:
            window_size += 1

        half_window = window_size // 2

        for i in range(phase_data.shape[0]):
            for j in range(half_window, phase_data.shape[1] - half_window):
                start_idx = j - half_window
                end_idx = j + half_window + 1
                smoothed_data[i, j] = np.mean(phase_data[i, start_idx:end_idx])

        return smoothed_data

    def filter_noise(self, phase_data: np.ndarray) -> np.ndarray:
        """Lọc nhiễu khỏi dữ liệu pha.

        Args:
            phase_data: Dữ liệu pha (mảng 2D)

        Returns:
            Dữ liệu pha đã lọc

        Raises:
            PhaseSanitizationError: Nếu lọc nhiễu thất bại
        """
        if not self.enable_noise_filtering:
            return phase_data

        try:
            filtered_data = self._apply_low_pass_filter(phase_data, self.noise_threshold)
            return filtered_data

        except Exception as e:
            raise PhaseSanitizationError(f"Lọc nhiễu thất bại: {e}")

    def _apply_low_pass_filter(self, phase_data: np.ndarray, threshold: float) -> np.ndarray:
        """Áp dụng bộ lọc thông thấp để loại bỏ nhiễu tần số cao."""
        filtered_data = phase_data.copy()

        # Kiểm tra xem dữ liệu có đủ lớn cho bộ lọc không
        min_filter_length = 18  # Chiều dài tối thiểu yêu cầu cho filtfilt với bậc 4
        if phase_data.shape[1] < min_filter_length:
            # Bỏ qua lọc cho các mảng nhỏ
            return filtered_data

        # Áp dụng bộ lọc Butterworth thông thấp
        nyquist = 0.5
        cutoff = threshold * nyquist

        # Thiết kế bộ lọc
        b, a = signal.butter(4, cutoff, btype='low')

        # Áp dụng bộ lọc cho từng ăng-ten
        for i in range(phase_data.shape[0]):
            filtered_data[i, :] = signal.filtfilt(b, a, phase_data[i, :])

        return filtered_data

    def sanitize_phase(self, phase_data: np.ndarray) -> np.ndarray:
        """Làm sạch dữ liệu pha qua toàn bộ pipeline.

        Args:
            phase_data: Dữ liệu pha thô (mảng 2D)

        Returns:
            Dữ liệu pha đã làm sạch

        Raises:
            PhaseSanitizationError: Nếu làm sạch thất bại
        """
        try:
            self._total_processed += 1

            # Xác thực dữ liệu đầu vào
            self.validate_phase_data(phase_data)

            # Áp dụng toàn bộ pipeline làm sạch
            sanitized_data = self.unwrap_phase(phase_data)
            sanitized_data = self.remove_outliers(sanitized_data)
            sanitized_data = self.smooth_phase(sanitized_data)
            sanitized_data = self.filter_noise(sanitized_data)

            return sanitized_data

        except PhaseSanitizationError:
            self._sanitization_errors += 1
            raise
        except Exception as e:
            self._sanitization_errors += 1
            raise PhaseSanitizationError(f"Pipeline làm sạch thất bại: {e}")

    def validate_phase_data(self, phase_data: np.ndarray) -> bool:
        """Xác thực định dạng và giá trị dữ liệu pha.

        Args:
            phase_data: Dữ liệu pha cần xác thực

        Returns:
            True nếu hợp lệ

        Raises:
            PhaseSanitizationError: Nếu xác thực thất bại
        """
        # Kiểm tra xem dữ liệu có phải 2D không
        if phase_data.ndim != 2:
            raise PhaseSanitizationError("Dữ liệu pha phải là mảng 2D")

        # Kiểm tra xem dữ liệu có rỗng không
        if phase_data.size == 0:
            raise PhaseSanitizationError("Dữ liệu pha không được rỗng")

        # Kiểm tra xem giá trị có nằm trong phạm vi hợp lệ không
        min_val, max_val = self.phase_range
        if np.any(phase_data < min_val) or np.any(phase_data > max_val):
            raise PhaseSanitizationError(f"Giá trị pha ngoài phạm vi hợp lệ [{min_val}, {max_val}]")

        return True

    def get_sanitization_statistics(self) -> Dict[str, Any]:
        """Lấy thống kê làm sạch.

        Returns:
            Từ điển chứa thống kê làm sạch
        """
        outlier_rate = self._outliers_removed / self._total_processed if self._total_processed > 0 else 0
        error_rate = self._sanitization_errors / self._total_processed if self._total_processed > 0 else 0

        return {
            'total_processed': self._total_processed,
            'outliers_removed': self._outliers_removed,
            'sanitization_errors': self._sanitization_errors,
            'outlier_rate': outlier_rate,
            'error_rate': error_rate
        }

    def reset_statistics(self) -> None:
        """Đặt lại thống kê làm sạch."""
        self._total_processed = 0
        self._outliers_removed = 0
        self._sanitization_errors = 0
