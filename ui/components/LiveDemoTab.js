// Thành phần Tab Demo Trực tiếp - Phiên bản Nâng cao

import { PoseDetectionCanvas } from './PoseDetectionCanvas.js';
import { poseService } from '../services/pose.service.js';
import { streamService } from '../services/stream.service.js';
import { wsService } from '../services/websocket.service.js';
import { sensingService } from '../services/sensing.service.js';

// Dịch vụ tùy chọn - tải lười trong init() để tránh chặn đồ thị module
let modelService = null;
let trainingService = null;

export class LiveDemoTab {
  constructor(containerElement) {
    this.container = containerElement;
    this.state = {
      isActive: false,
      connectionState: 'disconnected',
      currentZone: 'zone_1',
      debugMode: false,
      autoReconnect: true,
      renderMode: 'skeleton',
      // 'unknown' | 'signal_derived' | 'model_inference' — nguồn ước lượng tư thế
      poseSource: 'unknown'
    };
    
    this.components = {
      poseCanvas: null,
      settingsPanel: null
    };
    
    this.metrics = {
      startTime: null,
      frameCount: 0,
      errorCount: 0,
      lastUpdate: null,
      connectionAttempts: 0
    };
    
    // Trạng thái điều khiển mô hình
    this.modelState = {
      models: [],
      activeModelId: null,
      activeModelInfo: null,
      loraProfiles: [],
      selectedLoraProfile: null,
      loading: false
    };

    // Trạng thái huấn luyện
    this.trainingState = {
      status: 'idle',       // 'idle' | 'training' | 'recording'
      epoch: 0,
      totalEpochs: 0,
      showTrainingPanel: false
    };

    // Trạng thái chế độ xem chia đôi A/B
    this.splitViewActive = false;

    this.subscriptions = [];
    this.logger = this.createLogger();
    
    // Cấu hình
    this.config = {
      defaultZone: 'zone_1',
      reconnectDelay: 3000,
      healthCheckInterval: 10000,
      maxConnectionAttempts: 5,
      enablePerformanceMonitoring: true
    };
  }

  createLogger() {
    return {
      debug: (...args) => console.debug('[LIVEDEMO-DEBUG]', new Date().toISOString(), ...args),
      info: (...args) => console.info('[LIVEDEMO-INFO]', new Date().toISOString(), ...args),
      warn: (...args) => console.warn('[LIVEDEMO-WARN]', new Date().toISOString(), ...args),
      error: (...args) => console.error('[LIVEDEMO-ERROR]', new Date().toISOString(), ...args)
    };
  }

  // Khởi tạo thành phần
  async init() {
    try {
      this.logger.info('Đang khởi tạo thành phần LiveDemoTab');

      // Tải dịch vụ tùy chọn (không chặn)
      try {
        const mod = await import('../services/model.service.js');
        modelService = mod.modelService;
      } catch (e) { /* tính năng mô hình bị tắt */ }
      try {
        const mod = await import('../services/training.service.js');
        trainingService = mod.trainingService;
      } catch (e) { /* tính năng huấn luyện bị tắt */ }

      // Tạo cấu trúc DOM nâng cao
      this.createEnhancedStructure();

      // Khởi tạo canvas phát hiện tư thế
      this.initializePoseCanvas();

      // Thiết lập điều khiển và bộ xử lý sự kiện
      this.setupEnhancedControls();

      // Thiết lập giám sát và kiểm tra sức khỏe
      this.setupMonitoring();

      // Lấy danh sách mô hình khả dụng khi khởi tạo
      this.fetchModels();

      // Thiết lập bộ lắng nghe sự kiện mô hình/huấn luyện
      this.setupServiceListeners();

      // Khởi tạo trạng thái
      this.updateUI();

      // Tự động bắt đầu phát hiện tư thế khi backend khả dụng.
      // Kiểm tra sau một khoảng trễ ngắn (WS cảm biến có thể vẫn đang kết nối).
      this._autoStartOnce = false;
      const tryAutoStart = () => {
        if (this._autoStartOnce || this.state.isActive) return;
        const ds = sensingService.dataSource;
        if (ds === 'live' || ds === 'server-simulated') {
          this._autoStartOnce = true;
          this.logger.info('Tự động bắt đầu phát hiện tư thế (nguồn dữ liệu: ' + ds + ')');
          this.startDemo();
        }
      };
      setTimeout(tryAutoStart, 2000);
      // Cũng lắng nghe thay đổi trạng thái cảm biến trong trường hợp máy chủ kết nối sau
      this._autoStartUnsub = sensingService.onStateChange(tryAutoStart);

      this.logger.info('Thành phần LiveDemoTab đã khởi tạo thành công');
    } catch (error) {
      this.logger.error('Khởi tạo LiveDemoTab thất bại', { error: error.message });
      this.showError(`Khởi tạo thất bại: ${error.message}`);
    }
  }

  createEnhancedStructure() {
    // Kiểm tra xem có cần xây dựng lại cấu trúc không
    const existingCanvas = this.container.querySelector('#pose-detection-main');
    if (!existingCanvas) {
      // Tạo cấu trúc nâng cao nếu chưa tồn tại
      const enhancedHTML = `
        <div class="live-demo-enhanced">
          <!-- Banner nguồn dữ liệu — chỉ báo nổi bật cho trực tiếp vs mô phỏng -->
          <div id="demo-source-banner" class="demo-source-banner demo-source-unknown" role="status" aria-live="polite">
            Đang phát hiện nguồn dữ liệu...
          </div>

          <div class="demo-header">
            <div class="demo-title">
              <h2>Phát hiện Tư thế Con người Trực tiếp</h2>
              <div class="demo-status">
                <span class="status-indicator" id="demo-status-indicator"></span>
                <span class="status-text" id="demo-status-text">Sẵn sàng</span>
              </div>
            </div>
            <div class="demo-controls">
              <button class="btn btn--primary" id="start-enhanced-demo">Bắt đầu Phát hiện</button>
              <button class="btn btn--secondary" id="stop-enhanced-demo" disabled>Dừng Phát hiện</button>
              <button class="btn btn--accent" id="run-offline-demo">Demo</button>
              <button class="btn btn--primary" id="toggle-debug">Chế độ Gỡ lỗi</button>
              <select class="zone-select" id="zone-selector">
                <option value="zone_1">Vùng 1</option>
                <option value="zone_2">Vùng 2</option>
                <option value="zone_3">Vùng 3</option>
              </select>
            </div>
          </div>
          
          <div class="demo-content">
            <div class="demo-main">
              <div id="pose-detection-main" class="pose-detection-container"></div>
            </div>
            
            <div class="demo-sidebar">
              <div class="metrics-panel">
                <h4>Chỉ số Hiệu suất</h4>
                <div class="metric">
                  <label>Trạng thái Kết nối:</label>
                  <span id="connection-status">Ngắt kết nối</span>
                </div>
                <div class="metric">
                  <label>Khung hình Đã xử lý:</label>
                  <span id="frame-count">0</span>
                </div>
                <div class="metric">
                  <label>Thời gian hoạt động:</label>
                  <span id="uptime">0s</span>
                </div>
                <div class="metric">
                  <label>Lỗi:</label>
                  <span id="error-count">0</span>
                </div>
                <div class="metric">
                  <label>Cập nhật Cuối:</label>
                  <span id="last-update">Chưa bao giờ</span>
                </div>
              </div>
              
              <div class="pose-source-panel">
                <h4>Chế độ Ước lượng</h4>
                <div class="pose-source-indicator" id="pose-source-indicator">
                  <span class="pose-source-badge pose-source-unknown" id="pose-source-badge">Không xác định</span>
                  <p class="pose-source-description" id="pose-source-description">
                    Đang chờ khung hình đầu tiên...
                  </p>
                </div>
              </div>

              <div class="model-control-panel" id="model-control-panel">
                <h4>Điều khiển Mô hình</h4>
                <div class="setting-row-ld">
                  <label class="ld-label">Mô hình:</label>
                  <select class="ld-select" id="model-selector">
                    <option value="">Trích xuất từ Tín hiệu (không có mô hình)</option>
                  </select>
                </div>
                <div class="model-info-row" id="model-active-info" style="display: none;">
                  <span class="ld-label" id="model-active-name"></span>
                  <span class="model-pck-badge" id="model-active-pck"></span>
                </div>
                <div class="setting-row-ld" id="lora-profile-row" style="display: none;">
                  <label class="ld-label">Hồ sơ LoRA:</label>
                  <select class="ld-select" id="lora-profile-selector">
                    <option value="">Không</option>
                  </select>
                </div>
                <div class="model-actions">
                  <button class="btn-ld btn-ld-accent" id="load-model-btn">Tải Mô hình</button>
                  <button class="btn-ld btn-ld-muted" id="unload-model-btn" disabled>Gỡ tải</button>
                </div>
                <div class="model-status-text" id="model-status-text">Chưa tải mô hình</div>
              </div>

              <div class="split-view-panel">
                <div class="setting-row-ld">
                  <label class="ld-label">So sánh: Tín hiệu vs Mô hình</label>
                  <button class="btn-ld btn-ld-toggle" id="split-view-toggle" disabled>Tắt</button>
                </div>
              </div>

              <div class="training-quick-panel" id="training-quick-panel">
                <h4>Huấn luyện</h4>
                <div class="training-status-row">
                  <span class="training-status-badge" id="training-status-badge">Chờ</span>
                </div>
                <div class="training-actions">
                  <button class="btn-ld btn-ld-accent" id="open-training-panel-btn">Mở Bảng Huấn luyện</button>
                  <button class="btn-ld btn-ld-muted" id="quick-record-btn">Thu 60 giây</button>
                </div>
              </div>

              <div class="setup-guide-panel">
                <h4>Hướng dẫn Cài đặt</h4>
                <div class="setup-levels">
                  <div class="setup-level">
                    <span class="setup-level-icon">1x</span>
                    <div class="setup-level-info">
                      <strong>1 ESP32 + 1 AP</strong>
                      <p>Hiện diện, hô hấp, chuyển động thô</p>
                    </div>
                  </div>
                  <div class="setup-level">
                    <span class="setup-level-icon">3x</span>
                    <div class="setup-level-info">
                      <strong>2-3 ESP32s</strong>
                      <p>Định vị cơ thể, hướng chuyển động</p>
                    </div>
                  </div>
                  <div class="setup-level">
                    <span class="setup-level-icon">4x+</span>
                    <div class="setup-level-info">
                      <strong>4+ ESP32 + mô hình đã huấn luyện</strong>
                      <p>Theo dõi chi riêng lẻ, tư thế đầy đủ</p>
                    </div>
                  </div>
                </div>
                <p class="setup-note">
                  Chế độ Trích xuất Tín hiệu sử dụng đặc trưng CSI tổng hợp.
                  Để theo dõi từng chi, tải mô hình đã huấn luyện <code>.rvf</code>
                  với <code>--model path.rvf</code> và sử dụng 4+ cảm biến.
                </p>
              </div>

              <div class="health-panel">
                <h4>Sức khỏe Hệ thống</h4>
                <div class="health-check">
                  <label>Sức khỏe API:</label>
                  <span id="api-health">Không xác định</span>
                </div>
                <div class="health-check">
                  <label>WebSocket:</label>
                  <span id="websocket-health">Không xác định</span>
                </div>
                <div class="health-check">
                  <label>Dịch vụ Tư thế:</label>
                  <span id="pose-service-health">Không xác định</span>
                </div>
              </div>
              
              <div class="debug-panel" id="debug-panel" style="display: none;">
                <h4>Thông tin Gỡ lỗi</h4>
                <div class="debug-actions">
                  <button class="btn btn-sm" id="force-reconnect">Buộc Kết nối lại</button>
                  <button class="btn btn-sm" id="clear-errors">Xóa Lỗi</button>
                  <button class="btn btn-sm" id="export-logs">Xuất Nhật ký</button>
                </div>
                <div class="debug-info">
                  <textarea id="debug-output" readonly rows="8" cols="30"></textarea>
                </div>
              </div>
            </div>
          </div>
          
          <div class="demo-footer">
            <div class="error-display" id="error-display" style="display: none;"></div>
          </div>
        </div>
      `;
      
      this.container.innerHTML = enhancedHTML;
      this.addEnhancedStyles();
    }
  }

  addEnhancedStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .live-demo-enhanced {
        display: flex;
        flex-direction: column;
        height: 100%;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        background: #0a0f1a;
        color: #e0e0e0;
      }

      .demo-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 20px 24px;
        background: rgba(15, 20, 35, 0.95);
        backdrop-filter: blur(10px);
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 2px 20px rgba(0, 0, 0, 0.3);
        position: relative;
        z-index: 10;
      }

      .demo-title {
        display: flex;
        align-items: center;
        gap: 20px;
      }

      .demo-title h2 {
        margin: 0;
        color: #e0e0e0;
        font-size: 22px;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
      }

      .demo-status {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 16px;
        background: rgba(30, 40, 60, 0.8);
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.1);
      }

      .status-indicator {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #6c757d;
        transition: all 0.3s ease;
        box-shadow: 0 0 0 2px rgba(108, 117, 125, 0.2);
      }

      .status-indicator.active { 
        background: #28a745; 
        box-shadow: 0 0 0 2px rgba(40, 167, 69, 0.2), 0 0 8px rgba(40, 167, 69, 0.4);
      }
      .status-indicator.connecting { 
        background: #ffc107; 
        box-shadow: 0 0 0 2px rgba(255, 193, 7, 0.2), 0 0 8px rgba(255, 193, 7, 0.4);
        animation: pulse 1.5s ease-in-out infinite;
      }
      .status-indicator.error { 
        background: #dc3545; 
        box-shadow: 0 0 0 2px rgba(220, 53, 69, 0.2), 0 0 8px rgba(220, 53, 69, 0.4);
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }

      .status-text {
        font-size: 13px;
        font-weight: 500;
        color: #b0b8c8;
      }

      .demo-controls {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .demo-controls .btn {
        padding: 10px 20px;
        border: 1px solid transparent;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-width: 120px;
        justify-content: center;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      }

      .btn--primary {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-color: transparent;
      }

      .btn--primary:hover:not(:disabled) {
        transform: translateY(-2px);
        box-shadow: 0 4px 16px rgba(102, 126, 234, 0.4);
      }

      .btn--secondary {
        background: rgba(30, 40, 60, 0.8);
        color: #b0b8c8;
        border-color: rgba(255, 255, 255, 0.1);
      }

      .btn--secondary:hover:not(:disabled) {
        background: rgba(40, 50, 75, 0.9);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
      }

      .btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
        transform: none !important;
        box-shadow: none !important;
      }

      .btn-sm { 
        padding: 6px 12px; 
        font-size: 12px;
        min-width: 80px;
      }

      .zone-select {
        padding: 10px 14px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        background: rgba(30, 40, 60, 0.8);
        color: #b0b8c8;
        font-size: 14px;
        cursor: pointer;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        transition: all 0.2s ease;
      }

      .zone-select:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.2);
      }

      .demo-content {
        display: flex;
        flex: 1;
        gap: 24px;
        padding: 24px;
        background: #0a0f1a;
      }

      .demo-main {
        flex: 2;
        min-height: 500px;
        background: #111827;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        border: 1px solid rgba(255, 255, 255, 0.06);
      }

      .pose-detection-container {
        height: 100%;
        position: relative;
      }

      .demo-sidebar {
        flex: 1;
        display: flex;
        flex-direction: column;
        gap: 20px;
        max-width: 300px;
      }

      .metrics-panel, .health-panel, .debug-panel {
        background: rgba(17, 24, 39, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 15px;
      }

      .metrics-panel h4, .health-panel h4, .debug-panel h4 {
        margin: 0 0 15px 0;
        color: #e0e0e0;
        font-size: 14px;
        font-weight: 600;
      }

      .metric, .health-check {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        font-size: 13px;
      }

      .metric label, .health-check label {
        color: #8899aa;
      }

      .metric span, .health-check span {
        font-weight: 500;
        color: #c8d0dc;
      }

      .debug-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin-bottom: 10px;
      }

      .debug-info textarea {
        width: 100%;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 4px;
        padding: 8px;
        font-family: monospace;
        font-size: 11px;
        resize: vertical;
        background: #0a0f1a;
        color: #c8d0dc;
      }

      .error-display {
        background: rgba(220, 53, 69, 0.15);
        color: #f5a0a8;
        border: 1px solid rgba(220, 53, 69, 0.3);
        border-radius: 4px;
        padding: 12px;
        margin: 10px 20px;
      }

      .health-unknown { color: #6c757d; }
      .health-good { color: #28a745; }
      .health-poor { color: #ffc107; }
      .health-bad { color: #dc3545; }

      /* Chỉ báo chế độ ước lượng tư thế */
      .pose-source-panel {
        background: rgba(17, 24, 39, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 15px;
      }

      .pose-source-panel h4 {
        margin: 0 0 12px 0;
        color: #e0e0e0;
        font-size: 14px;
        font-weight: 600;
      }

      .pose-source-indicator {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .pose-source-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        width: fit-content;
      }

      .pose-source-unknown {
        background: rgba(108, 117, 125, 0.15);
        color: #8899aa;
        border: 1px solid rgba(108, 117, 125, 0.3);
      }

      .pose-source-signal {
        background: rgba(0, 204, 136, 0.12);
        color: #00cc88;
        border: 1px solid rgba(0, 204, 136, 0.3);
      }

      .pose-source-model {
        background: rgba(102, 126, 234, 0.12);
        color: #8ea4f0;
        border: 1px solid rgba(102, 126, 234, 0.3);
      }

      .pose-source-description {
        margin: 0;
        font-size: 11px;
        color: #8899aa;
        line-height: 1.4;
      }

      .setup-guide-panel {
        background: rgba(17, 24, 39, 0.9);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 15px;
      }

      .setup-guide-panel h4 {
        margin: 0 0 12px 0;
        color: #e0e0e0;
        font-size: 14px;
        font-weight: 600;
      }

      .setup-levels {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .setup-level {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px;
        border-radius: 6px;
        background: rgba(30, 40, 60, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.06);
      }

      .setup-level-icon {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-size: 11px;
        font-weight: 700;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }

      .setup-level-info strong {
        font-size: 12px;
        color: #c8d0dc;
        display: block;
      }

      .setup-level-info p {
        margin: 2px 0 0;
        font-size: 11px;
        color: #8899aa;
      }

      .setup-note {
        margin: 10px 0 0;
        font-size: 11px;
        color: #6b7a8d;
        line-height: 1.5;
      }

      .setup-note code {
        background: rgba(102, 126, 234, 0.12);
        color: #8ea4f0;
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 10px;
      }

      /* Bảng Điều khiển Mô hình */
      .model-control-panel,
      .split-view-panel,
      .training-quick-panel {
        background: rgba(17, 24, 39, 0.9);
        border: 1px solid rgba(56, 68, 89, 0.6);
        border-radius: 12px;
        padding: 16px;
      }

      .model-control-panel h4,
      .training-quick-panel h4 {
        margin: 0 0 12px 0;
        color: #e0e0e0;
        font-size: 14px;
        font-weight: 600;
      }

      .setting-row-ld {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        gap: 8px;
      }

      .ld-label {
        color: #8899aa;
        font-size: 11px;
        flex-shrink: 0;
      }

      .ld-select {
        flex: 1;
        padding: 6px 10px;
        border: 1px solid rgba(56, 68, 89, 0.6);
        border-radius: 6px;
        background: rgba(15, 20, 35, 0.8);
        color: #b0b8c8;
        font-size: 12px;
        cursor: pointer;
        min-width: 0;
      }

      .ld-select:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.15);
      }

      .ld-select option {
        background: #1a2234;
        color: #c8d0dc;
      }

      .model-info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        padding: 6px 8px;
        background: rgba(30, 40, 60, 0.6);
        border-radius: 6px;
      }

      .model-pck-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 8px;
        background: rgba(102, 126, 234, 0.15);
        color: #8ea4f0;
      }

      .model-actions,
      .training-actions {
        display: flex;
        gap: 8px;
        margin-top: 10px;
      }

      .btn-ld {
        flex: 1;
        padding: 7px 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        text-align: center;
      }

      .btn-ld:disabled {
        opacity: 0.4;
        cursor: not-allowed;
      }

      .btn-ld-accent {
        background: rgba(102, 126, 234, 0.15);
        color: #8ea4f0;
        border-color: rgba(102, 126, 234, 0.3);
      }

      .btn-ld-accent:hover:not(:disabled) {
        background: rgba(102, 126, 234, 0.25);
        border-color: rgba(102, 126, 234, 0.5);
      }

      .btn-ld-muted {
        background: rgba(30, 40, 60, 0.8);
        color: #8899aa;
        border-color: rgba(255, 255, 255, 0.08);
      }

      .btn-ld-muted:hover:not(:disabled) {
        background: rgba(40, 50, 70, 0.9);
        color: #b0b8c8;
      }

      .btn-ld-toggle {
        min-width: 44px;
        flex: 0;
        padding: 4px 10px;
        background: rgba(30, 40, 60, 0.8);
        color: #8899aa;
        border-color: rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        font-size: 11px;
      }

      .btn-ld-toggle.active {
        background: rgba(0, 212, 255, 0.15);
        color: #00d4ff;
        border-color: rgba(0, 212, 255, 0.4);
      }

      .model-status-text {
        margin-top: 8px;
        font-size: 11px;
        color: #6b7a8d;
      }

      .training-status-row {
        margin-bottom: 8px;
      }

      .training-status-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        background: rgba(108, 117, 125, 0.15);
        color: #8899aa;
        border: 1px solid rgba(108, 117, 125, 0.3);
      }

      .training-status-badge.training {
        background: rgba(251, 191, 36, 0.12);
        color: #fbbf24;
        border-color: rgba(251, 191, 36, 0.3);
      }

      .training-status-badge.recording {
        background: rgba(239, 68, 68, 0.12);
        color: #ef4444;
        border-color: rgba(239, 68, 68, 0.3);
        animation: pulse 1.5s ease-in-out infinite;
      }

      /* Lớp phủ Chế độ Xem Chia đôi A/B */
      .split-view-divider {
        position: absolute;
        top: 0;
        bottom: 0;
        left: 50%;
        width: 2px;
        background: repeating-linear-gradient(
          to bottom,
          rgba(255, 255, 255, 0.4) 0px,
          rgba(255, 255, 255, 0.4) 6px,
          transparent 6px,
          transparent 12px
        );
        z-index: 15;
        pointer-events: none;
      }

      .split-view-label {
        position: absolute;
        top: 8px;
        z-index: 16;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 3px 8px;
        border-radius: 4px;
        pointer-events: none;
      }

      .split-view-label.left {
        left: 8px;
        background: rgba(0, 204, 136, 0.2);
        color: #00cc88;
      }

      .split-view-label.right {
        right: 8px;
        background: rgba(102, 126, 234, 0.2);
        color: #8ea4f0;
      }

      /* Lớp phủ modal huấn luyện */
      .training-panel-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
      }

      .training-panel-modal {
        background: #0d1117;
        border: 1px solid rgba(56, 68, 89, 0.6);
        border-radius: 12px;
        padding: 24px;
        min-width: 400px;
        max-width: 600px;
        max-height: 80vh;
        overflow-y: auto;
        color: #e0e0e0;
      }

      .training-panel-modal h3 {
        margin: 0 0 16px 0;
        font-size: 18px;
        color: #e0e0e0;
      }

      .training-panel-modal .close-btn {
        float: right;
        background: rgba(30, 40, 60, 0.8);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #8899aa;
        border-radius: 6px;
        padding: 4px 10px;
        cursor: pointer;
        font-size: 12px;
      }

      .training-panel-modal .close-btn:hover {
        background: rgba(50, 60, 80, 0.9);
        color: #c8d0dc;
      }
    `;
    
    if (!document.querySelector('#live-demo-enhanced-styles')) {
      style.id = 'live-demo-enhanced-styles';
      document.head.appendChild(style);
    }
  }

  initializePoseCanvas() {
    try {
      this.components.poseCanvas = new PoseDetectionCanvas('pose-detection-main', {
        width: 800,
        height: 600,
        autoResize: true,
        enableStats: true,
        enableControls: false, // Chúng ta sẽ xử lý điều khiển ở thành phần cha
        zoneId: this.state.currentZone
      });

      // Thiết lập các callback cho canvas
      this.components.poseCanvas.setCallback('onStateChange', (state) => {
        this.handleCanvasStateChange(state);
      });

      this.components.poseCanvas.setCallback('onPoseUpdate', (data) => {
        this.handlePoseUpdate(data);
      });

      this.components.poseCanvas.setCallback('onError', (error) => {
        this.handleCanvasError(error);
      });

      this.components.poseCanvas.setCallback('onConnectionChange', (state) => {
        this.handleConnectionStateChange(state);
      });

      this.logger.info('Đã khởi tạo canvas phát hiện tư thế');
    } catch (error) {
      this.logger.error('Không thể khởi tạo canvas tư thế', { error: error.message });
      throw error;
    }
  }

  setupEnhancedControls() {
    // Điều khiển chính
    const startBtn = this.container.querySelector('#start-enhanced-demo');
    const stopBtn = this.container.querySelector('#stop-enhanced-demo');
    const debugBtn = this.container.querySelector('#toggle-debug');
    const zoneSelector = this.container.querySelector('#zone-selector');

    if (startBtn) {
      startBtn.addEventListener('click', () => this.startDemo());
    }

    if (stopBtn) {
      stopBtn.addEventListener('click', () => this.stopDemo());
    }

    // Nút demo ngoại tuyến — chạy demo hoạt hình phía client (không cần server)
    const offlineDemoBtn = this.container.querySelector('#run-offline-demo');
    if (offlineDemoBtn) {
      offlineDemoBtn.addEventListener('click', () => {
        if (this.components.poseCanvas) {
          this.components.poseCanvas.toggleDemo();
        }
      });
    }

    if (debugBtn) {
      debugBtn.addEventListener('click', () => this.toggleDebugMode());
    }

    if (zoneSelector) {
      zoneSelector.addEventListener('change', (e) => this.changeZone(e.target.value));
      zoneSelector.value = this.state.currentZone;
    }

    // Điều khiển gỡ lỗi
    const forceReconnectBtn = this.container.querySelector('#force-reconnect');
    const clearErrorsBtn = this.container.querySelector('#clear-errors');
    const exportLogsBtn = this.container.querySelector('#export-logs');

    if (forceReconnectBtn) {
      forceReconnectBtn.addEventListener('click', () => this.forceReconnect());
    }

    if (clearErrorsBtn) {
      clearErrorsBtn.addEventListener('click', () => this.clearErrors());
    }

    if (exportLogsBtn) {
      exportLogsBtn.addEventListener('click', () => this.exportLogs());
    }

    // Điều khiển mô hình, huấn luyện và chế độ xem chia đôi
    this.setupModelTrainingControls();

    this.logger.debug('Đã thiết lập điều khiển nâng cao');
  }

  setupMonitoring() {
    // Thiết lập kiểm tra sức khỏe định kỳ
    if (this.config.enablePerformanceMonitoring) {
      this.healthCheckInterval = setInterval(() => {
        this.performHealthCheck();
      }, this.config.healthCheckInterval);
    }

    // Thiết lập cập nhật giao diện định kỳ
    this.uiUpdateInterval = setInterval(() => {
      this.updateMetricsDisplay();
    }, 1000);

    // Đăng ký dịch vụ cảm biến để theo dõi thay đổi nguồn dữ liệu
    this._sensingStateUnsub = sensingService.onStateChange(() => {
      this.updateSourceBanner();
      this.updateStatusIndicator();
    });
    // Giới hạn tốc độ cập nhật banner theo dữ liệu (khung hình đến ở 10Hz)
    let lastBannerUpdate = 0;
    this._sensingDataUnsub = sensingService.onData(() => {
      const now = Date.now();
      if (now - lastBannerUpdate > 2000) {
        lastBannerUpdate = now;
        this.updateSourceBanner();
      }
    });
    // Cập nhật banner ban đầu
    this.updateSourceBanner();

    this.logger.debug('Đã thiết lập giám sát');
  }

  // Xử lý sự kiện callback từ canvas
  handleCanvasStateChange(state) {
    this.state.isActive = state.isActive;
    this.updateUI();
    this.logger.debug('Trạng thái canvas đã thay đổi', { state });
  }

  handlePoseUpdate(data) {
    this.metrics.frameCount++;
    this.metrics.lastUpdate = Date.now();
    // Cập nhật chỉ báo nguồn tư thế nếu backend cung cấp
    if (data.pose_source && data.pose_source !== this.state.poseSource) {
      this.setState({ poseSource: data.pose_source });
    }
    this.updateDebugOutput(`Cập nhật tư thế: ${data.persons?.length || 0} người được phát hiện (${data.pose_source || 'không xác định'})`);
  }

  handleCanvasError(error) {
    this.metrics.errorCount++;
    this.logger.error('Lỗi canvas', { error: error.message });
    this.showError(`Lỗi canvas: ${error.message}`);
  }

  handleConnectionStateChange(state) {
    this.state.connectionState = state;
    this.updateUI();
    this.logger.debug('Trạng thái kết nối đã thay đổi', { state });
  }

  // Bắt đầu demo
  async startDemo() {
    if (this.state.isActive) {
      this.logger.warn('Demo đã đang hoạt động');
      return;
    }
    
    try {
      this.logger.info('Đang bắt đầu demo nâng cao');
      this.metrics.startTime = Date.now();
      this.metrics.frameCount = 0;
      this.metrics.errorCount = 0;
      this.metrics.connectionAttempts++;
      
      // Cập nhật trạng thái giao diện
      this.setState({ isActive: true, connectionState: 'connecting' });
      this.clearError();
      
      // Bắt đầu canvas phát hiện tư thế
      await this.components.poseCanvas.start();
      
      this.logger.info('Đã bắt đầu demo nâng cao thành công');
      this.updateDebugOutput('Đã bắt đầu demo thành công');
      
    } catch (error) {
      this.logger.error('Không thể bắt đầu demo nâng cao', { error: error.message });
      this.showError(`Không thể bắt đầu: ${error.message}`);
      this.setState({ isActive: false, connectionState: 'error' });
    }
  }

  // Dừng demo
  stopDemo() {
    if (!this.state.isActive) {
      this.logger.warn('Demo không hoạt động');
      return;
    }
    
    try {
      this.logger.info('Đang dừng demo nâng cao');

      // Dừng canvas phát hiện tư thế
      this.components.poseCanvas.stop();
      
      // Cập nhật trạng thái
      this.setState({ isActive: false, connectionState: 'disconnected' });
      this.clearError();

      this.logger.info('Đã dừng demo nâng cao thành công');
      this.updateDebugOutput('Đã dừng demo thành công');
      
    } catch (error) {
      this.logger.error('Lỗi khi dừng demo nâng cao', { error: error.message });
      this.showError(`Lỗi khi dừng: ${error.message}`);
    }
  }

  // Các phương thức điều khiển nâng cao
  toggleDebugMode() {
    this.state.debugMode = !this.state.debugMode;
    const debugPanel = this.container.querySelector('#debug-panel');
    const debugBtn = this.container.querySelector('#toggle-debug');
    
    if (debugPanel) {
      debugPanel.style.display = this.state.debugMode ? 'block' : 'none';
    }
    
    if (debugBtn) {
      debugBtn.textContent = this.state.debugMode ? 'Ẩn Gỡ lỗi' : 'Chế độ Gỡ lỗi';
      debugBtn.classList.toggle('active', this.state.debugMode);
    }
    
    this.logger.info('Đã chuyển đổi chế độ gỡ lỗi', { enabled: this.state.debugMode });
  }

  async changeZone(zoneId) {
    this.logger.info('Đang chuyển vùng', { from: this.state.currentZone, to: zoneId });
    this.state.currentZone = zoneId;
    
    // Cập nhật cấu hình canvas
    if (this.components.poseCanvas) {
      this.components.poseCanvas.updateConfig({ zoneId });
      
      // Khởi động lại nếu đang hoạt động
      if (this.state.isActive) {
        await this.components.poseCanvas.reconnect();
      }
    }
  }

  async forceReconnect() {
    if (!this.state.isActive) {
      this.showError('Không thể kết nối lại - demo không hoạt động');
      return;
    }
    
    try {
      this.logger.info('Đang buộc kết nối lại');
      await this.components.poseCanvas.reconnect();
      this.updateDebugOutput('Đã khởi tạo buộc kết nối lại');
    } catch (error) {
      this.logger.error('Buộc kết nối lại thất bại', { error: error.message });
      this.showError(`Kết nối lại thất bại: ${error.message}`);
    }
  }

  clearErrors() {
    this.metrics.errorCount = 0;
    this.clearError();
    poseService.clearValidationErrors();
    this.updateDebugOutput('Đã xóa lỗi');
    this.logger.info('Đã xóa lỗi');
  }

  exportLogs() {
    const logs = {
      timestamp: new Date().toISOString(),
      state: this.state,
      metrics: this.metrics,
      poseServiceMetrics: poseService.getPerformanceMetrics(),
      wsServiceStats: wsService.getAllConnectionStats(),
      canvasStats: this.components.poseCanvas?.getPerformanceMetrics()
    };
    
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pose-detection-logs-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    this.updateDebugOutput('Đã xuất nhật ký');
    this.logger.info('Đã xuất nhật ký');
  }

  // Quản lý trạng thái
  setState(newState) {
    this.state = { ...this.state, ...newState };
    this.updateUI();
  }

  updateUI() {
    this.updateStatusIndicator();
    this.updateControls();
    this.updateMetricsDisplay();
    this.updatePoseSourceIndicator();
  }

  updateStatusIndicator() {
    const indicator = this.container.querySelector('#demo-status-indicator');
    const text = this.container.querySelector('#demo-status-text');
    
    if (indicator) {
      indicator.className = `status-indicator ${this.getStatusClass()}`;
    }
    
    if (text) {
      text.textContent = this.getStatusText();
    }
  }

  getStatusClass() {
    if (!this.state.isActive) {
      return this.state.connectionState === 'error' ? 'error' : '';
    }
    const ds = sensingService.dataSource;
    if (ds === 'live') return 'active';
    if (ds === 'server-simulated') return 'sim';
    return 'connecting';
  }

  getStatusText() {
    if (!this.state.isActive) {
      return this.state.connectionState === 'error' ? 'Lỗi' : 'Sẵn sàng';
    }
    const ds = sensingService.dataSource;
    if (ds === 'live') return 'Hoạt động \u2014 ESP32 Trực tiếp';
    if (ds === 'server-simulated') return 'Hoạt động \u2014 Dữ liệu Mô phỏng';
    if (ds === 'simulated') return 'Hoạt động \u2014 Mô phỏng Ngoại tuyến';
    return 'Đang kết nối...';
  }

  /** Cập nhật banner nguồn dữ liệu nổi bật ở đầu Demo Trực tiếp. */
  updateSourceBanner() {
    const banner = this.container.querySelector('#demo-source-banner');
    if (!banner) return;
    const ds = sensingService.dataSource;
    const config = {
      'live':             { text: 'TRỰC TIẾP \u2014 Phần cứng ESP32 Đã kết nối',           cls: 'demo-source-live' },
      'server-simulated': { text: 'DỮ LIỆU MÔ PHỎNG \u2014 Không phát hiện Phần cứng',     cls: 'demo-source-sim' },
      'reconnecting':     { text: 'ĐANG KẾT NỐI LẠI VỚI MÁY CHỦ...',                      cls: 'demo-source-reconnecting' },
      'simulated':        { text: 'NGOẠI TUYẾN \u2014 Máy chủ Không thể kết nối, Mô phỏng Cục bộ',   cls: 'demo-source-offline' },
    };
    const cfg = config[ds] || config['reconnecting'];
    banner.textContent = cfg.text;
    banner.className = 'demo-source-banner ' + cfg.cls;
  }

  updateControls() {
    const startBtn = this.container.querySelector('#start-enhanced-demo');
    const stopBtn = this.container.querySelector('#stop-enhanced-demo');
    const zoneSelector = this.container.querySelector('#zone-selector');
    
    if (startBtn) {
      startBtn.disabled = this.state.isActive;
    }
    
    if (stopBtn) {
      stopBtn.disabled = !this.state.isActive;
    }
    
    if (zoneSelector) {
      zoneSelector.disabled = this.state.isActive;
    }
  }

  updateMetricsDisplay() {
    const elements = {
      connectionStatus: this.container.querySelector('#connection-status'),
      frameCount: this.container.querySelector('#frame-count'),
      uptime: this.container.querySelector('#uptime'),
      errorCount: this.container.querySelector('#error-count'),
      lastUpdate: this.container.querySelector('#last-update')
    };

    if (elements.connectionStatus) {
      const ds = sensingService.dataSource;
      const dsLabels = {
        'live':              'Đã kết nối \u2014 ESP32',
        'server-simulated':  'Đã kết nối \u2014 Mô phỏng',
        'reconnecting':      'Đang kết nối lại...',
        'simulated':         'Ngoại tuyến \u2014 Mô phỏng',
      };
      const label = dsLabels[ds] || this.state.connectionState;
      elements.connectionStatus.textContent = label;
      const cls = ds === 'live' ? 'good'
        : ds === 'server-simulated' ? 'sim'
        : ds === 'simulated' ? 'bad'
        : this.getHealthClass(this.state.connectionState);
      elements.connectionStatus.className = `health-${cls}`;
    }

    if (elements.frameCount) {
      elements.frameCount.textContent = this.metrics.frameCount;
    }

    if (elements.uptime) {
      const uptime = this.metrics.startTime ? 
        Math.round((Date.now() - this.metrics.startTime) / 1000) : 0;
      elements.uptime.textContent = `${uptime}s`;
    }

    if (elements.errorCount) {
      elements.errorCount.textContent = this.metrics.errorCount;
      elements.errorCount.className = this.metrics.errorCount > 0 ? 'health-bad' : 'health-good';
    }

    if (elements.lastUpdate) {
      const lastUpdate = this.metrics.lastUpdate ? 
        new Date(this.metrics.lastUpdate).toLocaleTimeString() : 'Chưa bao giờ';
      elements.lastUpdate.textContent = lastUpdate;
    }
  }

  updatePoseSourceIndicator() {
    const badge = this.container.querySelector('#pose-source-badge');
    const description = this.container.querySelector('#pose-source-description');

    if (!badge || !description) return;

    const source = this.state.poseSource;

    if (source === 'model_inference') {
      badge.className = 'pose-source-badge pose-source-model';
      badge.textContent = 'Suy luận Mô hình';
      description.textContent =
        'Tư thế được ước tính bởi mạng nơ-ron đã huấn luyện ' +
        'được tải từ container RVF.';
    } else if (source === 'signal_derived') {
      badge.className = 'pose-source-badge pose-source-signal';
      badge.textContent = 'Trích xuất từ Tín hiệu';
      description.textContent =
        'Các điểm khớp được trích xuất từ đặc trưng tín hiệu CSI trực tiếp ' +
        '(công suất chuyển động, nhịp thở, phương sai).';
    } else {
      badge.className = 'pose-source-badge pose-source-unknown';
      badge.textContent = 'Không xác định';
      description.textContent = 'Đang chờ khung hình đầu tiên...';
    }
  }

  getHealthClass(status) {
    switch (status) {
      case 'connected': return 'good';
      case 'connecting': return 'poor';
      case 'error': return 'bad';
      default: return 'unknown';
    }
  }

  async performHealthCheck() {
    try {
      // Kiểm tra sức khỏe dịch vụ tư thế
      const poseHealth = await poseService.healthCheck();
      this.updateHealthDisplay('pose-service-health', poseHealth.healthy);

      // Kiểm tra sức khỏe WebSocket
      const wsStats = wsService.getAllConnectionStats();
      const wsHealthy = wsStats.connections.some(conn => conn.status === 'connected');
      this.updateHealthDisplay('websocket-health', wsHealthy);

      // Kiểm tra sức khỏe API (đơn giản hoá)
      this.updateHealthDisplay('api-health', poseHealth.apiHealthy);

    } catch (error) {
      this.logger.error('Kiểm tra sức khỏe thất bại', { error: error.message });
    }
  }

  updateHealthDisplay(elementId, isHealthy) {
    const element = this.container.querySelector(`#${elementId}`);
    if (element) {
      element.textContent = isHealthy ? 'Tốt' : 'Kém';
      element.className = isHealthy ? 'health-good' : 'health-poor';
    }
  }

  updateDebugOutput(message) {
    if (!this.state.debugMode) return;
    
    const debugOutput = this.container.querySelector('#debug-output');
    if (debugOutput) {
      const timestamp = new Date().toLocaleTimeString();
      const newLine = `[${timestamp}] ${message}\n`;
      debugOutput.value = (debugOutput.value + newLine).split('\n').slice(-50).join('\n');
      debugOutput.scrollTop = debugOutput.scrollHeight;
    }
  }

  showError(message) {
    const errorDisplay = this.container.querySelector('#error-display');
    if (errorDisplay) {
      errorDisplay.textContent = message;
      errorDisplay.style.display = 'block';
    }
    
    // Tự động ẩn sau 10 giây
    setTimeout(() => this.clearError(), 10000);
  }

  clearError() {
    const errorDisplay = this.container.querySelector('#error-display');
    if (errorDisplay) {
      errorDisplay.style.display = 'none';
    }
  }

  // --- Các phương thức Điều khiển Mô hình ---

  async fetchModels() {
    if (!modelService) return;
    try {
      const data = await modelService.listModels();
      this.modelState.models = data?.models || [];
      this.populateModelSelector();
      // Kiểm tra xem mô hình đã hoạt động chưa
      const active = await modelService.getActiveModel();
      if (active && active.model_id) {
        this.modelState.activeModelId = active.model_id;
        this.modelState.activeModelInfo = active;
        this.updateModelUI();
      }
    } catch (error) {
      this.logger.warn('Không thể tải danh sách mô hình', { error: error.message });
    }
  }

  populateModelSelector() {
    const selector = this.container.querySelector('#model-selector');
    if (!selector) return;
    // Giữ lại tùy chọn "Trích xuất từ Tín hiệu" đầu tiên
    selector.innerHTML = '<option value="">Trích xuất từ Tín hiệu (không có mô hình)</option>';
    this.modelState.models.forEach(model => {
      const opt = document.createElement('option');
      opt.value = model.id || model.model_id || model.name;
      opt.textContent = model.name || model.id || 'Mô hình Không xác định';
      selector.appendChild(opt);
    });
    if (this.modelState.activeModelId) {
      selector.value = this.modelState.activeModelId;
    }
  }

  async handleLoadModel() {
    if (!modelService) return;
    const selector = this.container.querySelector('#model-selector');
    const modelId = selector?.value;
    if (!modelId) {
      this.setModelStatus('Hãy chọn mô hình trước');
      return;
    }
    try {
      this.modelState.loading = true;
      this.setModelStatus('Đang tải...');
      const loadBtn = this.container.querySelector('#load-model-btn');
      if (loadBtn) loadBtn.disabled = true;

      await modelService.loadModel(modelId);
      this.modelState.activeModelId = modelId;

      // Thử lấy thông tin đầy đủ
      try {
        const info = await modelService.getModel(modelId);
        this.modelState.activeModelInfo = info;
      } catch (e) {
        this.modelState.activeModelInfo = { model_id: modelId };
      }

      // Lấy danh sách hồ sơ LoRA
      try {
        const profiles = await modelService.getLoraProfiles();
        this.modelState.loraProfiles = profiles || [];
      } catch (e) {
        this.modelState.loraProfiles = [];
      }

      this.modelState.loading = false;
      this.updateModelUI();
      this.updateSplitViewAvailability();

      // Cập nhật badge nguồn tư thế thành suy luận mô hình
      this.setState({ poseSource: 'model_inference' });

    } catch (error) {
      this.modelState.loading = false;
      this.setModelStatus(`Lỗi: ${error.message}`);
      const loadBtn = this.container.querySelector('#load-model-btn');
      if (loadBtn) loadBtn.disabled = false;
      this.logger.error('Không thể tải mô hình', { error: error.message });
    }
  }

  async handleUnloadModel() {
    if (!modelService) return;
    try {
      await modelService.unloadModel();
      this.modelState.activeModelId = null;
      this.modelState.activeModelInfo = null;
      this.modelState.loraProfiles = [];
      this.modelState.selectedLoraProfile = null;
      this.updateModelUI();
      this.updateSplitViewAvailability();
      this.disableSplitView();
      this.setState({ poseSource: 'signal_derived' });
    } catch (error) {
      this.setModelStatus(`Lỗi: ${error.message}`);
      this.logger.error('Không thể gỡ tải mô hình', { error: error.message });
    }
  }

  async handleLoraProfileChange(profileName) {
    if (!modelService || !this.modelState.activeModelId) return;
    if (!profileName) return;
    try {
      await modelService.activateLoraProfile(this.modelState.activeModelId, profileName);
      this.modelState.selectedLoraProfile = profileName;
      this.setModelStatus(`LoRA: ${profileName} đang hoạt động`);
    } catch (error) {
      this.setModelStatus(`Lỗi LoRA: ${error.message}`);
    }
  }

  updateModelUI() {
    const loadBtn = this.container.querySelector('#load-model-btn');
    const unloadBtn = this.container.querySelector('#unload-model-btn');
    const infoRow = this.container.querySelector('#model-active-info');
    const nameEl = this.container.querySelector('#model-active-name');
    const pckEl = this.container.querySelector('#model-active-pck');
    const loraRow = this.container.querySelector('#lora-profile-row');
    const loraSel = this.container.querySelector('#lora-profile-selector');

    const isLoaded = !!this.modelState.activeModelId;

    if (loadBtn) loadBtn.disabled = isLoaded;
    if (unloadBtn) unloadBtn.disabled = !isLoaded;

    if (infoRow) {
      infoRow.style.display = isLoaded ? 'flex' : 'none';
    }

    if (isLoaded && this.modelState.activeModelInfo) {
      const info = this.modelState.activeModelInfo;
      const name = info.name || info.model_id || this.modelState.activeModelId;
      const version = info.version ? ` v${info.version}` : '';
      const pck = info.pck_score != null ? info.pck_score.toFixed(2) : '--';
      if (nameEl) nameEl.textContent = `${name}${version}`;
      if (pckEl) pckEl.textContent = `PCK: ${pck}`;
      this.setModelStatus(`Mô hình: ${name} (PCK: ${pck})`);
    } else if (!isLoaded) {
      this.setModelStatus('Chưa tải mô hình');
    }

    // Hồ sơ LoRA
    if (loraRow && loraSel) {
      if (isLoaded && this.modelState.loraProfiles.length > 0) {
        loraRow.style.display = 'flex';
        loraSel.innerHTML = '<option value="">Không</option>';
        this.modelState.loraProfiles.forEach(profile => {
          const opt = document.createElement('option');
          opt.value = profile.name || profile;
          opt.textContent = profile.name || profile;
          loraSel.appendChild(opt);
        });
      } else {
        loraRow.style.display = 'none';
      }
    }
  }

  setModelStatus(text) {
    const el = this.container.querySelector('#model-status-text');
    if (el) el.textContent = text;
  }

  // --- Các phương thức Chế độ xem A/B Chia đôi ---

  updateSplitViewAvailability() {
    const toggle = this.container.querySelector('#split-view-toggle');
    if (toggle) {
      toggle.disabled = !this.modelState.activeModelId;
    }
  }

  toggleSplitView() {
    if (!this.modelState.activeModelId) return;
    this.splitViewActive = !this.splitViewActive;
    const toggle = this.container.querySelector('#split-view-toggle');
    if (toggle) {
      toggle.textContent = this.splitViewActive ? 'Bật' : 'Tắt';
      toggle.classList.toggle('active', this.splitViewActive);
    }
    this.updateSplitViewOverlay();
  }

  disableSplitView() {
    this.splitViewActive = false;
    const toggle = this.container.querySelector('#split-view-toggle');
    if (toggle) {
      toggle.textContent = 'Tắt';
      toggle.classList.remove('active');
    }
    this.updateSplitViewOverlay();
  }

  updateSplitViewOverlay() {
    const mainContainer = this.container.querySelector('.pose-detection-container');
    if (!mainContainer) return;

    // Xóa lớp phủ hiện có
    mainContainer.querySelectorAll('.split-view-divider, .split-view-label').forEach(el => el.remove());

    if (this.splitViewActive) {
      const divider = document.createElement('div');
      divider.className = 'split-view-divider';
      mainContainer.appendChild(divider);

      const leftLabel = document.createElement('div');
      leftLabel.className = 'split-view-label left';
      leftLabel.textContent = 'Trích xuất từ Tín hiệu';
      mainContainer.appendChild(leftLabel);

      const rightLabel = document.createElement('div');
      rightLabel.className = 'split-view-label right';
      rightLabel.textContent = 'Suy luận Mô hình';
      mainContainer.appendChild(rightLabel);
    }
  }

  // --- Các phương thức Bảng Huấn luyện Nhanh ---

  updateTrainingStatus() {
    const badge = this.container.querySelector('#training-status-badge');
    if (!badge) return;

    const state = this.trainingState.status;
    badge.classList.remove('training', 'recording');

    if (state === 'training') {
      badge.classList.add('training');
      badge.textContent = `Đang huấn luyện epoch ${this.trainingState.epoch}/${this.trainingState.totalEpochs}`;
    } else if (state === 'recording') {
      badge.classList.add('recording');
      badge.textContent = 'Đang thu...';
    } else {
      badge.textContent = 'Chờ';
    }
  }

  async handleQuickRecord() {
    if (!trainingService) {
      this.logger.warn('Dịch vụ huấn luyện không khả dụng');
      return;
    }
    try {
      await trainingService.startRecording({ session_name: `quick_${Date.now()}`, duration_secs: 60 });
      this.trainingState.status = 'recording';
      this.updateTrainingStatus();
      // Tự động đặt lại sau ~65 giây
      setTimeout(() => {
        if (this.trainingState.status === 'recording') {
          this.trainingState.status = 'idle';
          this.updateTrainingStatus();
        }
      }, 65000);
    } catch (error) {
      this.logger.error('Thu nhanh thất bại', { error: error.message });
    }
  }

  showTrainingPanel() {
    // Tạo lớp phủ modal đơn giản cho bảng huấn luyện
    const existing = document.querySelector('.training-panel-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'training-panel-overlay';
    overlay.innerHTML = `
      <div class="training-panel-modal">
        <button class="close-btn" id="close-training-modal">Đóng</button>
        <h3>Bảng Huấn luyện</h3>
        <p style="color: #8899aa; font-size: 13px; margin-bottom: 16px;">
          Cấu hình và bắt đầu huấn luyện mô hình từ đây. Kết nối tới API huấn luyện backend để quản lý epoch, tập dữ liệu và checkpoint.
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div class="setting-row-ld">
            <label class="ld-label" style="flex: 1;">Trạng thái:</label>
            <span style="color: #c8d0dc; font-size: 12px;">${this.trainingState.status}</span>
          </div>
          <div class="setting-row-ld">
            <label class="ld-label" style="flex: 1;">Dịch vụ huấn luyện:</label>
            <span style="color: ${trainingService ? '#00cc88' : '#ef4444'}; font-size: 12px;">${trainingService ? 'Đã kết nối' : 'Không khả dụng'}</span>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Xử lý đóng
    overlay.querySelector('#close-training-modal').addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.remove();
    });
  }

  // --- Lắng nghe Sự kiện Dịch vụ ---

  setupServiceListeners() {
    if (modelService) {
      const unsub1 = modelService.on('model-loaded', (data) => {
        this.logger.info('Sự kiện mô hình đã tải', data);
      });
      const unsub2 = modelService.on('model-unloaded', () => {
        this.modelState.activeModelId = null;
        this.modelState.activeModelInfo = null;
        this.updateModelUI();
        this.disableSplitView();
      });
      this.subscriptions.push(unsub1, unsub2);
    }

    if (trainingService) {
      const unsub3 = trainingService.on('progress', (data) => {
        if (data && data.epoch != null) {
          this.trainingState.epoch = data.epoch;
          this.trainingState.totalEpochs = data.total_epochs || data.totalEpochs || this.trainingState.totalEpochs;
          this.trainingState.status = 'training';
          this.updateTrainingStatus();
        }
      });
      const unsub4 = trainingService.on('training-stopped', () => {
        this.trainingState.status = 'idle';
        this.updateTrainingStatus();
      });
      this.subscriptions.push(unsub3, unsub4);
    }
  }

  // --- Thiết lập Điều khiển Nâng cao ---

  setupModelTrainingControls() {
    // Nút điều khiển mô hình
    const loadBtn = this.container.querySelector('#load-model-btn');
    const unloadBtn = this.container.querySelector('#unload-model-btn');
    const loraSel = this.container.querySelector('#lora-profile-selector');
    const splitToggle = this.container.querySelector('#split-view-toggle');
    const openTrainingBtn = this.container.querySelector('#open-training-panel-btn');
    const quickRecordBtn = this.container.querySelector('#quick-record-btn');

    if (loadBtn) loadBtn.addEventListener('click', () => this.handleLoadModel());
    if (unloadBtn) unloadBtn.addEventListener('click', () => this.handleUnloadModel());
    if (loraSel) loraSel.addEventListener('change', (e) => this.handleLoraProfileChange(e.target.value));
    if (splitToggle) splitToggle.addEventListener('click', () => this.toggleSplitView());
    if (openTrainingBtn) openTrainingBtn.addEventListener('click', () => this.showTrainingPanel());
    if (quickRecordBtn) quickRecordBtn.addEventListener('click', () => this.handleQuickRecord());
  }

  // Dọn dẹp
  dispose() {
    try {
      this.logger.info('Đang huỷ thành phần LiveDemoTab');

      // Dừng demo nếu đang chạy
      if (this.state.isActive) {
        this.stopDemo();
      }
      
      // Xóa các bộ đếm thời gian
      if (this.healthCheckInterval) {
        clearInterval(this.healthCheckInterval);
      }
      
      if (this.uiUpdateInterval) {
        clearInterval(this.uiUpdateInterval);
      }
      
      // Huỷ thành phần canvas
      if (this.components.poseCanvas) {
        this.components.poseCanvas.dispose();
      }
      
      // Huỷ đăng ký dịch vụ
      this.subscriptions.forEach(unsubscribe => unsubscribe());
      this.subscriptions = [];
      if (this._sensingStateUnsub) this._sensingStateUnsub();
      if (this._sensingDataUnsub) this._sensingDataUnsub();
      if (this._autoStartUnsub) this._autoStartUnsub();
      
      this.logger.info('Đã huỷ thành phần LiveDemoTab thành công');
    } catch (error) {
      this.logger.error('Lỗi khi huỷ', { error: error.message });
    }
  }
}