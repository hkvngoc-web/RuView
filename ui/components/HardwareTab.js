// Thành phần Tab Phần Cứng

export class HardwareTab {
  constructor(containerElement) {
    this.container = containerElement;
    this.antennas = [];
    this.csiUpdateInterval = null;
    this.isActive = false;
  }

  // Khởi tạo thành phần
  init() {
    this.setupAntennas();
    this.startCSISimulation();
  }

  // Thiết lập tương tác ăng-ten
  setupAntennas() {
    this.antennas = Array.from(this.container.querySelectorAll('.antenna'));
    
    this.antennas.forEach(antenna => {
      antenna.addEventListener('click', () => {
        antenna.classList.toggle('active');
        this.updateCSIDisplay();
      });
    });
  }

  // Bắt đầu mô phỏng CSI
  startCSISimulation() {
    // Cập nhật ban đầu
    this.updateCSIDisplay();

    // Thiết lập cập nhật định kỳ
    this.csiUpdateInterval = setInterval(() => {
      if (this.hasActiveAntennas()) {
        this.updateCSIDisplay();
      }
    }, 1000);
  }

  // Kiểm tra xem có ăng-ten nào đang hoạt động không
  hasActiveAntennas() {
    return this.antennas.some(antenna => antenna.classList.contains('active'));
  }

  // Cập nhật hiển thị CSI
  updateCSIDisplay() {
    const activeAntennas = this.antennas.filter(a => a.classList.contains('active'));
    const isActive = activeAntennas.length > 0;
    
    // Lấy các phần tử hiển thị
    const amplitudeFill = this.container.querySelector('.csi-fill.amplitude');
    const phaseFill = this.container.querySelector('.csi-fill.phase');
    const amplitudeValue = this.container.querySelector('.csi-row:first-child .csi-value');
    const phaseValue = this.container.querySelector('.csi-row:last-child .csi-value');
    
    if (!isActive) {
      // Đặt về không khi không có ăng-ten hoạt động
      if (amplitudeFill) amplitudeFill.style.width = '0%';
      if (phaseFill) phaseFill.style.width = '0%';
      if (amplitudeValue) amplitudeValue.textContent = '0.00';
      if (phaseValue) phaseValue.textContent = '0.0π';
      return;
    }
    
    // Tạo giá trị CSI thực tế dựa trên ăng-ten đang hoạt động
    const txCount = activeAntennas.filter(a => a.classList.contains('tx')).length;
    const rxCount = activeAntennas.filter(a => a.classList.contains('rx')).length;
    
    // Biên độ tăng khi có nhiều ăng-ten hoạt động hơn
    const baseAmplitude = 0.3 + (txCount * 0.1) + (rxCount * 0.05);
    const amplitude = Math.min(0.95, baseAmplitude + (Math.random() * 0.1 - 0.05));
    
    // Pha biến thiên nhiều hơn khi có nhiều ăng-ten
    const phaseVariation = 0.5 + (activeAntennas.length * 0.1);
    const phase = 0.5 + Math.random() * phaseVariation;
    
    // Cập nhật hiển thị
    if (amplitudeFill) {
      amplitudeFill.style.width = `${amplitude * 100}%`;
      amplitudeFill.style.transition = 'width 0.5s ease';
    }
    
    if (phaseFill) {
      phaseFill.style.width = `${phase * 50}%`;
      phaseFill.style.transition = 'width 0.5s ease';
    }
    
    if (amplitudeValue) {
      amplitudeValue.textContent = amplitude.toFixed(2);
    }
    
    if (phaseValue) {
      phaseValue.textContent = `${phase.toFixed(1)}π`;
    }
    
    // Cập nhật trực quan mảng ăng-ten
    this.updateAntennaArray(activeAntennas);
  }

  // Update antenna array visualization
  updateAntennaArray(activeAntennas) {
    const arrayStatus = this.container.querySelector('.array-status');
    if (!arrayStatus) return;
    
    const txActive = activeAntennas.filter(a => a.classList.contains('tx')).length;
    const rxActive = activeAntennas.filter(a => a.classList.contains('rx')).length;
    
    // Xóa và xây dựng lại bằng phương pháp DOM an toàn để ngăn XSS
    arrayStatus.innerHTML = '';
    
    const createInfoDiv = (label, value) => {
      const div = document.createElement('div');
      div.className = 'array-info';
      
      const labelSpan = document.createElement('span');
      labelSpan.className = 'info-label';
      labelSpan.textContent = label;
      
      const valueSpan = document.createElement('span');
      valueSpan.className = 'info-value';
      valueSpan.textContent = value;
      
      div.appendChild(labelSpan);
      div.appendChild(valueSpan);
      return div;
    };
    
    arrayStatus.appendChild(createInfoDiv('TX Hoạt động:', `${txActive}/3`));
    arrayStatus.appendChild(createInfoDiv('RX Hoạt động:', `${rxActive}/6`));
    arrayStatus.appendChild(createInfoDiv('Chất lượng tín hiệu:', `${this.calculateSignalQuality(txActive, rxActive)}%`));
  }

  // Tính chất lượng tín hiệu dựa trên ăng-ten đang hoạt động
  calculateSignalQuality(txCount, rxCount) {
    if (txCount === 0 || rxCount === 0) return 0;
    
    const txRatio = txCount / 3;
    const rxRatio = rxCount / 6;
    const quality = (txRatio * 0.4 + rxRatio * 0.6) * 100;
    
    return Math.round(quality);
  }

  // Bật/tắt tất cả ăng-ten
  toggleAllAntennas(active) {
    this.antennas.forEach(antenna => {
      antenna.classList.toggle('active', active);
    });
    this.updateCSIDisplay();
  }

  // Đặt lại cấu hình ăng-ten
  resetAntennas() {
    // Đặt cấu hình mặc định (tất cả hoạt động)
    this.antennas.forEach(antenna => {
      antenna.classList.add('active');
    });
    this.updateCSIDisplay();
  }

  // Dọn dẹp
  dispose() {
    if (this.csiUpdateInterval) {
      clearInterval(this.csiUpdateInterval);
      this.csiUpdateInterval = null;
    }
    
    this.antennas.forEach(antenna => {
      antenna.removeEventListener('click', this.toggleAntenna);
    });
  }
}