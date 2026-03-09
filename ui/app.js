// Ứng Dụng WiFi DensePose - Điểm Khởi Đầu Chính

import { TabManager } from './components/TabManager.js';
import { DashboardTab } from './components/DashboardTab.js';
import { HardwareTab } from './components/HardwareTab.js';
import { LiveDemoTab } from './components/LiveDemoTab.js';
import { SensingTab } from './components/SensingTab.js';
import { apiService } from './services/api.service.js';
import { wsService } from './services/websocket.service.js';
import { healthService } from './services/health.service.js';
import { sensingService } from './services/sensing.service.js';
import { backendDetector } from './utils/backend-detector.js';

class WiFiDensePoseApp {
  constructor() {
    this.components = {};
    this.isInitialized = false;
  }

  // Khởi tạo ứng dụng
  async init() {
    try {
      console.log('Đang khởi tạo WiFi DensePose UI...');

      // Thiết lập xử lý lỗi
      this.setupErrorHandling();

      // Khởi tạo các dịch vụ
      await this.initializeServices();

      // Khởi tạo các thành phần giao diện
      this.initializeComponents();

      // Thiết lập bộ lắng nghe sự kiện toàn cục
      this.setupEventListeners();

      this.isInitialized = true;
      console.log('WiFi DensePose UI đã khởi tạo thành công');

    } catch (error) {
      console.error('Khởi tạo ứng dụng thất bại:', error);
      this.showGlobalError('Khởi tạo ứng dụng thất bại. Vui lòng tải lại trang.');
    }
  }

  // Khởi tạo các dịch vụ
  async initializeServices() {
    // Thêm interceptor phản hồi để xử lý lỗi
    apiService.addResponseInterceptor(async (response, url) => {
      if (!response.ok && response.status === 401) {
        console.warn('Yêu cầu xác thực cho:', url);
        // Xử lý xác thực nếu cần
      }
      return response;
    });

    // Phát hiện backend có sẵn và khởi tạo tương ứng
    const useMock = await backendDetector.shouldUseMockServer();

    if (useMock) {
      console.log('🧪 Đang khởi tạo với máy chủ giả lập để kiểm thử');
      // Import và khởi động mock server khi cần
      const { mockServer } = await import('./utils/mock-server.js');
      mockServer.start();

      // Hiển thị thông báo cho người dùng
      this.showBackendStatus('Máy chủ giả lập đang hoạt động - chế độ kiểm thử', 'warning');
    } else {
      console.log('🔌 Đang kết nối tới backend...');

      try {
        const health = await healthService.checkLiveness();
        console.log('✅ Backend đang phản hồi:', health);
        this.showBackendStatus('Đã kết nối tới máy chủ cảm biến Rust', 'success');
      } catch (error) {
        console.warn('⚠️ Backend không khả dụng:', error.message);
        this.showBackendStatus('Backend không khả dụng — hãy khởi động sensing-server', 'warning');
      }

      // Khởi động dịch vụ WebSocket cảm biến sớm để bảng điều khiển và
      // tab demo trực tiếp có thể hiển thị trạng thái nguồn dữ liệu ngay.
      sensingService.start();
    }
  }

  // Khởi tạo các thành phần giao diện
  initializeComponents() {
    const container = document.querySelector('.container');
    if (!container) {
      throw new Error('Không tìm thấy container chính');
    }

    // Khởi tạo trình quản lý tab
    this.components.tabManager = new TabManager(container);
    this.components.tabManager.init();

    // Khởi tạo các thành phần tab
    this.initializeTabComponents();

    // Thiết lập xử lý chuyển tab
    this.components.tabManager.onTabChange((newTab, oldTab) => {
      this.handleTabChange(newTab, oldTab);
    });

  }

  // Khởi tạo từng thành phần tab
  initializeTabComponents() {
    // Tab bảng điều khiển
    const dashboardContainer = document.getElementById('dashboard');
    if (dashboardContainer) {
      this.components.dashboard = new DashboardTab(dashboardContainer);
      this.components.dashboard.init().catch(error => {
        console.error('Khởi tạo bảng điều khiển thất bại:', error);
      });
    }

    // Tab phần cứng
    const hardwareContainer = document.getElementById('hardware');
    if (hardwareContainer) {
      this.components.hardware = new HardwareTab(hardwareContainer);
      this.components.hardware.init();
    }

    // Tab demo trực tiếp
    const demoContainer = document.getElementById('demo');
    if (demoContainer) {
      this.components.demo = new LiveDemoTab(demoContainer);
      this.components.demo.init();
    }

    // Tab cảm biến
    const sensingContainer = document.getElementById('sensing');
    if (sensingContainer) {
      this.components.sensing = new SensingTab(sensingContainer);
    }

    // Tab huấn luyện - tải chậm để tránh lỗi ảnh hưởng tab khác
    this.initTrainingTab();

    // Tab kiến trúc - nội dung tĩnh, không cần component

    // Tab hiệu năng - nội dung tĩnh, không cần component

    // Tab ứng dụng - nội dung tĩnh, không cần component
  }

  // Tải chậm các panel tab Huấn luyện (import động để lỗi không ảnh hưởng tab khác)
  async initTrainingTab() {
    try {
      const [{ default: TrainingPanel }, { default: ModelPanel }] = await Promise.all([
        import('./components/TrainingPanel.js'),
        import('./components/ModelPanel.js')
      ]);

      const trainingContainer = document.getElementById('training-panel-container');
      if (trainingContainer) {
        this.components.trainingPanel = new TrainingPanel(trainingContainer);
      }

      const modelContainer = document.getElementById('model-panel-container');
      if (modelContainer) {
        this.components.modelPanel = new ModelPanel(modelContainer);
      }
    } catch (error) {
      console.error('Tải thành phần tab Huấn luyện thất bại:', error);
    }
  }

  // Xử lý chuyển tab
  handleTabChange(newTab, oldTab) {
    console.log(`Tab đã chuyển từ ${oldTab} sang ${newTab}`);

    // Dừng demo nếu rời khỏi tab demo
    if (oldTab === 'demo' && this.components.demo) {
      this.components.demo.stopDemo();
    }

    // Cập nhật các thành phần dựa trên tab đang hoạt động
    switch (newTab) {
      case 'dashboard':
        // Bảng điều khiển tự cập nhật khi hiển thị
        break;

      case 'hardware':
        // Trực quan hóa phần cứng luôn hoạt động
        break;

      case 'demo':
        // Demo khởi động thủ công
        break;

      case 'sensing':
        // Khởi tạo chậm tab cảm biến khi truy cập lần đầu
        if (this.components.sensing && !this.components.sensing.splatRenderer) {
          this.components.sensing.init().catch(error => {
            console.error('Khởi tạo tab cảm biến thất bại:', error);
          });
        }
        break;

      case 'training':
        // Làm mới các panel khi tab huấn luyện hiển thị
        if (this.components.trainingPanel && typeof this.components.trainingPanel.refresh === 'function') {
          this.components.trainingPanel.refresh();
        }
        if (this.components.modelPanel && typeof this.components.modelPanel.refresh === 'function') {
          this.components.modelPanel.refresh();
        }
        break;
    }
  }

  // Thiết lập bộ lắng nghe sự kiện toàn cục
  setupEventListeners() {
    // Xử lý thay đổi kích thước cửa sổ
    window.addEventListener('resize', () => {
      this.handleResize();
    });

    // Xử lý thay đổi trạng thái hiển thị
    document.addEventListener('visibilitychange', () => {
      this.handleVisibilityChange();
    });

    // Xử lý trước khi đóng trang
    window.addEventListener('beforeunload', () => {
      this.cleanup();
    });
  }

  // Xử lý thay đổi kích thước cửa sổ
  handleResize() {
    // Cập nhật kích thước canvas nếu cần
    const canvases = document.querySelectorAll('canvas');
    canvases.forEach(canvas => {
      const rect = canvas.parentElement.getBoundingClientRect();
      if (canvas.width !== rect.width || canvas.height !== rect.height) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
    });
  }

  // Xử lý thay đổi trạng thái hiển thị
  handleVisibilityChange() {
    if (document.hidden) {
      // Tạm dừng cập nhật khi trang bị ẩn
      console.log('Trang bị ẩn, tạm dừng cập nhật');
      healthService.stopHealthMonitoring();
    } else {
      // Tiếp tục cập nhật khi trang hiển thị
      console.log('Trang hiển thị, tiếp tục cập nhật');
      healthService.startHealthMonitoring();
    }
  }

  // Thiết lập xử lý lỗi
  setupErrorHandling() {
    window.addEventListener('error', (event) => {
      if (event.error) {
        console.error('Lỗi toàn cục:', event.error);
        this.showGlobalError('Đã xảy ra lỗi không mong muốn');
      }
    });

    window.addEventListener('unhandledrejection', (event) => {
      if (event.reason) {
        console.error('Promise bị từ chối không xử lý:', event.reason);
        this.showGlobalError('Đã xảy ra lỗi không mong muốn');
      }
    });
  }

  // Hiển thị thông báo trạng thái backend
  showBackendStatus(message, type) {
    // Create status notification if it doesn't exist
    let statusToast = document.getElementById('backendStatusToast');
    if (!statusToast) {
      statusToast = document.createElement('div');
      statusToast.id = 'backendStatusToast';
      statusToast.className = 'backend-status-toast';
      document.body.appendChild(statusToast);
    }

    statusToast.textContent = message;
    statusToast.className = `backend-status-toast ${type}`;
    statusToast.classList.add('show');

    // Tự ẩn thông báo thành công, giữ cảnh báo và lỗi lâu hơn
    const timeout = type === 'success' ? 3000 : 8000;
    setTimeout(() => {
      statusToast.classList.remove('show');
    }, timeout);
  }

  // Hiển thị thông báo lỗi toàn cục
  showGlobalError(message) {
    // Tạo thông báo lỗi nếu chưa tồn tại
    let errorToast = document.getElementById('globalErrorToast');
    if (!errorToast) {
      errorToast = document.createElement('div');
      errorToast.id = 'globalErrorToast';
      errorToast.className = 'error-toast';
      document.body.appendChild(errorToast);
    }

    errorToast.textContent = message;
    errorToast.classList.add('show');

    setTimeout(() => {
      errorToast.classList.remove('show');
    }, 5000);
  }

  // Dọn dẹp tài nguyên
  cleanup() {
    console.log('Đang dọn dẹp tài nguyên ứng dụng...');

    // Hủy tất cả thành phần
    Object.values(this.components).forEach(component => {
      if (component && typeof component.dispose === 'function') {
        component.dispose();
      }
    });

    // Ngắt tất cả kết nối WebSocket
    wsService.disconnectAll();

    // Dừng giám sát sức khỏe
    healthService.dispose();
  }

  // API công khai
  getComponent(name) {
    return this.components[name];
  }

  isReady() {
    return this.isInitialized;
  }
}

// Khởi tạo ứng dụng khi DOM sẵn sàng
document.addEventListener('DOMContentLoaded', () => {
  window.wifiDensePoseApp = new WiFiDensePoseApp();
  window.wifiDensePoseApp.init();
});

// Xuất để kiểm thử
export { WiFiDensePoseApp };