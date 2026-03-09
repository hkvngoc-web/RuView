/**
 * SensingTab — Trực quan hoá Cảm biến WiFi Trực tiếp
 *
 * Kết nối tới dịch vụ WebSocket cảm biến và hiển thị:
 *   1. Trường tín hiệu 3D Gaussian-splat (qua gaussian-splats.js)
 *   2. HUD lớp phủ với chỉ số thời gian thực (RSSI, phương sai, dải tần, phân loại)
 */

import { sensingService } from '../services/sensing.service.js';
import { GaussianSplatRenderer } from './gaussian-splats.js';

export class SensingTab {
  /** @param {HTMLElement} container - phần tử section #sensing */
  constructor(container) {
    this.container = container;
    this.splatRenderer = null;
    this._unsubData = null;
    this._unsubState = null;
    this._resizeObserver = null;
    this._threeLoaded = false;
  }

  async init() {
    this._buildDOM();
    await this._loadThree();
    this._initSplatRenderer();
    this._connectService();
    this._setupResize();
  }

  // ---- Xây dựng DOM --------------------------------------------------

  _buildDOM() {
    this.container.innerHTML = `
      <h2>Cảm biến WiFi Trực tiếp</h2>

      <!-- Banner trạng thái nguồn dữ liệu — cập nhật bởi _onStateChange -->
      <div id="sensingSourceBanner" class="sensing-source-banner sensing-source-reconnecting"
           role="status" aria-live="polite">
        ĐANG KẾT NỐI LẠI...
      </div>

      <div class="sensing-layout">
        <!-- Khung nhìn 3D -->
        <div class="sensing-viewport" id="sensingViewport">
          <div class="sensing-loading">Đang tải công cụ 3D...</div>
        </div>

        <!-- Bảng bên -->
        <div class="sensing-panel">
          <!-- Kết nối -->
          <div class="sensing-card">
            <div class="sensing-card-title">Kết nối</div>
            <div class="sensing-connection">
              <span class="sensing-dot" id="sensingDot"></span>
              <span id="sensingState">Đang kết nối...</span>
              <span class="sensing-source" id="sensingSource"></span>
            </div>
          </div>

          <!-- RSSI -->
          <div class="sensing-card">
            <div class="sensing-card-title">RSSI</div>
            <div class="sensing-big-value" id="sensingRssi">-- dBm</div>
            <canvas id="sensingSparkline" width="200" height="40"></canvas>
          </div>

          <!-- Đặc trưng tín hiệu -->
          <div class="sensing-card">
            <div class="sensing-card-title">Đặc trưng Tín hiệu</div>
            <div class="sensing-meters">
              <div class="sensing-meter">
                <label>Phương sai</label>
                <div class="sensing-bar"><div class="sensing-bar-fill" id="barVariance"></div></div>
                <span class="sensing-meter-val" id="valVariance">0</span>
              </div>
              <div class="sensing-meter">
                <label>Dải Chuyển động</label>
                <div class="sensing-bar"><div class="sensing-bar-fill motion" id="barMotion"></div></div>
                <span class="sensing-meter-val" id="valMotion">0</span>
              </div>
              <div class="sensing-meter">
                <label>Dải Hô hấp</label>
                <div class="sensing-bar"><div class="sensing-bar-fill breath" id="barBreath"></div></div>
                <span class="sensing-meter-val" id="valBreath">0</span>
              </div>
              <div class="sensing-meter">
                <label>Công suất Phổ</label>
                <div class="sensing-bar"><div class="sensing-bar-fill spectral" id="barSpectral"></div></div>
                <span class="sensing-meter-val" id="valSpectral">0</span>
              </div>
            </div>
          </div>

          <!-- Phân loại -->
          <div class="sensing-card">
            <div class="sensing-card-title">Phân loại</div>
            <div class="sensing-classification" id="sensingClassification">
              <div class="sensing-class-label" id="classLabel">VẮNG MẶT</div>
              <div class="sensing-confidence">
                <label>Độ tin cậy</label>
                <div class="sensing-bar"><div class="sensing-bar-fill confidence" id="barConfidence"></div></div>
                <span class="sensing-meter-val" id="valConfidence">0%</span>
              </div>
            </div>
          </div>

          <!-- Thông tin giới thiệu -->
          <div class="sensing-card">
            <div class="sensing-card-title">Về Dữ liệu Này</div>
            <p class="sensing-about-text">
              Các chỉ số được tính toán từ Thông tin Trạng thái Kênh WiFi (CSI).
              Với <strong>1 ESP32</strong> bạn có thể phát hiện sự hiện diện, ước tính
              hô hấp và chuyển động thô. Thêm <strong>3-4+ node ESP32</strong>
              xung quanh phòng để có độ phân giải không gian và theo dõi cấp chi.
            </p>
          </div>

          <!-- Thông tin chi tiết -->
          <div class="sensing-card">
            <div class="sensing-card-title">Chi tiết</div>
            <div class="sensing-details">
              <div class="sensing-detail-row">
                <span>Tần số Chủ đạo</span><span id="valDomFreq">0 Hz</span>
              </div>
              <div class="sensing-detail-row">
                <span>Điểm Thay đổi</span><span id="valChangePoints">0</span>
              </div>
              <div class="sensing-detail-row">
                <span>Tốc độ Lấy mẫu</span><span id="valSampleRate">--</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ---- Tải Three.js --------------------------------------------------

  async _loadThree() {
    if (window.THREE) {
      this._threeLoaded = true;
      return;
    }

    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
      script.onload = () => {
        this._threeLoaded = true;
        resolve();
      };
      script.onerror = () => reject(new Error('Tải Three.js thất bại'));
      document.head.appendChild(script);
    });
  }

  // ---- Bộ kết xuất splat ----------------------------------------------------

  _initSplatRenderer() {
    const viewport = this.container.querySelector('#sensingViewport');
    if (!viewport) return;

    // Xóa thông báo đang tải
    viewport.innerHTML = '';

    try {
      this.splatRenderer = new GaussianSplatRenderer(viewport, {
        width: viewport.clientWidth,
        height: viewport.clientHeight || 500,
      });
    } catch (e) {
      console.error('[SensingTab] Khởi tạo bộ kết xuất splat thất bại:', e);
      viewport.innerHTML = '<div class="sensing-loading">Kết xuất 3D không khả dụng</div>';
    }
  }

  // ---- Kết nối dịch vụ ------------------------------------------------

  _connectService() {
    sensingService.start();

    this._unsubData = sensingService.onData((data) => this._onSensingData(data));
    this._unsubState = sensingService.onStateChange((state) => this._onStateChange(state));
  }

  _onSensingData(data) {
    // Cập nhật khung nhìn 3D
    if (this.splatRenderer) {
      this.splatRenderer.update(data);
    }

    // Cập nhật HUD
    this._updateHUD(data);
  }

  _onStateChange(state) {
    const dot    = this.container.querySelector('#sensingDot');
    const text   = this.container.querySelector('#sensingState');
    const banner = this.container.querySelector('#sensingSourceBanner');

    if (dot && text) {
      const stateLabels = {
        disconnected: 'Ngắt kết nối',
        connecting:   'Đang kết nối...',
        connected:    'Đã kết nối',
        reconnecting: 'Đang kết nối lại...',
        simulated:    'Mô phỏng',
      };
      dot.className = 'sensing-dot ' + state;
      text.textContent = stateLabels[state] || state;
    }

    if (banner) {
      // Ánh xạ dataSource của dịch vụ sang văn bản banner và class CSS.
      const dataSource = sensingService.dataSource;
      const bannerConfig = {
        'live':              { text: 'TRỰC TIẾP \u2014 PHẦN CỨNG ESP32',       cls: 'sensing-source-live' },
        'server-simulated':  { text: 'MÔ PHỎNG \u2014 KHÔNG CÓ PHẦN CỨNG',    cls: 'sensing-source-server-sim' },
        'reconnecting':      { text: 'ĐANG KẾT NỐI LẠI...',                cls: 'sensing-source-reconnecting' },
        'simulated':         { text: 'NGOẠI TUYẾN \u2014 MÔ PHỎNG CỤC BỘ',    cls: 'sensing-source-simulated' },
      };
      const cfg = bannerConfig[dataSource] || bannerConfig.reconnecting;
      banner.textContent = cfg.text;
      banner.className = 'sensing-source-banner ' + cfg.cls;
    }
  }

  // ---- Cập nhật HUD --------------------------------------------------------

  _updateHUD(data) {
    const f = data.features || {};
    const c = data.classification || {};

    // RSSI
    this._setText('sensingRssi', `${(f.mean_rssi || -80).toFixed(1)} dBm`);
    this._setText('sensingSource', data.source || '');

    // Thanh (tỷ lệ 0-100%)
    this._setBar('barVariance', f.variance, 10, 'valVariance', f.variance);
    this._setBar('barMotion', f.motion_band_power, 0.5, 'valMotion', f.motion_band_power);
    this._setBar('barBreath', f.breathing_band_power, 0.3, 'valBreath', f.breathing_band_power);
    this._setBar('barSpectral', f.spectral_power, 2.0, 'valSpectral', f.spectral_power);

    // Phân loại
    const label = this.container.querySelector('#classLabel');
    if (label) {
      const level = (c.motion_level || 'absent').toUpperCase();
      label.textContent = level;
      label.className = 'sensing-class-label ' + (c.motion_level || 'absent');
    }

    const confPct = ((c.confidence || 0) * 100).toFixed(0);
    this._setBar('barConfidence', c.confidence, 1.0, 'valConfidence', confPct + '%');

    // Chi tiết
    this._setText('valDomFreq', (f.dominant_freq_hz || 0).toFixed(3) + ' Hz');
    this._setText('valChangePoints', String(f.change_points || 0));
    const srcLabel = (data.source === 'simulated' || data.source === 'simulate') ? 'sim' : data.source || 'live';
    this._setText('valSampleRate', srcLabel);

    // Đồ thị spark
    this._drawSparkline();
  }

  _setText(id, text) {
    const el = this.container.querySelector('#' + id);
    if (el) el.textContent = text;
  }

  _setBar(barId, value, maxVal, valId, displayVal) {
    const bar = this.container.querySelector('#' + barId);
    if (bar) {
      const pct = Math.min(100, Math.max(0, ((value || 0) / maxVal) * 100));
      bar.style.width = pct + '%';
    }
    if (valId && displayVal != null) {
      const el = this.container.querySelector('#' + valId);
      if (el) el.textContent = typeof displayVal === 'number' ? displayVal.toFixed(3) : displayVal;
    }
  }

  _drawSparkline() {
    const canvas = this.container.querySelector('#sensingSparkline');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const history = sensingService.getRssiHistory();
    if (history.length < 2) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const min = Math.min(...history) - 2;
    const max = Math.max(...history) + 2;
    const range = max - min || 1;

    ctx.beginPath();
    ctx.strokeStyle = '#32b8c6';
    ctx.lineWidth = 1.5;

    for (let i = 0; i < history.length; i++) {
      const x = (i / (history.length - 1)) * w;
      const y = h - ((history[i] - min) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // ---- Thay đổi kích thước ------------------------------------------------------------

  _setupResize() {
    const viewport = this.container.querySelector('#sensingViewport');
    if (!viewport || !window.ResizeObserver) return;

    this._resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (this.splatRenderer) {
          this.splatRenderer.resize(entry.contentRect.width, entry.contentRect.height);
        }
      }
    });
    this._resizeObserver.observe(viewport);
  }

  // ---- Dọn dẹp -----------------------------------------------------------

  dispose() {
    if (this._unsubData) this._unsubData();
    if (this._unsubState) this._unsubState();
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (this.splatRenderer) this.splatRenderer.dispose();
    sensingService.stop();
  }
}
