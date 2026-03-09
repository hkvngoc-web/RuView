// Thành phần PoseDetectionCanvas cho WiFi-DensePose UI

import { PoseRenderer } from '../utils/pose-renderer.js';
import { poseService } from '../services/pose.service.js';
import { SettingsPanel } from './SettingsPanel.js';

export class PoseDetectionCanvas {
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    
    if (!this.container) {
      throw new Error(`Không tìm thấy container với ID '${containerId}'`);
    }

    this.config = {
      width: 800,
      height: 600,
      autoResize: true,
      enableStats: true,
      enableControls: true,
      zoneId: 'zone_1',
      updateInterval: 50, // ms
      ...options
    };

    this.state = {
      isActive: false,
      connectionState: 'disconnected',
      lastPoseData: null,
      errorMessage: null,
      frameCount: 0,
      startTime: Date.now()
    };

    this.callbacks = {
      onStateChange: null,
      onPoseUpdate: null,
      onError: null,
      onConnectionChange: null
    };

    this.logger = this.createLogger();
    this.unsubscribeFunctions = [];
    
    // Khởi tạo bảng cài đặt
    this.settingsPanel = null;

    // Trạng thái vệt tư thế
    this.poseTrail = [];
    this.showTrail = false;
    this.maxTrailLength = 10;

    // Khởi tạo thành phần
    this.initializeComponent();
  }

  createLogger() {
    return {
      debug: (...args) => console.debug('[CANVAS-DEBUG]', new Date().toISOString(), ...args),
      info: (...args) => console.info('[CANVAS-INFO]', new Date().toISOString(), ...args),
      warn: (...args) => console.warn('[CANVAS-WARN]', new Date().toISOString(), ...args),
      error: (...args) => console.error('[CANVAS-ERROR]', new Date().toISOString(), ...args)
    };
  }

  initializeComponent() {
    this.logger.info('Đang khởi tạo thành phần PoseDetectionCanvas', { containerId: this.containerId });

    // Tạo cấu trúc DOM
    this.createDOMStructure();

    // Khởi tạo canvas và bộ kết xuất
    this.initializeCanvas();

    // Thiết lập bộ xử lý sự kiện
    this.setupEventHandlers();

    // Thiết lập đăng ký dịch vụ tư thế
    this.setupPoseServiceSubscription();

    this.logger.info('Thành phần PoseDetectionCanvas đã khởi tạo thành công');
  }

  createDOMStructure() {
    this.container.innerHTML = `
      <div class="pose-detection-canvas-wrapper">
        <div class="pose-canvas-header">
          <div class="pose-canvas-title">
            <h3>Phát hiện Tư thế Con người</h3>
            <div class="connection-status">
              <span class="status-indicator" id="status-indicator-${this.containerId}"></span>
              <span class="status-text" id="status-text-${this.containerId}">Ngắt kết nối</span>
            </div>
          </div>
          <div class="pose-canvas-controls" id="controls-${this.containerId}" ${!this.config.enableControls ? 'style="display:none"' : ''}>
            <button class="btn btn-start" id="start-btn-${this.containerId}">&#9654; Bắt đầu</button>
            <button class="btn btn-stop" id="stop-btn-${this.containerId}" disabled>&#9632; Dừng</button>
            <button class="btn btn-reconnect" id="reconnect-btn-${this.containerId}" disabled>&#8635; Kết nối lại</button>
            <button class="btn btn-demo" id="demo-btn-${this.containerId}">&#9881; Demo</button>
            <select class="mode-select" id="mode-select-${this.containerId}">
              <option value="skeleton">Bộ xương</option>
              <option value="keypoints">Điểm khớp</option>
              <option value="heatmap">Bản đồ nhiệt</option>
              <option value="dense">Dày đặc</option>
            </select>
            <button class="btn btn-trail" id="trail-btn-${this.containerId}">&#9676; Vệt</button>
            <button class="btn btn-settings" id="settings-btn-${this.containerId}">&#9881; Cài đặt</button>
          </div>
        </div>
        <div class="pose-canvas-container">
          <canvas id="pose-canvas-${this.containerId}" class="pose-canvas"></canvas>
          <div class="pose-canvas-overlay" id="overlay-${this.containerId}">
            <div class="pose-stats" id="stats-${this.containerId}"></div>
            <div class="pose-error" id="error-${this.containerId}" style="display: none;"></div>
          </div>
        </div>
      </div>
    `;

    // Thêm kiểu CSS
    this.addComponentStyles();
  }

  addComponentStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .pose-detection-canvas-wrapper {
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 8px;
        overflow: hidden;
        background: #0d1117;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }

      .pose-canvas-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        background: rgba(15, 20, 35, 0.95);
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }

      .pose-canvas-title {
        display: flex;
        align-items: center;
        gap: 15px;
      }

      .pose-canvas-title h3 {
        margin: 0;
        color: #e0e0e0;
        font-size: 16px;
        font-weight: 600;
      }

      .connection-status {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        background: rgba(30, 40, 60, 0.6);
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.06);
      }

      .status-indicator {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #4a5568;
        transition: background-color 0.3s;
      }

      .status-indicator.connected { background: #00cc88; box-shadow: 0 0 6px rgba(0, 204, 136, 0.5); }
      .status-indicator.connecting { background: #fbbf24; box-shadow: 0 0 6px rgba(251, 191, 36, 0.5); animation: pulse 1.5s ease-in-out infinite; }
      .status-indicator.error { background: #ef4444; box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
      .status-indicator.disconnected { background: #4a5568; }

      .status-text {
        font-size: 11px;
        color: #8899aa;
        min-width: 70px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 500;
      }

      .pose-canvas-controls {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: nowrap;
      }

      .btn {
        padding: 8px 16px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        background: rgba(30, 40, 60, 0.8);
        color: #c8d0dc;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        transition: all 0.2s ease;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        min-width: 80px;
        justify-content: center;
      }

      .btn:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
      }

      .btn:active:not(:disabled) {
        transform: translateY(0);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
      }

      .btn:disabled {
        opacity: 0.35;
        cursor: not-allowed;
        background: rgba(20, 30, 50, 0.6);
        color: #4a5568;
        transform: none !important;
        box-shadow: none !important;
      }

      .btn-start {
        background: rgba(0, 204, 136, 0.15);
        color: #00cc88;
        border-color: rgba(0, 204, 136, 0.3);
      }

      .btn-start:hover:not(:disabled) {
        background: rgba(0, 204, 136, 0.25);
        border-color: rgba(0, 204, 136, 0.5);
        box-shadow: 0 4px 12px rgba(0, 204, 136, 0.2);
      }

      .btn-stop {
        background: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border-color: rgba(239, 68, 68, 0.3);
      }

      .btn-stop:hover:not(:disabled) {
        background: rgba(239, 68, 68, 0.25);
        border-color: rgba(239, 68, 68, 0.5);
        box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
      }

      .btn-reconnect {
        background: rgba(59, 130, 246, 0.15);
        color: #60a5fa;
        border-color: rgba(59, 130, 246, 0.3);
      }

      .btn-reconnect:hover:not(:disabled) {
        background: rgba(59, 130, 246, 0.25);
        border-color: rgba(59, 130, 246, 0.5);
        box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
      }

      .btn-demo {
        background: rgba(139, 92, 246, 0.15);
        color: #a78bfa;
        border-color: rgba(139, 92, 246, 0.3);
      }

      .btn-demo:hover:not(:disabled) {
        background: rgba(139, 92, 246, 0.25);
        border-color: rgba(139, 92, 246, 0.5);
        box-shadow: 0 4px 12px rgba(139, 92, 246, 0.2);
      }

      .btn-settings {
        background: rgba(100, 116, 139, 0.15);
        color: #94a3b8;
        border-color: rgba(100, 116, 139, 0.3);
      }

      .btn-settings:hover:not(:disabled) {
        background: rgba(100, 116, 139, 0.25);
        border-color: rgba(100, 116, 139, 0.5);
      }

      .btn-trail {
        background: rgba(0, 212, 255, 0.1);
        color: #5ec4d4;
        border-color: rgba(0, 212, 255, 0.25);
      }

      .btn-trail:hover:not(:disabled) {
        background: rgba(0, 212, 255, 0.2);
        border-color: rgba(0, 212, 255, 0.45);
        box-shadow: 0 4px 12px rgba(0, 212, 255, 0.15);
      }

      .btn-trail.active {
        background: rgba(0, 212, 255, 0.2);
        color: #00d4ff;
        border-color: rgba(0, 212, 255, 0.5);
        box-shadow: 0 0 8px rgba(0, 212, 255, 0.2);
      }

      .mode-select {
        padding: 8px 12px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 8px;
        background: rgba(30, 40, 60, 0.8);
        color: #b0b8c8;
        font-size: 13px;
        cursor: pointer;
      }

      .mode-select:focus {
        outline: none;
        border-color: rgba(139, 92, 246, 0.5);
        box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.15);
      }

      .mode-select option {
        background: #1a2234;
        color: #c8d0dc;
      }

      .pose-canvas-container {
        position: relative;
        background: #000;
      }

      .pose-canvas {
        display: block;
        width: 100%;
        height: auto;
        background: #000;
      }

      .pose-canvas-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        pointer-events: none;
        z-index: 10;
      }

      .pose-stats {
        position: absolute;
        top: 10px;
        right: 10px;
        background: rgba(0, 0, 0, 0.7);
        color: white;
        padding: 8px;
        border-radius: 4px;
        font-size: 11px;
        line-height: 1.4;
        font-family: monospace;
        max-width: 200px;
      }

      .pose-error {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(220, 53, 69, 0.9);
        color: white;
        padding: 15px;
        border-radius: 4px;
        font-size: 14px;
        text-align: center;
        max-width: 80%;
      }
    `;
    
    if (!document.querySelector('#pose-canvas-styles')) {
      style.id = 'pose-canvas-styles';
      document.head.appendChild(style);
    }
  }

  initializeCanvas() {
    this.canvas = document.getElementById(`pose-canvas-${this.containerId}`);
    this.canvas.width = this.config.width;
    this.canvas.height = this.config.height;

    // Khởi tạo bộ kết xuất
    this.renderer = new PoseRenderer(this.canvas, {
      showDebugInfo: this.config.enableStats,
      mode: 'skeleton'
    });

    this.logger.debug('Canvas và bộ kết xuất đã khởi tạo', { 
      width: this.config.width, 
      height: this.config.height 
    });

    // Xử lý tự động thay đổi kích thước
    if (this.config.autoResize) {
      this.setupAutoResize();
    }
  }

  setupAutoResize() {
    const resizeObserver = new ResizeObserver(entries => {
      const entry = entries[0];
      const { width } = entry.contentRect;
      const height = Math.round(width * 0.75); // 4:3 aspect ratio
      
      this.renderer.resize(width, height);
      this.logger.debug('Canvas đã tự động thay đổi kích thước', { width, height });
    });

    resizeObserver.observe(this.container);
    this.resizeObserver = resizeObserver;
  }

  setupEventHandlers() {
    // Nút bắt đầu
    const startBtn = document.getElementById(`start-btn-${this.containerId}`);
    startBtn.addEventListener('click', () => this.start());

    // Nút dừng
    const stopBtn = document.getElementById(`stop-btn-${this.containerId}`);
    stopBtn.addEventListener('click', () => this.stop());

    // Nút kết nối lại
    const reconnectBtn = document.getElementById(`reconnect-btn-${this.containerId}`);
    reconnectBtn.addEventListener('click', () => this.reconnect());

    // Nút demo
    const demoBtn = document.getElementById(`demo-btn-${this.containerId}`);
    demoBtn.addEventListener('click', () => this.toggleDemo());

    // Nút bật/tắt vệt
    const trailBtn = document.getElementById(`trail-btn-${this.containerId}`);
    trailBtn.addEventListener('click', () => this.toggleTrail());

    // Nút cài đặt
    const settingsBtn = document.getElementById(`settings-btn-${this.containerId}`);
    settingsBtn.addEventListener('click', () => this.showSettings());

    // Bộ chọn chế độ
    const modeSelect = document.getElementById(`mode-select-${this.containerId}`);
    modeSelect.addEventListener('change', (event) => {
      this.setRenderMode(event.target.value);
    });

    this.logger.debug('Đã thiết lập bộ xử lý sự kiện');
  }

  setupPoseServiceSubscription() {
    // Đăng ký cập nhật tư thế
    const unsubscribePose = poseService.subscribeToPoseUpdates((update) => {
      this.handlePoseUpdate(update);
    });

    this.unsubscribeFunctions.push(unsubscribePose);
    this.logger.debug('Đã thiết lập đăng ký dịch vụ tư thế');
  }

  handlePoseUpdate(update) {
    try {
      switch (update.type) {
        case 'pose_update':
          this.state.lastPoseData = update.data;
          this.state.frameCount++;
          this.updateTrail(update.data);
          this.renderPoseData(update.data);
          this.updateStats();
          this.notifyCallback('onPoseUpdate', update.data);
          break;

        case 'connected':
          this.setConnectionState('connected');
          this.clearError();
          break;

        case 'disconnected':
          this.setConnectionState('disconnected');
          break;

        case 'connecting':
          this.setConnectionState('connecting');
          break;

        case 'connection_state':
          this.setConnectionState(update.state);
          break;

        case 'error':
          this.setConnectionState('error');
          this.showError(update.error?.message || 'Lỗi kết nối');
          this.notifyCallback('onError', update.error);
          break;

        default:
          this.logger.debug('Loại cập nhật tư thế chưa xử lý', { type: update.type });
      }
    } catch (error) {
      this.logger.error('Lỗi xử lý cập nhật tư thế', { error: error.message, update });
      this.showError(`Lỗi cập nhật: ${error.message}`);
    }
  }

  renderPoseData(poseData) {
    if (!this.renderer || !this.state.isActive) {
      return;
    }

    try {
      // Kết xuất vệt trước khung hình hiện tại nếu được bật
      if (this.showTrail && this.poseTrail.length > 1) {
        // Bộ kết xuất renderer.render() xóa canvas, nên chúng ta kết xuất vệt
        // bằng cách can thiệp vào ngữ cảnh canvas của bộ kết xuất sau khi xóa.
        // Chúng ta ghi đè luồng kết xuất: xóa, vệt, rồi hiện tại.
        this.renderer.clearCanvas();
        this.renderTrail(this.renderer.ctx);
        // Bây giờ kết xuất khung hình hiện tại mà không xóa lại
        this.renderCurrentFrameNoClean(poseData);
      } else {
        this.renderer.render(poseData, {
          frameCount: this.state.frameCount,
          connectionState: this.state.connectionState
        });
      }
    } catch (error) {
      this.logger.error('Lỗi kết xuất', { error: error.message });
      this.showError(`Lỗi kết xuất: ${error.message}`);
    }
  }

  renderCurrentFrameNoClean(poseData) {
    // Gọi logic kết xuất của bộ kết xuất mà không xóa canvas.
    // Chúng ta tạm thời thay thế clearCanvas, kết xuất, rồi khôi phục.
    const origClear = this.renderer.clearCanvas.bind(this.renderer);
    this.renderer.clearCanvas = () => {}; // no-op
    try {
      this.renderer.render(poseData, {
        frameCount: this.state.frameCount,
        connectionState: this.state.connectionState
      });
    } finally {
      this.renderer.clearCanvas = origClear;
    }
  }

  setConnectionState(state) {
    if (this.state.connectionState !== state) {
      this.logger.debug('Trạng thái kết nối đã thay đổi', { from: this.state.connectionState, to: state });
      this.state.connectionState = state;
      this.updateConnectionIndicator();
      this.updateControls();
      this.notifyCallback('onConnectionChange', state);
    }
  }

  updateConnectionIndicator() {
    const indicator = document.getElementById(`status-indicator-${this.containerId}`);
    const text = document.getElementById(`status-text-${this.containerId}`);

    if (indicator && text) {
      indicator.className = `status-indicator ${this.state.connectionState}`;
      text.textContent = this.state.connectionState.charAt(0).toUpperCase() + 
                        this.state.connectionState.slice(1);
    }
  }

  updateControls() {
    const startBtn = document.getElementById(`start-btn-${this.containerId}`);
    const stopBtn = document.getElementById(`stop-btn-${this.containerId}`);
    const reconnectBtn = document.getElementById(`reconnect-btn-${this.containerId}`);

    if (startBtn && stopBtn && reconnectBtn) {
      const isConnected = this.state.connectionState === 'connected';
      const isActive = this.state.isActive;

      startBtn.disabled = isActive || isConnected;
      stopBtn.disabled = !isActive;
      reconnectBtn.disabled = !isActive || this.state.connectionState === 'connecting';
    }
  }

  updateStats() {
    if (!this.config.enableStats) return;

    const statsEl = document.getElementById(`stats-${this.containerId}`);
    if (!statsEl) return;

    const uptime = Math.round((Date.now() - this.state.startTime) / 1000);
    const fps = this.renderer.getPerformanceMetrics().averageFps;
    const persons = this.state.lastPoseData?.persons?.length || 0;
    const zones = Object.keys(this.state.lastPoseData?.zone_summary || {}).length;

    // Dùng textContent thay vì innerHTML để ngăn XSS
    statsEl.textContent = '';
    const lines = [
      `Kết nối: ${this.state.connectionState}`,
      `Khung hình: ${this.state.frameCount}`,
      `FPS: ${fps.toFixed(1)}`,
      `Số người: ${persons}`,
      `Vùng: ${zones}`,
      `Thời gian: ${uptime}s`
    ];
    lines.forEach((line, index) => {
      if (index > 0) {
        statsEl.appendChild(document.createElement('br'));
      }
      const textNode = document.createTextNode(line);
      statsEl.appendChild(textNode);
    });
  }

  showError(message) {
    this.state.errorMessage = message;
    const errorEl = document.getElementById(`error-${this.containerId}`);
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.style.display = 'block';
    }
    this.logger.error('Lỗi thành phần', { message });
  }

  clearError() {
    this.state.errorMessage = null;
    const errorEl = document.getElementById(`error-${this.containerId}`);
    if (errorEl) {
      errorEl.style.display = 'none';
    }
  }

  // Các phương thức API công khai
  async start() {
    try {
      this.logger.info('Bắt đầu phát hiện tư thế');
      this.state.isActive = true;
      this.state.frameCount = 0;
      this.state.startTime = Date.now();
      
      this.clearError();
      this.updateControls();

      await poseService.startPoseStream({
        zoneIds: [this.config.zoneId],
        minConfidence: 0.3,
        maxFps: 30
      });

      this.notifyCallback('onStateChange', { isActive: true });
      this.logger.info('Phát hiện tư thế đã bắt đầu thành công');
    } catch (error) {
      this.logger.error('Bắt đầu phát hiện tư thế thất bại', { error: error.message });
      this.state.isActive = false;
      this.updateControls();
      this.showError(`Bắt đầu thất bại: ${error.message}`);
      this.notifyCallback('onError', error);
    }
  }

  stop() {
    try {
      this.logger.info('Dừng phát hiện tư thế');
      this.state.isActive = false;
      
      poseService.stopPoseStream();
      this.setConnectionState('disconnected');
      this.clearError();
      this.updateControls();

      // Xóa canvas
      if (this.renderer) {
        this.renderer.clearCanvas();
      }

      this.notifyCallback('onStateChange', { isActive: false });
      this.logger.info('Đã dừng phát hiện tư thế');
    } catch (error) {
      this.logger.error('Lỗi khi dừng phát hiện tư thế', { error: error.message });
      this.showError(`Lỗi dừng: ${error.message}`);
    }
  }

  async reconnect() {
    try {
      this.logger.info('Đang kết nối lại luồng tư thế');
      await poseService.reconnectStream();
    } catch (error) {
      this.logger.error('Kết nối lại thất bại', { error: error.message });
      this.showError(`Kết nối lại thất bại: ${error.message}`);
    }
  }

  setRenderMode(mode) {
    if (this.renderer) {
      this.renderer.setMode(mode);
      this.logger.info('Chế độ kết xuất đã thay đổi', { mode });
    }
  }

  // --- Phương thức Vệt Tư thế ---

  toggleTrail() {
    this.showTrail = !this.showTrail;
    const trailBtn = document.getElementById(`trail-btn-${this.containerId}`);
    if (trailBtn) {
      trailBtn.classList.toggle('active', this.showTrail);
      trailBtn.textContent = this.showTrail ? '\u25CB Vệt Bật' : '\u25CB Vệt';
    }
    if (!this.showTrail) {
      this.poseTrail = [];
    }
    this.logger.info('Đã bật/tắt vệt', { showTrail: this.showTrail });
  }

  updateTrail(poseData) {
    if (!this.showTrail) return;
    if (!poseData || !poseData.persons || poseData.persons.length === 0) return;

    // Nhân bản sâu các điểm khớp từ tất cả người cho khung hình này
    const frameKeypoints = poseData.persons.map(person => {
      if (!person.keypoints) return null;
      return person.keypoints.map(kp => ({
        x: kp.x,
        y: kp.y,
        confidence: kp.confidence
      }));
    }).filter(Boolean);

    if (frameKeypoints.length > 0) {
      this.poseTrail.push(frameKeypoints);
      if (this.poseTrail.length > this.maxTrailLength) {
        this.poseTrail.shift();
      }
    }
  }

  renderTrail(ctx) {
    if (!this.poseTrail || this.poseTrail.length < 2) return;

    const totalFrames = this.poseTrail.length;

    // Bảng màu điểm khớp (giống màu bộ phận cơ thể của bộ kết xuất)
    const kpColors = [
      '#ff0000', '#ff4500', '#ffa500', '#ffff00', '#adff2f',
      '#00ff00', '#00ff7f', '#00ffff', '#0080ff', '#0000ff',
      '#4000ff', '#8000ff', '#ff00ff', '#ff0080', '#ff0040',
      '#ff8080', '#ffb380'
    ];

    // Kết xuất điểm khớp mờ và đường quỹ đạo cho mỗi khung hình trong vệt
    // (bỏ qua khung hình cuối vì nó được kết xuất bởi pipeline bình thường)
    for (let frameIdx = 0; frameIdx < totalFrames - 1; frameIdx++) {
      const alpha = 0.1 + (frameIdx / totalFrames) * 0.7;
      const framePersons = this.poseTrail[frameIdx];
      const nextFramePersons = this.poseTrail[frameIdx + 1];

      framePersons.forEach((personKeypoints, personIdx) => {
        if (!personKeypoints) return;

        personKeypoints.forEach((kp, kpIdx) => {
          if (kp.confidence <= 0.1) return;

          const x = this.renderer.scaleX(kp.x);
          const y = this.renderer.scaleY(kp.y);
          const color = kpColors[kpIdx % kpColors.length];

          // Vẽ chấm điểm khớp mờ
          ctx.globalAlpha = alpha * 0.6;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          ctx.fill();

          // Vẽ đường quỹ đạo tới cùng điểm khớp trong khung hình tiếp theo
          if (nextFramePersons && nextFramePersons[personIdx]) {
            const nextKp = nextFramePersons[personIdx][kpIdx];
            if (nextKp && nextKp.confidence > 0.1) {
              const nx = this.renderer.scaleX(nextKp.x);
              const ny = this.renderer.scaleY(nextKp.y);

              ctx.globalAlpha = alpha * 0.4;
              ctx.strokeStyle = color;
              ctx.lineWidth = 1;
              ctx.beginPath();
              ctx.moveTo(x, y);
              ctx.lineTo(nx, ny);
              ctx.stroke();
            }
          }
        });
      });
    }

    // Đặt lại alpha
    ctx.globalAlpha = 1.0;
  }

  // Bật/tắt chế độ demo
  toggleDemo() {
    if (this.demoState && this.demoState.isRunning) {
      this.stopDemo();
      this.updateDemoButton(false);
    } else {
      this.runDemo();
      this.updateDemoButton(true);
    }
  }

  // Chế độ demo - kết xuất dữ liệu tư thế thử nghiệm hoạt hình
  runDemo() {
    this.logger.info('Chạy chế độ demo hoạt hình');

    // Dừng hoạt hình demo hiện có
    this.stopDemo();
    
    // Buộc bật tất cả phần tử trực quan cho demo
    this.originalConfig = { ...this.renderer.config };
    this.renderer.updateConfig({
      showKeypoints: true,
      showSkeleton: true,
      showBoundingBox: true,
      showConfidence: true,
      confidenceThreshold: 0.1,
      keypointConfidenceThreshold: 0.1
    });

    // Khởi tạo trạng thái hoạt hình
    this.demoState = {
      isRunning: true,
      frameCount: 0,
      startTime: Date.now(),
      animations: {
        person1: { type: 'walking', phase: 0, centerX: 150, centerY: 250 },
        person2: { type: 'waving', phase: 0, centerX: 350, centerY: 270 },
        person3: { type: 'dancing', phase: 0, centerX: 550, centerY: 260 }
      }
    };
    
    // Bắt đầu vòng lặp hoạt hình
    this.startDemoAnimation();

    // Hiện thông báo demo
    this.showDemoNotification('🎭 Demo Hoạt hình Đang chạy - Đi bộ, Vẫy tay & Nhảy');
  }

  stopDemo() {
    if (this.demoState && this.demoState.isRunning) {
      this.demoState.isRunning = false;
      if (this.demoAnimationFrame) {
        cancelAnimationFrame(this.demoAnimationFrame);
      }
      if (this.originalConfig) {
        this.renderer.updateConfig(this.originalConfig);
      }
      // Xóa canvas
      if (this.renderer) {
        this.renderer.clearCanvas();
      }
      this.logger.info('Đã dừng demo');
    }
  }

  updateDemoButton(isRunning) {
    const demoBtn = document.getElementById(`demo-btn-${this.containerId}`);
    if (demoBtn) {
      demoBtn.textContent = isRunning ? 'Dừng Demo' : 'Demo';
      demoBtn.style.background = isRunning ? '#dc3545' : '#6f42c1';
      demoBtn.style.borderColor = isRunning ? '#dc3545' : '#6f42c1';
    }
  }

  startDemoAnimation() {
    if (!this.demoState || !this.demoState.isRunning) return;

    this.demoState.frameCount++;
    const elapsed = (Date.now() - this.demoState.startTime) / 1000;
    
    // Tạo dữ liệu tư thế hoạt hình
    const animatedPoseData = this.generateAnimatedPoseData(elapsed);
    
    // Kết xuất dữ liệu hoạt hình
    this.renderPoseData(animatedPoseData);
    
    // Tiếp tục hoạt hình
    this.demoAnimationFrame = requestAnimationFrame(() => this.startDemoAnimation());
  }

  generateAnimatedPoseData(time) {
    const persons = [];
    
    // Người 1: Hoạt hình đi bộ
    const person1 = this.generateWalkingPerson(
      this.demoState.animations.person1.centerX,
      this.demoState.animations.person1.centerY,
      time * 2 // Walking speed
    );
    persons.push(person1);
    
    // Người 2: Hoạt hình vẫy tay
    const person2 = this.generateWavingPerson(
      this.demoState.animations.person2.centerX,
      this.demoState.animations.person2.centerY,
      time * 3 // Waving speed
    );
    persons.push(person2);
    
    // Người 3: Hoạt hình nhảy
    const person3 = this.generateDancingPerson(
      this.demoState.animations.person3.centerX,
      this.demoState.animations.person3.centerY,
      time * 2.5 // Dancing speed
    );
    persons.push(person3);
    
    return {
      timestamp: new Date().toISOString(),
      frame_id: `demo_frame_${this.demoState.frameCount.toString().padStart(6, '0')}`,
      persons: persons,
      zone_summary: {
        demo_zone: persons.length
      },
      processing_time_ms: 12 + Math.random() * 8,
      metadata: {
        mock_data: true,
        source: 'animated_demo',
        fps: Math.round(this.demoState.frameCount / ((Date.now() - this.demoState.startTime) / 1000))
      }
    };
  }

  generateWalkingPerson(centerX, centerY, time) {
    // Thông số chu kỳ đi bộ
    const walkCycle = Math.sin(time) * 0.3;
    const stepPhase = Math.sin(time * 2) * 0.2;
    
    // Vị trí điểm khớp cơ bản cho đi bộ
    const keypoints = [
      // Đầu (mũi, mắt, tai) - lắc nhẹ
      { x: centerX, y: centerY - 80 + Math.sin(time * 4) * 2, confidence: 0.95 },
      { x: centerX - 8, y: centerY - 85 + Math.sin(time * 4) * 2, confidence: 0.92 },
      { x: centerX + 8, y: centerY - 85 + Math.sin(time * 4) * 2, confidence: 0.93 },
      { x: centerX - 15, y: centerY - 82 + Math.sin(time * 4) * 2, confidence: 0.88 },
      { x: centerX + 15, y: centerY - 82 + Math.sin(time * 4) * 2, confidence: 0.89 },
      
      // Vai - chuyển động nhẹ
      { x: centerX - 35 + walkCycle * 5, y: centerY - 40 + Math.sin(time * 4) * 1, confidence: 0.94 },
      { x: centerX + 35 - walkCycle * 5, y: centerY - 40 + Math.sin(time * 4) * 1, confidence: 0.95 },
      
      // Khuỷu tay - vung tay
      { x: centerX - 25 + walkCycle * 20, y: centerY + 10 + walkCycle * 10, confidence: 0.91 },
      { x: centerX + 25 - walkCycle * 20, y: centerY + 10 - walkCycle * 10, confidence: 0.92 },
      
      // Cổ tay - theo khuỷu tay
      { x: centerX - 15 + walkCycle * 25, y: centerY + 55 + walkCycle * 15, confidence: 0.87 },
      { x: centerX + 15 - walkCycle * 25, y: centerY + 55 - walkCycle * 15, confidence: 0.88 },
      
      // Hông - chuyển động nhẹ
      { x: centerX - 18 + walkCycle * 3, y: centerY + 60, confidence: 0.96 },
      { x: centerX + 18 - walkCycle * 3, y: centerY + 60, confidence: 0.96 },
      
      // Đầu gối - chuyển động đi bộ
      { x: centerX - 20 + stepPhase * 15, y: centerY + 120 - Math.abs(stepPhase) * 10, confidence: 0.93 },
      { x: centerX + 20 - stepPhase * 15, y: centerY + 120 - Math.abs(-stepPhase) * 10, confidence: 0.94 },
      
      // Mắt cá chân - vị trí đặt chân
      { x: centerX - 22 + stepPhase * 20, y: centerY + 180, confidence: 0.90 },
      { x: centerX + 22 - stepPhase * 20, y: centerY + 180, confidence: 0.91 }
    ];
    
    return {
      person_id: 'demo_walker',
      confidence: 0.94 + Math.sin(time) * 0.03,
      bbox: this.calculateBoundingBox(keypoints),
      keypoints: keypoints,
      zone_id: 'demo_zone',
      activity: 'walking'
    };
  }

  generateWavingPerson(centerX, centerY, time) {
    // Tham số vẫy tay
    const wavePhase = Math.sin(time) * 0.8;
    const armWave = Math.sin(time * 1.5) * 30;
    
    const keypoints = [
      // Đầu - ổn định
      { x: centerX, y: centerY - 80, confidence: 0.96 },
      { x: centerX - 8, y: centerY - 85, confidence: 0.94 },
      { x: centerX + 8, y: centerY - 85, confidence: 0.94 },
      { x: centerX - 15, y: centerY - 82, confidence: 0.90 },
      { x: centerX + 15, y: centerY - 82, confidence: 0.91 },
      
      // Vai
      { x: centerX - 35, y: centerY - 40, confidence: 0.95 },
      { x: centerX + 35, y: centerY - 40, confidence: 0.95 },

      // Khuỷu tay - tay trái ổn định, tay phải vẫy
      { x: centerX - 55, y: centerY + 10, confidence: 0.92 },
      { x: centerX + 65 + armWave * 0.3, y: centerY - 10 - Math.abs(armWave) * 0.5, confidence: 0.93 },
      
      // Cổ tay - chuyển động vẫy mạnh
      { x: centerX - 60, y: centerY + 60, confidence: 0.88 },
      { x: centerX + 45 + armWave, y: centerY - 30 - Math.abs(armWave) * 0.8, confidence: 0.89 },
      
      // Hông - ổn định
      { x: centerX - 18, y: centerY + 60, confidence: 0.97 },
      { x: centerX + 18, y: centerY + 60, confidence: 0.97 },
      
      // Đầu gối - chuyển động nhẹ
      { x: centerX - 20, y: centerY + 120 + Math.sin(time * 0.5) * 5, confidence: 0.94 },
      { x: centerX + 20, y: centerY + 120 + Math.sin(time * 0.5) * 5, confidence: 0.95 },
      
      // Mắt cá chân - ổn định
      { x: centerX - 22, y: centerY + 180, confidence: 0.92 },
      { x: centerX + 22, y: centerY + 180, confidence: 0.93 }
    ];
    
    return {
      person_id: 'demo_waver',
      confidence: 0.91 + Math.sin(time * 0.7) * 0.05,
      bbox: this.calculateBoundingBox(keypoints),
      keypoints: keypoints,
      zone_id: 'demo_zone',
      activity: 'waving'
    };
  }

  generateDancingPerson(centerX, centerY, time) {
    // Tham số nhảy - chuyển động phức tạp hơn
    const dancePhase1 = Math.sin(time * 1.2) * 0.6;
    const dancePhase2 = Math.cos(time * 1.8) * 0.4;
    const bodyBob = Math.sin(time * 3) * 8;
    const hipSway = Math.sin(time * 1.5) * 15;
    
    const keypoints = [
      // Đầu - lắc nhảy
      { x: centerX + dancePhase1 * 5, y: centerY - 80 + bodyBob, confidence: 0.96 },
      { x: centerX - 8 + dancePhase1 * 5, y: centerY - 85 + bodyBob, confidence: 0.94 },
      { x: centerX + 8 + dancePhase1 * 5, y: centerY - 85 + bodyBob, confidence: 0.94 },
      { x: centerX - 15 + dancePhase1 * 5, y: centerY - 82 + bodyBob, confidence: 0.90 },
      { x: centerX + 15 + dancePhase1 * 5, y: centerY - 82 + bodyBob, confidence: 0.91 },
      
      // Vai - chuyển động nhảy
      { x: centerX - 35 + dancePhase1 * 10, y: centerY - 40 + bodyBob * 0.5, confidence: 0.95 },
      { x: centerX + 35 + dancePhase2 * 10, y: centerY - 40 + bodyBob * 0.5, confidence: 0.95 },
      
      // Khuỷu tay - cả hai tay nhảy
      { x: centerX - 45 + dancePhase1 * 25, y: centerY + 0 + dancePhase1 * 20, confidence: 0.92 },
      { x: centerX + 45 + dancePhase2 * 25, y: centerY + 0 + dancePhase2 * 20, confidence: 0.93 },
      
      // Cổ tay - chuyển động tay biểu cảm
      { x: centerX - 40 + dancePhase1 * 35, y: centerY + 50 + dancePhase1 * 30, confidence: 0.88 },
      { x: centerX + 40 + dancePhase2 * 35, y: centerY + 50 + dancePhase2 * 30, confidence: 0.89 },
      
      // Hông - lắc nhảy
      { x: centerX - 18 + hipSway * 0.3, y: centerY + 60 + bodyBob * 0.3, confidence: 0.97 },
      { x: centerX + 18 + hipSway * 0.3, y: centerY + 60 + bodyBob * 0.3, confidence: 0.97 },
      
      // Đầu gối - bước nhảy
      { x: centerX - 20 + hipSway * 0.5 + Math.sin(time * 2.5) * 10, y: centerY + 120 + Math.abs(Math.sin(time * 2.5)) * 15, confidence: 0.94 },
      { x: centerX + 20 + hipSway * 0.5 + Math.cos(time * 2.5) * 10, y: centerY + 120 + Math.abs(Math.cos(time * 2.5)) * 15, confidence: 0.95 },
      
      // Mắt cá chân - vị trí bàn chân
      { x: centerX - 22 + hipSway * 0.6 + Math.sin(time * 2.5) * 12, y: centerY + 180, confidence: 0.92 },
      { x: centerX + 22 + hipSway * 0.6 + Math.cos(time * 2.5) * 12, y: centerY + 180, confidence: 0.93 }
    ];
    
    return {
      person_id: 'demo_dancer',
      confidence: 0.89 + Math.sin(time * 1.3) * 0.07,
      bbox: this.calculateBoundingBox(keypoints),
      keypoints: keypoints,
      zone_id: 'demo_zone',
      activity: 'dancing'
    };
  }

  calculateBoundingBox(keypoints) {
    const validPoints = keypoints.filter(kp => kp.confidence > 0.1);
    if (validPoints.length === 0) return { x: 0, y: 0, width: 50, height: 50 };
    
    const xs = validPoints.map(kp => kp.x);
    const ys = validPoints.map(kp => kp.y);
    
    const minX = Math.min(...xs) - 10;
    const maxX = Math.max(...xs) + 10;
    const minY = Math.min(...ys) - 10;
    const maxY = Math.max(...ys) + 10;
    
    return {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY
    };
  }

  generateDemoKeypoints(centerX, centerY) {
    // Thứ tự điểm khớp COCO: mũi, mắt_trái, mắt_phải, tai_trái, tai_phải,
    // vai_trái, vai_phải, khuỷu_tay_trái, khuỷu_tay_phải, cổ_tay_trái, cổ_tay_phải,
    // hông_trái, hông_phải, đầu_gối_trái, đầu_gối_phải, mắt_cá_chân_trái, mắt_cá_chân_phải
    const offsets = [
      [0, -80],     // mũi
      [-10, -90],   // mắt_trái
      [10, -90],    // mắt_phải
      [-20, -85],   // tai_trái
      [20, -85],    // tai_phải
      [-40, -40],   // vai_trái
      [40, -40],    // vai_phải
      [-60, 10],    // khuỷu_tay_trái
      [60, 10],     // khuỷu_tay_phải
      [-65, 60],    // cổ_tay_trái
      [65, 60],     // cổ_tay_phải
      [-20, 60],    // hông_trái
      [20, 60],     // hông_phải
      [-25, 120],   // đầu_gối_trái
      [25, 120],    // đầu_gối_phải
      [-25, 180],   // mắt_cá_chân_trái
      [25, 180]     // mắt_cá_chân_phải
    ];
    
    return offsets.map(([dx, dy]) => ({
      x: centerX + dx,
      y: centerY + dy,
      confidence: 0.8 + (Math.random() * 0.2)
    }));
  }

  showDemoNotification(message = '🎭 Chế độ Demo Đang hoạt động') {
    const notification = document.createElement('div');
    notification.style.cssText = `
      position: absolute;
      top: 10px;
      left: 10px;
      background: rgba(111, 66, 193, 0.9);
      color: white;
      padding: 10px 15px;
      border-radius: 4px;
      font-size: 14px;
      z-index: 20;
      pointer-events: none;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    `;
    notification.textContent = message;
    
    const overlay = document.getElementById(`overlay-${this.containerId}`);
    
    // Xóa thông báo hiện có
    const existingNotifications = overlay.querySelectorAll('div[style*="background: rgba(111, 66, 193"]');
    existingNotifications.forEach(n => n.remove());
    
    overlay.appendChild(notification);
    
    // Xóa thông báo sau 3 giây
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 3000);
  }

  // Các phương thức cấu hình
  updateConfig(newConfig) {
    this.config = { ...this.config, ...newConfig };
    
    if (this.renderer) {
      this.renderer.updateConfig(newConfig);
    }
    
    this.logger.debug('Đã cập nhật cấu hình thành phần', { config: this.config });
  }

  // Quản lý callback
  setCallback(eventName, callback) {
    if (eventName in this.callbacks) {
      this.callbacks[eventName] = callback;
    }
  }

  notifyCallback(eventName, data) {
    if (this.callbacks[eventName]) {
      try {
        this.callbacks[eventName](data);
      } catch (error) {
        this.logger.error('Lỗi callback', { eventName, error: error.message });
      }
    }
  }

  // Các phương thức tiện ích
  getState() {
    return { ...this.state };
  }

  getPerformanceMetrics() {
    return this.renderer ? this.renderer.getPerformanceMetrics() : null;
  }

  exportFrame(format = 'png') {
    return this.renderer ? this.renderer.exportFrame(format) : null;
  }

  // Phương thức kiểm tra để gỡ lỗi
  renderTestShape() {
    if (this.renderer) {
      this.renderer.renderTestShape();
    }
  }

  // Hiển thị modal cài đặt
  showSettings() {
    this.logger.info('Đang mở modal cài đặt');
    
    if (!this.settingsPanel) {
      this.createSettingsModal();
    }
    
    this.settingsPanel.show();
  }

  createSettingsModal() {
    // Tạo container tạm thời cho bảng cài đặt
    const modalContainer = document.createElement('div');
    modalContainer.id = `settings-modal-${this.containerId}`;
    modalContainer.className = 'settings-modal-wrapper';
    modalContainer.innerHTML = `
      <div class="settings-modal-overlay">
        <div class="settings-modal-dialog">
          <div class="settings-modal-header">
            <h2>⚙️ Cài đặt Phát hiện Tư thế</h2>
            <button class="settings-modal-close" type="button">×</button>
          </div>
          <div class="settings-modal-body" id="settings-container-${this.containerId}">
            <!-- Bảng cài đặt sẽ được chèn vào đây -->
          </div>
        </div>
      </div>
    `;
    
    document.body.appendChild(modalContainer);
    
    // Tạo bảng cài đặt bên trong modal
    this.settingsPanel = new SettingsPanel(`settings-container-${this.containerId}`, {
      enableAdvancedSettings: true,
      enableDebugControls: true,
      enableExportFeatures: true,
      allowConfigPersistence: true,
      initialSettings: this.getInitialSettings()
    });
    
    // Thiết lập callback cho bảng cài đặt
    this.settingsPanel.setCallback('onSettingsChange', (data) => {
      this.handleSettingsChange(data);
    });
    
    this.settingsPanel.setCallback('onRenderModeChange', (mode) => {
      this.setRenderMode(mode);
    });
    
    // Thiết lập xử lý sự kiện modal
    this.setupModalEventHandlers(modalContainer);
    
    // Thêm kiểu dáng modal
    this.addModalStyles();
    
    // Thêm phương thức hiện/ẩn cho modal
    modalContainer.show = () => {
      modalContainer.style.display = 'flex';
      modalContainer.classList.add('active');
      document.body.style.overflow = 'hidden';
    };
    
    modalContainer.hide = () => {
      modalContainer.style.display = 'none';
      modalContainer.classList.remove('active');
      document.body.style.overflow = '';
    };
    
    this.settingsPanel.show = () => modalContainer.show();
    this.settingsPanel.hide = () => modalContainer.hide();
    
    this.logger.debug('Đã tạo modal cài đặt');
  }

  setupModalEventHandlers(modalContainer) {
    // Nút đóng
    const closeBtn = modalContainer.querySelector('.settings-modal-close');
    closeBtn.addEventListener('click', () => {
      this.settingsPanel.hide();
    });
    
    // Nhấp lớp phủ để đóng
    const overlay = modalContainer.querySelector('.settings-modal-overlay');
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        this.settingsPanel.hide();
      }
    });
    
    // Phím Escape để đóng
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modalContainer.classList.contains('active')) {
        this.settingsPanel.hide();
      }
    });
  }

  addModalStyles() {
    if (document.querySelector('#pose-canvas-modal-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'pose-canvas-modal-styles';
    style.textContent = `
      .settings-modal-wrapper {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10000;
        display: none;
        opacity: 0;
        transition: opacity 0.3s ease;
      }

      .settings-modal-wrapper.active {
        opacity: 1;
      }

      .settings-modal-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
        backdrop-filter: blur(5px);
      }

      .settings-modal-dialog {
        background: white;
        border-radius: 12px;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        width: 100%;
        max-width: 800px;
        max-height: 90vh;
        overflow: hidden;
        transform: scale(0.9);
        transition: transform 0.3s ease;
        display: flex;
        flex-direction: column;
      }

      .settings-modal-wrapper.active .settings-modal-dialog {
        transform: scale(1);
      }

      .settings-modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 20px 24px;
        border-bottom: 1px solid #e9ecef;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
      }

      .settings-modal-header h2 {
        margin: 0;
        font-size: 20px;
        font-weight: 600;
      }

      .settings-modal-close {
        background: rgba(255, 255, 255, 0.2);
        border: none;
        color: white;
        font-size: 24px;
        cursor: pointer;
        padding: 8px;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s ease;
        backdrop-filter: blur(10px);
      }

      .settings-modal-close:hover {
        background: rgba(255, 255, 255, 0.3);
        transform: scale(1.1);
      }

      .settings-modal-body {
        flex: 1;
        overflow-y: auto;
        padding: 0;
      }

      /* Ghi đè kiểu dáng bảng cài đặt cho modal */
      .settings-modal-body .settings-panel {
        border: none;
        border-radius: 0;
        box-shadow: none;
      }

      .settings-modal-body .settings-header {
        display: none;
      }

      .settings-modal-body .settings-content {
        max-height: none;
        padding: 24px;
      }

      /* Thanh cuộn tuỳ chỉnh cho modal */
      .settings-modal-body::-webkit-scrollbar {
        width: 8px;
      }

      .settings-modal-body::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 4px;
      }

      .settings-modal-body::-webkit-scrollbar-thumb {
        background: #c1c1c1;
        border-radius: 4px;
      }

      .settings-modal-body::-webkit-scrollbar-thumb:hover {
        background: #a8a8a8;
      }

      /* Tương thích di động */
      @media (max-width: 768px) {
        .settings-modal-overlay {
          padding: 10px;
        }
        
        .settings-modal-dialog {
          max-width: 100%;
          max-height: 95vh;
        }
        
        .settings-modal-header {
          padding: 15px 20px;
        }
        
        .settings-modal-body .settings-content {
          padding: 20px;
        }
      }
    `;
    
    document.head.appendChild(style);
  }

  getInitialSettings() {
    return {
      // Lấy cấu hình renderer hiện tại
      ...(this.renderer ? this.renderer.getConfig() : {}),
      // Thêm các cài đặt liên quan khác
      currentZone: this.config.zoneId || 'zone_1',
      maxFps: 30,
      autoReconnect: true,
      connectionTimeout: 10000
    };
  }

  handleSettingsChange(data) {
    this.logger.debug('Cài đặt đã thay đổi', data);
    
    if (data.settings && this.renderer) {
      // Áp dụng cài đặt kết xuất
      const renderConfig = {
        mode: data.settings.renderMode,
        showKeypoints: data.settings.showKeypoints,
        showSkeleton: data.settings.showSkeleton,
        showBoundingBox: data.settings.showBoundingBox,
        showConfidence: data.settings.showConfidence,
        showZones: data.settings.showZones,
        showDebugInfo: data.settings.showDebugInfo,
        skeletonColor: data.settings.skeletonColor,
        keypointColor: data.settings.keypointColor,
        boundingBoxColor: data.settings.boundingBoxColor,
        confidenceThreshold: data.settings.confidenceThreshold,
        keypointConfidenceThreshold: data.settings.keypointConfidenceThreshold,
        enableSmoothing: data.settings.enableSmoothing
      };
      
      this.renderer.updateConfig(renderConfig);
      this.logger.info('Đã cập nhật cấu hình renderer từ cài đặt');
    }
  }

  // Dọn dẹp
  dispose() {
    this.logger.info('Đang huỷ thành phần PoseDetectionCanvas');
    
    try {
      // Dừng phát hiện tư thế
      if (this.state.isActive) {
        this.stop();
      }

      // Dừng hoạt hình demo
      this.stopDemo();

      // Huỷ bảng cài đặt
      if (this.settingsPanel) {
        this.settingsPanel.dispose();
        const modalContainer = document.getElementById(`settings-modal-${this.containerId}`);
        if (modalContainer) {
          modalContainer.remove();
        }
      }

      // Huỷ đăng ký dịch vụ tư thế
      this.unsubscribeFunctions.forEach(unsubscribe => unsubscribe());
      this.unsubscribeFunctions = [];

      // Dọn dẹp trình quan sát thay đổi kích thước
      if (this.resizeObserver) {
        this.resizeObserver.disconnect();
      }

      // Xóa DOM
      if (this.container) {
        this.container.innerHTML = '';
      }

      this.logger.info('Đã huỷ thành phần PoseDetectionCanvas thành công');
    } catch (error) {
      this.logger.error('Lỗi khi huỷ', { error: error.message });
    }
  }
}