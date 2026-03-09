// Lớp phủ HUD Bảng điều khiển - Trực quan hoá 3D WiFi DensePose
// Trạng thái kết nối, bộ đếm FPS, độ tin cậy phát hiện, số người, chế độ cảm biến

export class DashboardHUD {
  constructor(container) {
    this.container = typeof container === 'string'
      ? document.getElementById(container)
      : container;

    // Trạng thái
    this.state = {
      connectionStatus: 'disconnected', // connected, disconnected, connecting, error
      isRealData: false,
      fps: 0,
      confidence: 0,
      personCount: 0,
      sensingMode: 'Mock',    // CSI, RSSI, Mock
      latency: 0,
      messageCount: 0,
      uptime: 0
    };

    this._fpsFrames = [];
    this._lastFpsUpdate = 0;

    this._build();
  }

  _build() {
    // Tạo container lớp phủ HUD
    this.hudElement = document.createElement('div');
    this.hudElement.id = 'viz-hud';
    this.hudElement.innerHTML = `
      <style>
        #viz-hud {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          pointer-events: none;
          z-index: 100;
          font-family: 'Courier New', 'Consolas', monospace;
          color: #88ccff;
        }
        #viz-hud * {
          pointer-events: none;
        }

        /* Banner nguồn dữ liệu */
        .hud-banner {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          text-align: center;
          padding: 6px 0;
          font-size: 14px;
          font-weight: bold;
          letter-spacing: 3px;
          text-transform: uppercase;
          z-index: 110;
        }
        .hud-banner.mock {
          background: linear-gradient(90deg, rgba(180,100,0,0.85) 0%, rgba(200,120,0,0.85) 50%, rgba(180,100,0,0.85) 100%);
          color: #fff;
          border-bottom: 2px solid #ff8800;
        }
        .hud-banner.real {
          background: linear-gradient(90deg, rgba(0,120,60,0.85) 0%, rgba(0,160,80,0.85) 50%, rgba(0,120,60,0.85) 100%);
          color: #fff;
          border-bottom: 2px solid #00ff66;
          animation: pulse-green 2s ease-in-out infinite;
        }
        @keyframes pulse-green {
          0%, 100% { border-bottom-color: #00ff66; }
          50% { border-bottom-color: #00cc44; }
        }

        /* Trên-trái: thông tin kết nối */
        .hud-top-left {
          position: absolute;
          top: 40px;
          left: 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .hud-row {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          line-height: 1.4;
        }
        .hud-label {
          color: #5588aa;
          min-width: 65px;
          text-transform: uppercase;
          font-size: 9px;
          letter-spacing: 1px;
        }
        .hud-value {
          color: #aaddff;
          font-weight: bold;
          font-size: 12px;
        }

        /* Chấm trạng thái */
        .hud-status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
          margin-right: 4px;
        }
        .hud-status-dot.connected {
          background: #00ff66;
          box-shadow: 0 0 6px #00ff66;
        }
        .hud-status-dot.disconnected {
          background: #666;
        }
        .hud-status-dot.connecting {
          background: #ffaa00;
          box-shadow: 0 0 6px #ffaa00;
          animation: blink 1s infinite;
        }
        .hud-status-dot.error {
          background: #ff3344;
          box-shadow: 0 0 6px #ff3344;
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }

        /* Trên-phải: hiệu suất */
        .hud-top-right {
          position: absolute;
          top: 40px;
          right: 12px;
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 4px;
        }
        .hud-fps {
          font-size: 22px;
          font-weight: bold;
          color: #00ff88;
          line-height: 1;
        }
        .hud-fps.low { color: #ff4444; }
        .hud-fps.mid { color: #ffaa00; }
        .hud-fps.high { color: #00ff88; }

        /* Dưới-trái: thông tin phát hiện */
        .hud-bottom-left {
          position: absolute;
          bottom: 12px;
          left: 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .hud-person-count {
          font-size: 28px;
          font-weight: bold;
          line-height: 1;
        }
        .hud-confidence-bar {
          width: 120px;
          height: 6px;
          background: rgba(20, 30, 50, 0.8);
          border: 1px solid #223344;
          border-radius: 3px;
          overflow: hidden;
        }
        .hud-confidence-fill {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s ease, background 0.3s ease;
        }

        /* Dưới-phải: chế độ cảm biến */
        .hud-bottom-right {
          position: absolute;
          bottom: 12px;
          right: 12px;
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 4px;
        }
        .hud-mode-badge {
          padding: 3px 10px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: bold;
          letter-spacing: 1px;
          text-transform: uppercase;
        }
        .hud-mode-badge.csi {
          background: rgba(0, 100, 200, 0.7);
          border: 1px solid #0088ff;
          color: #aaddff;
        }
        .hud-mode-badge.rssi {
          background: rgba(100, 0, 200, 0.7);
          border: 1px solid #8800ff;
          color: #ddaaff;
        }
        .hud-mode-badge.mock {
          background: rgba(120, 80, 0, 0.7);
          border: 1px solid #ff8800;
          color: #ffddaa;
        }

        /* Trang trí ngoặc góc */
        .hud-corner {
          position: absolute;
          width: 20px;
          height: 20px;
          border-color: rgba(100, 150, 200, 0.3);
          border-style: solid;
        }
        .hud-corner.tl { top: 36px; left: 4px; border-width: 1px 0 0 1px; }
        .hud-corner.tr { top: 36px; right: 4px; border-width: 1px 1px 0 0; }
        .hud-corner.bl { bottom: 4px; left: 4px; border-width: 0 0 1px 1px; }
        .hud-corner.br { bottom: 4px; right: 4px; border-width: 0 1px 1px 0; }

        /* Gợi ý điều khiển */
        .hud-controls-hint {
          position: absolute;
          bottom: 50px;
          left: 50%;
          transform: translateX(-50%);
          font-size: 10px;
          color: #445566;
          text-align: center;
          opacity: 0.6;
        }
      </style>

      <!-- Banner nguồn dữ liệu -->
      <div class="hud-banner mock" id="hud-banner">DỮ LIỆU GIẢ LẬP</div>

      <!-- Trang trí góc -->
      <div class="hud-corner tl"></div>
      <div class="hud-corner tr"></div>
      <div class="hud-corner bl"></div>
      <div class="hud-corner br"></div>

      <!-- Trên-trái: thông tin kết nối -->
      <div class="hud-top-left">
        <div class="hud-row">
          <span class="hud-status-dot disconnected" id="hud-status-dot"></span>
          <span class="hud-value" id="hud-conn-status">Ngắt kết nối</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Độ trễ</span>
          <span class="hud-value" id="hud-latency">-- ms</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Tin nhắn</span>
          <span class="hud-value" id="hud-msg-count">0</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Thời gian hoạt động</span>
          <span class="hud-value" id="hud-uptime">0s</span>
        </div>
      </div>

      <!-- Trên-phải: FPS -->
      <div class="hud-top-right">
        <div class="hud-fps high" id="hud-fps">-- FPS</div>
        <div class="hud-row">
          <span class="hud-label">Khung hình</span>
          <span class="hud-value" id="hud-frame-time">-- ms</span>
        </div>
      </div>

      <!-- Dưới-trái: thông tin phát hiện -->
      <div class="hud-bottom-left">
        <div class="hud-row">
          <span class="hud-label">Số người</span>
          <span class="hud-person-count hud-value" id="hud-person-count">0</span>
        </div>
        <div class="hud-row">
          <span class="hud-label">Độ tin cậy</span>
          <span class="hud-value" id="hud-confidence">0%</span>
        </div>
        <div class="hud-confidence-bar">
          <div class="hud-confidence-fill" id="hud-confidence-fill" style="width: 0%; background: #334455;"></div>
        </div>
      </div>

      <!-- Dưới-phải: chế độ cảm biến -->
      <div class="hud-bottom-right">
        <div class="hud-mode-badge mock" id="hud-mode-badge">MOCK</div>
        <div class="hud-row" style="margin-top: 4px;">
          <span class="hud-label">WiFi DensePose</span>
        </div>
      </div>

      <!-- Gợi ý điều khiển -->
      <div class="hud-controls-hint">
        Kéo để xoay | Cuộn để phóng | Nhấp phải để dịch chuyển
      </div>
    `;

    this.container.style.position = 'relative';
    this.container.appendChild(this.hudElement);

    // Lưu cache tham chiếu DOM
    this._els = {
      banner: this.hudElement.querySelector('#hud-banner'),
      statusDot: this.hudElement.querySelector('#hud-status-dot'),
      connStatus: this.hudElement.querySelector('#hud-conn-status'),
      latency: this.hudElement.querySelector('#hud-latency'),
      msgCount: this.hudElement.querySelector('#hud-msg-count'),
      uptime: this.hudElement.querySelector('#hud-uptime'),
      fps: this.hudElement.querySelector('#hud-fps'),
      frameTime: this.hudElement.querySelector('#hud-frame-time'),
      personCount: this.hudElement.querySelector('#hud-person-count'),
      confidence: this.hudElement.querySelector('#hud-confidence'),
      confidenceFill: this.hudElement.querySelector('#hud-confidence-fill'),
      modeBadge: this.hudElement.querySelector('#hud-mode-badge')
    };
  }

  // Cập nhật trạng thái từ dữ liệu bên ngoài
  updateState(newState) {
    Object.assign(this.state, newState);
    this._render();
  }

  // Theo dõi FPS - gọi mỗi khung hình
  tickFPS() {
    const now = performance.now();
    this._fpsFrames.push(now);

    // Chỉ giữ khung hình trong giây cuối
    while (this._fpsFrames.length > 0 && this._fpsFrames[0] < now - 1000) {
      this._fpsFrames.shift();
    }

    // Cập nhật hiển thị FPS tối đa 4 lần mỗi giây
    if (now - this._lastFpsUpdate > 250) {
      this.state.fps = this._fpsFrames.length;
      const frameTime = this._fpsFrames.length > 1
        ? (now - this._fpsFrames[0]) / (this._fpsFrames.length - 1)
        : 0;
      this._lastFpsUpdate = now;

      // Cập nhật phần tử FPS
      this._els.fps.textContent = `${this.state.fps} FPS`;
      this._els.fps.className = 'hud-fps ' + (
        this.state.fps >= 50 ? 'high' : this.state.fps >= 25 ? 'mid' : 'low'
      );
      this._els.frameTime.textContent = `${frameTime.toFixed(1)} ms`;
    }
  }

  _render() {
    const { state } = this;

    // Banner
    if (state.isRealData) {
      this._els.banner.textContent = 'DỮ LIỆU THỰC - LUỒNG TRỰC TIẾP';
      this._els.banner.className = 'hud-banner real';
    } else {
      this._els.banner.textContent = 'DỮ LIỆU GIẢ LẬP - CHẾ ĐỘ DEMO';
      this._els.banner.className = 'hud-banner mock';
    }

    // Trạng thái kết nối
    this._els.statusDot.className = `hud-status-dot ${state.connectionStatus}`;
    const statusText = {
      connected: 'Đã kết nối',
      disconnected: 'Ngắt kết nối',
      connecting: 'Đang kết nối...',
      error: 'Lỗi'
    };
    this._els.connStatus.textContent = statusText[state.connectionStatus] || 'Không xác định';

    // Độ trễ
    this._els.latency.textContent = state.latency > 0 ? `${state.latency.toFixed(0)} ms` : '-- ms';

    // Tin nhắn
    this._els.msgCount.textContent = state.messageCount.toLocaleString();

    // Thời gian hoạt động
    const uptimeSec = Math.floor(state.uptime);
    if (uptimeSec < 60) {
      this._els.uptime.textContent = `${uptimeSec}s`;
    } else if (uptimeSec < 3600) {
      this._els.uptime.textContent = `${Math.floor(uptimeSec / 60)}m ${uptimeSec % 60}s`;
    } else {
      const h = Math.floor(uptimeSec / 3600);
      const m = Math.floor((uptimeSec % 3600) / 60);
      this._els.uptime.textContent = `${h}h ${m}m`;
    }

    // Số người
    this._els.personCount.textContent = state.personCount;
    this._els.personCount.style.color = state.personCount > 0 ? '#00ff88' : '#556677';

    // Độ tin cậy
    const confPct = (state.confidence * 100).toFixed(1);
    this._els.confidence.textContent = `${confPct}%`;
    this._els.confidenceFill.style.width = `${state.confidence * 100}%`;
    // Nhiệt màu: đỏ (thấp) -> vàng (trung bình) -> xanh (cao)
    const confHue = state.confidence * 120; // 0=red, 60=yellow, 120=green
    this._els.confidenceFill.style.background = `hsl(${confHue}, 100%, 45%)`;

    // Chế độ cảm biến
    const modeLower = (state.sensingMode || 'Mock').toLowerCase();
    this._els.modeBadge.textContent = state.sensingMode.toUpperCase();
    this._els.modeBadge.className = `hud-mode-badge ${modeLower}`;
  }

  dispose() {
    if (this.hudElement && this.hudElement.parentNode) {
      this.hudElement.parentNode.removeChild(this.hudElement);
    }
  }
}
