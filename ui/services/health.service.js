// Dịch vụ Sức khoẻ cho Giao diện WiFi-DensePose

import { API_CONFIG } from '../config/api.config.js';
import { apiService } from './api.service.js';

export class HealthService {
  constructor() {
    this.healthCheckInterval = null;
    this.healthSubscribers = [];
    this.lastHealthStatus = null;
  }

  // Lấy sức khoẻ hệ thống
  async getSystemHealth() {
    const health = await apiService.get(API_CONFIG.ENDPOINTS.HEALTH.SYSTEM);
    this.lastHealthStatus = health;
    this.notifySubscribers(health);
    return health;
  }

  // Kiểm tra sẵn sàng
  async checkReadiness() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.READY);
  }

  // Kiểm tra hoạt động
  async checkLiveness() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.LIVE);
  }

  // Lấy chỉ số hệ thống
  async getSystemMetrics() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.METRICS);
  }

  // Lấy thông tin phiên bản
  async getVersion() {
    return apiService.get(API_CONFIG.ENDPOINTS.HEALTH.VERSION);
  }

  // Lấy thông tin API
  async getApiInfo() {
    return apiService.get(API_CONFIG.ENDPOINTS.INFO);
  }

  // Lấy trạng thái API
  async getApiStatus() {
    return apiService.get(API_CONFIG.ENDPOINTS.STATUS);
  }

  // Bắt đầu kiểm tra sức khoẻ định kỳ
  startHealthMonitoring(intervalMs = 30000) {
    if (this.healthCheckInterval) {
      console.warn('Giám sát sức khoẻ đã hoạt động');
      return;
    }

    // Kiểm tra ban đầu (im lặng khi thất bại — API DensePose có thể không chạy)
    this.getSystemHealth().catch(() => {
      // API DensePose không chạy — chế độ chỉ cảm biến, bỏ qua bỏ phiếu
      this._backendUnavailable = true;
    });

    // Thiết lập kiểm tra định kỳ chỉ khi backend có thể truy cập
    this.healthCheckInterval = setInterval(() => {
      if (this._backendUnavailable) return;
      this.getSystemHealth().catch(error => {
        this.notifySubscribers({
          status: 'error',
          error: error.message,
          timestamp: new Date().toISOString()
        });
      });
    }, intervalMs);
  }

  // Dừng giám sát sức khoẻ
  stopHealthMonitoring() {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = null;
    }
  }

  // Đăng ký cập nhật sức khoẻ
  subscribeToHealth(callback) {
    this.healthSubscribers.push(callback);
    
    // Gửi trạng thái đã biết cuối cùng nếu có
    if (this.lastHealthStatus) {
      callback(this.lastHealthStatus);
    }
    
    // Trả về hàm huỷ đăng ký
    return () => {
      const index = this.healthSubscribers.indexOf(callback);
      if (index > -1) {
        this.healthSubscribers.splice(index, 1);
      }
    };
  }

  // Thông báo cho người đăng ký
  notifySubscribers(health) {
    this.healthSubscribers.forEach(callback => {
      try {
        callback(health);
      } catch (error) {
        console.error('Lỗi trong người đăng ký sức khoẻ:', error);
      }
    });
  }

  // Kiểm tra hệ thống có khoẻ mạnh không
  isSystemHealthy() {
    if (!this.lastHealthStatus) {
      return null;
    }
    return this.lastHealthStatus.status === 'healthy';
  }

  // Lấy trạng thái thành phần
  getComponentStatus(componentName) {
    if (!this.lastHealthStatus?.components) {
      return null;
    }
    return this.lastHealthStatus.components[componentName];
  }

  // Dọn dẹp
  dispose() {
    this.stopHealthMonitoring();
    this.healthSubscribers = [];
    this.lastHealthStatus = null;
  }
}

// Tạo thể hiện singleton
export const healthService = new HealthService();