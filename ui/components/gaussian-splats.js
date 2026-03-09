/**
 * Bộ Kết xuất Gaussian Splat cho Trực quan hoá Cảm biến WiFi
 *
 * Kết xuất trường tín hiệu 3D sử dụng Points của Three.js với ShaderMaterial tuỳ chỉnh.
 * Mỗi "splat" là một đĩa trên không gian màn hình có kích thước, màu sắc và độ mờ
 * được điều khiển bởi dữ liệu cảm biến:
 *   - Kích thước: phương sai tín hiệu / biên độ nhiễu loạn
 *   - Màu sắc: xanh dương (yên tĩnh) -> xanh lá (có mặt) -> đỏ (chuyển động tích cực)
 *   - Độ mờ: độ tin cậy phân loại
 */

// Sử dụng THREE toàn cục từ CDN (được tải trong SensingTab)
const getThree = () => window.THREE;

// ---- Shader Splat Tuỳ chỉnh ------------------------------------------------

const SPLAT_VERTEX = `
  attribute float splatSize;
  attribute vec3  splatColor;
  attribute float splatOpacity;

  varying vec3  vColor;
  varying float vOpacity;

  void main() {
    vColor   = splatColor;
    vOpacity = splatOpacity;

    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = splatSize * (300.0 / -mvPosition.z);
    gl_Position  = projectionMatrix * mvPosition;
  }
`;

const SPLAT_FRAGMENT = `
  varying vec3  vColor;
  varying float vOpacity;

  void main() {
    // Đĩa mép mềm hình tròn
    float dist = length(gl_PointCoord - vec2(0.5));
    if (dist > 0.5) discard;
    float alpha = smoothstep(0.5, 0.2, dist) * vOpacity;
    gl_FragColor = vec4(vColor, alpha);
  }
`;

// ---- Hàm trợ giúp Màu sắc -------------------------------------------------------

/** Ánh xạ giá trị 0-1 sang gradient xanh dương -> xanh lá -> đỏ */
function valueToColor(v) {
  const clamped = Math.max(0, Math.min(1, v));
  // xanh_dương(0) -> lục_lam(0.25) -> xanh_lá(0.5) -> vàng(0.75) -> đỏ(1)
  let r, g, b;
  if (clamped < 0.5) {
    const t = clamped * 2;
    r = 0;
    g = t;
    b = 1 - t;
  } else {
    const t = (clamped - 0.5) * 2;
    r = t;
    g = 1 - t;
    b = 0;
  }
  return [r, g, b];
}

// ---- GaussianSplatRenderer -----------------------------------------------

export class GaussianSplatRenderer {
  /**
   * @param {HTMLElement} container - Phần tử DOM để gắn bộ kết xuất
   * @param {object}      [opts]
   * @param {number}      [opts.width]  - chiều rộng canvas (mặc định chiều rộng container)
   * @param {number}      [opts.height] - chiều cao canvas (mặc định 500)
   */
  constructor(container, opts = {}) {
    const THREE = getThree();
    if (!THREE) throw new Error('Three.js not loaded');

    this.container = container;
    this.width  = opts.width  || container.clientWidth || 800;
    this.height = opts.height || 500;

    // Cảnh
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0a12);

    // Camera — phối cảnh nhìn xuống phòng
    this.camera = new THREE.PerspectiveCamera(55, this.width / this.height, 0.1, 200);
    this.camera.position.set(0, 14, 14);
    this.camera.lookAt(0, 0, 0);

    // Bộ kết xuất
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    // Lưới & phòng
    this._createRoom(THREE);

    // Splat trường tín hiệu (20x20 = 400 điểm trên mặt phẳng sàn)
    this.gridSize = 20;
    this._createFieldSplats(THREE);

    // Đánh dấu nút (vị trí ESP32 / router)
    this._createNodeMarkers(THREE);

    // Đốm nhiễu loạn cơ thể
    this._createBodyBlob(THREE);

    // Xoay chuột kiểu quỹ đạo đơn giản
    this._setupMouseControls();

    // Trạng thái hoạt hình
    this._animFrame = null;
    this._lastData = null;

    // Bắt đầu vòng kết xuất
    this._animate();
  }

  // ---- Thiết lập cảnh -------------------------------------------------------

  _createRoom(THREE) {
    // Lưới sàn
    const grid = new THREE.GridHelper(20, 20, 0x1a3a4a, 0x0d1f28);
    this.scene.add(grid);

    // Khung dây ranh giới phòng
    const boxGeo = new THREE.BoxGeometry(20, 6, 20);
    const edges  = new THREE.EdgesGeometry(boxGeo);
    const line   = new THREE.LineSegments(
      edges,
      new THREE.LineBasicMaterial({ color: 0x1a4a5a, opacity: 0.3, transparent: true })
    );
    line.position.y = 3;
    this.scene.add(line);
  }

  _createFieldSplats(THREE) {
    const count = this.gridSize * this.gridSize;

    const positions = new Float32Array(count * 3);
    const sizes     = new Float32Array(count);
    const colors    = new Float32Array(count * 3);
    const opacities = new Float32Array(count);

    // Đặt splat trên mặt phẳng sàn (y = 0.05 nằm ngay trên lưới)
    for (let iz = 0; iz < this.gridSize; iz++) {
      for (let ix = 0; ix < this.gridSize; ix++) {
        const idx = iz * this.gridSize + ix;
        positions[idx * 3 + 0] = (ix - this.gridSize / 2) + 0.5; // x
        positions[idx * 3 + 1] = 0.05;                            // y
        positions[idx * 3 + 2] = (iz - this.gridSize / 2) + 0.5; // z

        sizes[idx]     = 1.5;
        colors[idx * 3]     = 0.1;
        colors[idx * 3 + 1] = 0.2;
        colors[idx * 3 + 2] = 0.6;
        opacities[idx] = 0.15;
      }
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position',    new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('splatSize',   new THREE.BufferAttribute(sizes, 1));
    geo.setAttribute('splatColor',  new THREE.BufferAttribute(colors, 3));
    geo.setAttribute('splatOpacity',new THREE.BufferAttribute(opacities, 1));

    const mat = new THREE.ShaderMaterial({
      vertexShader:   SPLAT_VERTEX,
      fragmentShader: SPLAT_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.fieldPoints = new THREE.Points(geo, mat);
    this.scene.add(this.fieldPoints);
  }

  _createNodeMarkers(THREE) {
    // Router ở giữa — hình cầu xanh lá
    const routerGeo = new THREE.SphereGeometry(0.3, 16, 16);
    const routerMat = new THREE.MeshBasicMaterial({ color: 0x00ff88, transparent: true, opacity: 0.8 });
    this.routerMarker = new THREE.Mesh(routerGeo, routerMat);
    this.routerMarker.position.set(0, 0.5, 0);
    this.scene.add(this.routerMarker);

    // Nút ESP32 — hình cầu lục lam (vị trí mặc định, cập nhật từ dữ liệu)
    const nodeGeo = new THREE.SphereGeometry(0.25, 16, 16);
    const nodeMat = new THREE.MeshBasicMaterial({ color: 0x00ccff, transparent: true, opacity: 0.8 });
    this.nodeMarker = new THREE.Mesh(nodeGeo, nodeMat);
    this.nodeMarker.position.set(2, 0.5, 1.5);
    this.scene.add(this.nodeMarker);
  }

  _createBodyBlob(THREE) {
    // Cụm splat đại diện cho nhiễu loạn cơ thể
    const count = 64;
    const positions = new Float32Array(count * 3);
    const sizes     = new Float32Array(count);
    const colors    = new Float32Array(count * 3);
    const opacities = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      // Phân bố hình cầu ngẫu nhiên
      const theta = Math.random() * Math.PI * 2;
      const phi   = Math.acos(2 * Math.random() - 1);
      const r     = Math.random() * 1.5;
      positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi) + 2;
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);

      sizes[i] = 2 + Math.random() * 3;
      colors[i * 3]     = 0.2;
      colors[i * 3 + 1] = 0.8;
      colors[i * 3 + 2] = 0.3;
      opacities[i] = 0.0; // ẩn cho đến khi phát hiện sự hiện diện
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position',    new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('splatSize',   new THREE.BufferAttribute(sizes, 1));
    geo.setAttribute('splatColor',  new THREE.BufferAttribute(colors, 3));
    geo.setAttribute('splatOpacity',new THREE.BufferAttribute(opacities, 1));

    const mat = new THREE.ShaderMaterial({
      vertexShader:   SPLAT_VERTEX,
      fragmentShader: SPLAT_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.bodyBlob = new THREE.Points(geo, mat);
    this.scene.add(this.bodyBlob);
  }

  // ---- Điều khiển chuột (quỹ đạo đơn giản) -------------------------------------

  _setupMouseControls() {
    let isDragging = false;
    let prevX = 0, prevY = 0;
    let azimuth = 0, elevation = 55;
    const radius = 20;

    const updateCamera = () => {
      const phi   = (elevation * Math.PI) / 180;
      const theta = (azimuth * Math.PI) / 180;
      this.camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta)
      );
      this.camera.lookAt(0, 0, 0);
    };

    const canvas = this.renderer.domElement;
    canvas.addEventListener('mousedown', (e) => {
      isDragging = true;
      prevX = e.clientX;
      prevY = e.clientY;
    });
    canvas.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      azimuth   += (e.clientX - prevX) * 0.4;
      elevation -= (e.clientY - prevY) * 0.4;
      elevation  = Math.max(15, Math.min(85, elevation));
      prevX = e.clientX;
      prevY = e.clientY;
      updateCamera();
    });
    canvas.addEventListener('mouseup',   () => { isDragging = false; });
    canvas.addEventListener('mouseleave',() => { isDragging = false; });

    // Cuộn để phóng to/thu nhỏ
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 1.05 : 0.95;
      this.camera.position.multiplyScalar(delta);
      this.camera.position.clampLength(8, 40);
    }, { passive: false });

    updateCamera();
  }

  // ---- Cập nhật dữ liệu -------------------------------------------------------

  /**
   * Cập nhật trực quan hoá với dữ liệu cảm biến mới.
   * @param {object} data - JSON sensing_update từ ws_server
   */
  update(data) {
    this._lastData = data;
    if (!data) return;

    const features = data.features || {};
    const classification = data.classification || {};
    const signalField = data.signal_field || {};
    const nodes = data.nodes || [];

    // -- Cập nhật splat trường tín hiệu ----------------------------------------
    if (signalField.values && this.fieldPoints) {
      const geo    = this.fieldPoints.geometry;
      const clr    = geo.attributes.splatColor.array;
      const sizes  = geo.attributes.splatSize.array;
      const opac   = geo.attributes.splatOpacity.array;
      const vals   = signalField.values;
      const count  = Math.min(vals.length, this.gridSize * this.gridSize);

      for (let i = 0; i < count; i++) {
        const v = vals[i];
        const [r, g, b] = valueToColor(v);
        clr[i * 3]     = r;
        clr[i * 3 + 1] = g;
        clr[i * 3 + 2] = b;
        sizes[i] = 1.0 + v * 4.0;
        opac[i]  = 0.1 + v * 0.6;
      }

      geo.attributes.splatColor.needsUpdate  = true;
      geo.attributes.splatSize.needsUpdate   = true;
      geo.attributes.splatOpacity.needsUpdate = true;
    }

    // -- Cập nhật đốm cơ thể --------------------------------------------------
    if (this.bodyBlob) {
      const bGeo  = this.bodyBlob.geometry;
      const bOpac = bGeo.attributes.splatOpacity.array;
      const bClr  = bGeo.attributes.splatColor.array;
      const bSize = bGeo.attributes.splatSize.array;
      const bPos  = bGeo.attributes.position.array;

      const presence   = classification.presence || false;
      const motionLvl  = classification.motion_level || 'absent';
      const confidence = classification.confidence || 0;
      const breathing  = features.breathing_band_power || 0;

      // Nhịp hô hấp
      const breathPulse = 1.0 + Math.sin(Date.now() * 0.004) * Math.min(breathing * 3, 0.4);

      for (let i = 0; i < bOpac.length; i++) {
        if (presence) {
          bOpac[i] = confidence * 0.4;

          // Màu theo mức chuyển động
          if (motionLvl === 'active') {
            bClr[i * 3]     = 1.0;
            bClr[i * 3 + 1] = 0.2;
            bClr[i * 3 + 2] = 0.1;
          } else {
            bClr[i * 3]     = 0.1;
            bClr[i * 3 + 1] = 0.8;
            bClr[i * 3 + 2] = 0.4;
          }

          bSize[i] = (2 + Math.random() * 2) * breathPulse;
        } else {
          bOpac[i] = 0.0;
        }
      }

      bGeo.attributes.splatOpacity.needsUpdate = true;
      bGeo.attributes.splatColor.needsUpdate   = true;
      bGeo.attributes.splatSize.needsUpdate    = true;
    }

    // -- Cập nhật vị trí nút ---------------------------------------------
    if (nodes.length > 0 && nodes[0].position) {
      const pos = nodes[0].position;
      this.nodeMarker.position.set(pos[0], 0.5, pos[2]);
    }
  }

  // ---- Vòng kết xuất -------------------------------------------------------

  _animate() {
    this._animFrame = requestAnimationFrame(() => this._animate());

    // Nhịp phát sáng nhẹ nhàng router
    if (this.routerMarker) {
      const pulse = 0.6 + 0.3 * Math.sin(Date.now() * 0.003);
      this.routerMarker.material.opacity = pulse;
    }

    this.renderer.render(this.scene, this.camera);
  }

  // ---- Thay đổi kích thước / dọn dẹp --------------------------------------------------

  resize(width, height) {
    this.width  = width;
    this.height = height;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  dispose() {
    if (this._animFrame) {
      cancelAnimationFrame(this._animFrame);
    }
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
  }
}
