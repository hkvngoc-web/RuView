// Thành phần Tab Bảng Điều Khiển

import { healthService } from '../services/health.service.js';
import { poseService } from '../services/pose.service.js';
import { sensingService } from '../services/sensing.service.js';

export class DashboardTab {
  constructor(containerElement) {
    this.container = containerElement;
    this.statsElements = {};
    this.healthSubscription = null;
    this.statsInterval = null;
  }

  // Khởi tạo thành phần
  async init() {
    this.cacheElements();
    await this.loadInitialData();
    this.startMonitoring();
  }

  // Lưu trữ các phần tử DOM
  cacheElements() {
    // Thống kê hệ thống
    const statsContainer = this.container.querySelector('.system-stats');
    if (statsContainer) {
      this.statsElements = {
        bodyRegions: statsContainer.querySelector('[data-stat="body-regions"] .stat-value'),
        samplingRate: statsContainer.querySelector('[data-stat="sampling-rate"] .stat-value'),
        accuracy: statsContainer.querySelector('[data-stat="accuracy"] .stat-value'),
        hardwareCost: statsContainer.querySelector('[data-stat="hardware-cost"] .stat-value')
      };
    }

    // Chỉ báo trạng thái
    this.statusElements = {
      apiStatus: this.container.querySelector('.api-status'),
      streamStatus: this.container.querySelector('.stream-status'),
      hardwareStatus: this.container.querySelector('.hardware-status')
    };
  }

  // Tải dữ liệu ban đầu
  async loadInitialData() {
    try {
      // Lấy thông tin API
      const info = await healthService.getApiInfo();
      this.updateApiInfo(info);

      // Lấy thống kê hiện tại
      const stats = await poseService.getStats(1);
      this.updateStats(stats);

    } catch (error) {
      // API DensePose có thể chưa chạy (chế độ chỉ cảm biến) — bỏ qua lỗi
      console.log('Bảng điều khiển: API DensePose không khả dụng (chế độ chỉ cảm biến)');
    }
  }

  // Bắt đầu giám sát
  startMonitoring() {
    // Đăng ký nhận cập nhật sức khỏe
    this.healthSubscription = healthService.subscribeToHealth(health => {
      this.updateHealthStatus(health);
    });

    // Đăng ký nhận thay đổi trạng thái dịch vụ cảm biến cho chỉ báo nguồn dữ liệu
    this._sensingUnsub = sensingService.onStateChange(() => {
      this.updateDataSourceIndicator();
    });
    // Cũng cập nhật khi có dữ liệu — bắt thay đổi nguồn giữa luồng
    this._sensingDataUnsub = sensingService.onData(() => {
      this.updateDataSourceIndicator();
    });
    // Cập nhật ban đầu
    this.updateDataSourceIndicator();

    // Bắt đầu cập nhật thống kê định kỳ
    this.statsInterval = setInterval(() => {
      this.updateLiveStats();
    }, 5000);

    // Bắt đầu giám sát sức khỏe
    healthService.startHealthMonitoring(30000);
  }

  // Cập nhật chỉ báo nguồn dữ liệu trên bảng điều khiển
  updateDataSourceIndicator() {
    const el = this.container.querySelector('#dashboard-datasource');
    if (!el) return;
    const ds = sensingService.dataSource;
    const statusText = el.querySelector('.status-text');
    const statusMsg  = el.querySelector('.status-message');
    const config = {
      'live':              { text: 'ESP32',     status: 'healthy', msg: 'Phần cứng thực đã kết nối' },
      'server-simulated':  { text: 'MÔ PHỎNG', status: 'warning', msg: 'Máy chủ chạy không có phần cứng' },
      'reconnecting':      { text: 'ĐANG KẾT NỐI LẠI', status: 'degraded', msg: 'Đang thử kết nối...' },
      'simulated':         { text: 'NGOẠI TUYẾN',   status: 'unhealthy', msg: 'Máy chủ không truy cập được, dùng dự phòng cục bộ' },
    };
    const cfg = config[ds] || config['reconnecting'];
    el.className = `component-status status-${cfg.status}`;
    if (statusText) statusText.textContent = cfg.text;
    if (statusMsg)  statusMsg.textContent = cfg.msg;
  }

  // Cập nhật hiển thị thông tin API
  updateApiInfo(info) {
    // Cập nhật phiên bản
    const versionElement = this.container.querySelector('.api-version');
    if (versionElement && info.version) {
      versionElement.textContent = `v${info.version}`;
    }

    // Cập nhật môi trường
    const envElement = this.container.querySelector('.api-environment');
    if (envElement && info.environment) {
      envElement.textContent = info.environment;
      envElement.className = `api-environment env-${info.environment}`;
    }

    // Cập nhật trạng thái tính năng
    if (info.features) {
      this.updateFeatures(info.features);
    }
  }

  // Cập nhật hiển thị tính năng
  updateFeatures(features) {
    const featuresContainer = this.container.querySelector('.features-status');
    if (!featuresContainer) return;

    featuresContainer.innerHTML = '';
    
    Object.entries(features).forEach(([feature, enabled]) => {
      const featureElement = document.createElement('div');
      featureElement.className = `feature-item ${enabled ? 'enabled' : 'disabled'}`;
      
      // Dùng textContent thay vì innerHTML để ngăn XSS = document.createElement('span');
      featureNameSpan.className = 'feature-name';
      featureNameSpan.textContent = this.formatFeatureName(feature);
      
      const featureStatusSpan = document.createElement('span');
      featureStatusSpan.className = 'feature-status';
      featureStatusSpan.textContent = enabled ? '✓' : '✗';
      
      featureElement.appendChild(featureNameSpan);
      featureElement.appendChild(featureStatusSpan);
      featuresContainer.appendChild(featureElement);
    });
  }

  // Cập nhật trạng thái sức khỏe
  updateHealthStatus(health) {
    if (!health) return;

    // Cập nhật trạng thái tổng thể
    const overallStatus = this.container.querySelector('.overall-health');
    if (overallStatus) {
      overallStatus.className = `overall-health status-${health.status}`;
      overallStatus.textContent = health.status.toUpperCase();
    }

    // Cập nhật trạng thái thành phần
    if (health.components) {
      Object.entries(health.components).forEach(([component, status]) => {
        this.updateComponentStatus(component, status);
      });
    }

    // Cập nhật chỉ số
    if (health.metrics) {
      this.updateSystemMetrics(health.metrics);
    }
  }

  // Cập nhật trạng thái thành phần
  updateComponentStatus(component, status) {
    // Ánh xạ tên thành phần backend sang tên thành phần giao diện
    const componentMap = {
      'pose': 'inference',
      'stream': 'streaming',
      'hardware': 'hardware'
    };
    
    const uiComponent = componentMap[component] || component;
    const element = this.container.querySelector(`[data-component="${uiComponent}"]`);
    
    if (element) {
      element.className = `component-status status-${status.status}`;
      const statusText = element.querySelector('.status-text');
      const statusMessage = element.querySelector('.status-message');
      
      if (statusText) {
        statusText.textContent = status.status.toUpperCase();
      }
      
      if (statusMessage && status.message) {
        statusMessage.textContent = status.message;
      }
    }
    
    // Cũng cập nhật trạng thái API dựa trên sức khỏe tổng thể
    if (component === 'hardware') {
      const apiElement = this.container.querySelector(`[data-component="api"]`);
      if (apiElement) {
        apiElement.className = `component-status status-healthy`;
        const apiStatusText = apiElement.querySelector('.status-text');
        const apiStatusMessage = apiElement.querySelector('.status-message');
        
        if (apiStatusText) {
          apiStatusText.textContent = 'KHỎE MẠNH';
        }
        
        if (apiStatusMessage) {
          apiStatusMessage.textContent = 'Máy chủ API đang hoạt động bình thường';
        }
      }
    }
  }

  // Cập nhật chỉ số hệ thống
  updateSystemMetrics(metrics) {
    // Xử lý cả cấu trúc chỉ số phẳng và lồng nhau
    // Backend trả về system_metrics.cpu.percent, mock trả về metrics.cpu.percent
    const systemMetrics = metrics.system_metrics || metrics;
    const cpuPercent = systemMetrics.cpu?.percent || systemMetrics.cpu_percent;
    const memoryPercent = systemMetrics.memory?.percent || systemMetrics.memory_percent;
    const diskPercent = systemMetrics.disk?.percent || systemMetrics.disk_percent;

    // Sử dụng CPU
    const cpuElement = this.container.querySelector('.cpu-usage');
    if (cpuElement && cpuPercent !== undefined) {
      cpuElement.textContent = `${cpuPercent.toFixed(1)}%`;
      this.updateProgressBar('cpu', cpuPercent);
    }

    // Sử dụng bộ nhớ
    const memoryElement = this.container.querySelector('.memory-usage');
    if (memoryElement && memoryPercent !== undefined) {
      memoryElement.textContent = `${memoryPercent.toFixed(1)}%`;
      this.updateProgressBar('memory', memoryPercent);
    }

    // Sử dụng ổ đĩa
    const diskElement = this.container.querySelector('.disk-usage');
    if (diskElement && diskPercent !== undefined) {
      diskElement.textContent = `${diskPercent.toFixed(1)}%`;
      this.updateProgressBar('disk', diskPercent);
    }
  }

  // Cập nhật thanh tiến trình
  updateProgressBar(type, percent) {
    const progressBar = this.container.querySelector(`.progress-bar[data-type="${type}"]`);
    if (progressBar) {
      const fill = progressBar.querySelector('.progress-fill');
      if (fill) {
        fill.style.width = `${percent}%`;
        fill.className = `progress-fill ${this.getProgressClass(percent)}`;
      }
    }
  }

  // Lấy class tiến trình dựa trên phần trăm
  getProgressClass(percent) {
    if (percent >= 90) return 'critical';
    if (percent >= 75) return 'warning';
    return 'normal';
  }

  // Cập nhật thống kê trực tiếp
  async updateLiveStats() {
    try {
      // Lấy dữ liệu tư thế hiện tại
      const currentPose = await poseService.getCurrentPose();
      this.updatePoseStats(currentPose);

      // Lấy tổng hợp khu vực
      const zonesSummary = await poseService.getZonesSummary();
      this.updateZonesDisplay(zonesSummary);

    } catch (error) {
      console.error('Cập nhật thống kê trực tiếp thất bại:', error);
    }
  }

  // Cập nhật thống kê tư thế
  updatePoseStats(poseData) {
    if (!poseData) return;

    // Cập nhật số lượng người
    const personCount = this.container.querySelector('.person-count');
    if (personCount) {
      const count = poseData.persons ? poseData.persons.length : (poseData.total_persons || 0);
      personCount.textContent = count;
    }

    // Cập nhật độ tin cậy trung bình
    const avgConfidence = this.container.querySelector('.avg-confidence');
    if (avgConfidence && poseData.persons && poseData.persons.length > 0) {
      const confidences = poseData.persons.map(p => p.confidence);
      const avg = confidences.length > 0
        ? (confidences.reduce((a, b) => a + b, 0) / confidences.length * 100).toFixed(1)
        : 0;
      avgConfidence.textContent = `${avg}%`;
    } else if (avgConfidence) {
      avgConfidence.textContent = '0%';
    }

    // Cập nhật tổng số phát hiện từ thống kê nếu có
    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount && poseData.total_detections !== undefined) {
      detectionCount.textContent = this.formatNumber(poseData.total_detections);
    }
  }

  // Cập nhật hiển thị khu vực
  updateZonesDisplay(zonesSummary) {
    const zonesContainer = this.container.querySelector('.zones-summary');
    if (!zonesContainer) return;

    zonesContainer.innerHTML = '';
    
    // Xử lý các định dạng tổng hợp khu vực khác nhau
    let zones = {};
    if (zonesSummary && zonesSummary.zones) {
      zones = zonesSummary.zones;
    } else if (zonesSummary && typeof zonesSummary === 'object') {
      zones = zonesSummary;
    }
    
    // Nếu không có dữ liệu khu vực, hiển thị khu vực mặc định
    if (Object.keys(zones).length === 0) {
      ['zone_1', 'zone_2', 'zone_3', 'zone_4'].forEach(zoneId => {
        const zoneElement = document.createElement('div');
        zoneElement.className = 'zone-item';
        
        // Dùng textContent thay vì innerHTML để ngăn XSS
        const zoneNameSpan = document.createElement('span');
        zoneNameSpan.className = 'zone-name';
        zoneNameSpan.textContent = zoneId;

        const zoneCountSpan = document.createElement('span');
        zoneCountSpan.className = 'zone-count';
        zoneCountSpan.textContent = 'chưa xác định';
        
        zoneElement.appendChild(zoneNameSpan);
        zoneElement.appendChild(zoneCountSpan);
        zonesContainer.appendChild(zoneElement);
      });
      return;
    }
    
    Object.entries(zones).forEach(([zoneId, data]) => {
      const zoneElement = document.createElement('div');
      zoneElement.className = 'zone-item';
      const count = typeof data === 'object' ? (data.person_count || data.count || 0) : data;
      
      // Dùng textContent thay vì innerHTML để ngăn XSS
      const zoneNameSpan = document.createElement('span');
      zoneNameSpan.className = 'zone-name';
      zoneNameSpan.textContent = zoneId;
      
      const zoneCountSpan = document.createElement('span');
      zoneCountSpan.className = 'zone-count';
      zoneCountSpan.textContent = String(count);
      
      zoneElement.appendChild(zoneNameSpan);
      zoneElement.appendChild(zoneCountSpan);
      zonesContainer.appendChild(zoneElement);
    });
  }

  // Cập nhật thống kê
  updateStats(stats) {
    if (!stats) return;

    // Cập nhật số lượng phát hiện
    const detectionCount = this.container.querySelector('.detection-count');
    if (detectionCount && stats.total_detections !== undefined) {
      detectionCount.textContent = this.formatNumber(stats.total_detections);
    }

    // Cập nhật độ chính xác nếu có
    if (this.statsElements.accuracy && stats.average_confidence !== undefined) {
      this.statsElements.accuracy.textContent = `${(stats.average_confidence * 100).toFixed(1)}%`;
    }
  }

  // Định dạng tên tính năng
  formatFeatureName(name) {
    return name.replace(/_/g, ' ')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  // Định dạng số lớn
  formatNumber(num) {
    if (num >= 1000000) {
      return `${(num / 1000000).toFixed(1)}M`;
    }
    if (num >= 1000) {
      return `${(num / 1000).toFixed(1)}K`;
    }
    return num.toString();
  }

  // Hiển thị thông báo lỗi
  showError(message) {
    const errorContainer = this.container.querySelector('.error-container');
    if (errorContainer) {
      errorContainer.textContent = message;
      errorContainer.style.display = 'block';
      
      setTimeout(() => {
        errorContainer.style.display = 'none';
      }, 5000);
    }
  }

  // Dọn dẹp
    if (this.healthSubscription) {
      this.healthSubscription();
    }
    if (this._sensingUnsub) this._sensingUnsub();
    if (this._sensingDataUnsub) this._sensingDataUnsub();

    if (this.statsInterval) {
      clearInterval(this.statsInterval);
    }

    healthService.stopHealthMonitoring();
  }
}