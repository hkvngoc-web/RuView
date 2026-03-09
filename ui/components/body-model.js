// Mô hình Cơ thể Con người 3D - Trực quan hoá WiFi DensePose
// Ánh xạ 24 bộ phận cơ thể DensePose sang vị trí 3D sử dụng hình học đơn giản

export class BodyModel {
  // ID bộ phận cơ thể DensePose (1-24)
  static PARTS = {
    TORSO_BACK: 1,
    TORSO_FRONT: 2,
    RIGHT_HAND: 3,
    LEFT_HAND: 4,
    LEFT_FOOT: 5,
    RIGHT_FOOT: 6,
    RIGHT_UPPER_LEG_BACK: 7,
    LEFT_UPPER_LEG_BACK: 8,
    RIGHT_UPPER_LEG_FRONT: 9,
    LEFT_UPPER_LEG_FRONT: 10,
    RIGHT_LOWER_LEG_BACK: 11,
    LEFT_LOWER_LEG_BACK: 12,
    RIGHT_LOWER_LEG_FRONT: 13,
    LEFT_LOWER_LEG_FRONT: 14,
    LEFT_UPPER_ARM_FRONT: 15,
    RIGHT_UPPER_ARM_FRONT: 16,
    LEFT_UPPER_ARM_BACK: 17,
    RIGHT_UPPER_ARM_BACK: 18,
    LEFT_LOWER_ARM_FRONT: 19,
    RIGHT_LOWER_ARM_FRONT: 20,
    LEFT_LOWER_ARM_BACK: 21,
    RIGHT_LOWER_ARM_BACK: 22,
    HEAD_RIGHT: 23,
    HEAD_LEFT: 24
  };

  // Các cặp kết nối bộ xương để vẽ xương
  static BONE_CONNECTIONS = [
    // Cột sống
    ['pelvis', 'spine'],
    ['spine', 'chest'],
    ['chest', 'neck'],
    ['neck', 'head'],
    // Tay trái
    ['chest', 'left_shoulder'],
    ['left_shoulder', 'left_elbow'],
    ['left_elbow', 'left_wrist'],
    // Tay phải
    ['chest', 'right_shoulder'],
    ['right_shoulder', 'right_elbow'],
    ['right_elbow', 'right_wrist'],
    // Chân trái
    ['pelvis', 'left_hip'],
    ['left_hip', 'left_knee'],
    ['left_knee', 'left_ankle'],
    // Chân phải
    ['pelvis', 'right_hip'],
    ['right_hip', 'right_knee'],
    ['right_knee', 'right_ankle']
  ];

  constructor() {
    this.group = new THREE.Group();
    this.group.name = 'body-model';

    // Lưu tham chiếu đến mesh bộ phận cơ thể để cập nhật
    this.joints = {};
    this.limbs = {};
    this.bones = [];
    this.partMeshes = {};

    // Trạng thái tư thế hiện tại
    this.confidence = 0;
    this.isVisible = false;
    this.targetPositions = {};
    this.currentPositions = {};

    // Vật liệu
    this._materials = this._createMaterials();

    // Xây dựng cơ thể
    this._buildBody();

    // Trạng thái ban đầu ẩn
    this.group.visible = false;
  }

  _createMaterials() {
    // Màu dựa trên độ tin cậy: xanh lạnh (thấp) -> cam ấm (cao)
    const jointMat = new THREE.MeshPhongMaterial({
      color: 0x00aaff,
      emissive: 0x003366,
      emissiveIntensity: 0.3,
      shininess: 60,
      transparent: true,
      opacity: 0.9
    });

    const limbMat = new THREE.MeshPhongMaterial({
      color: 0x0088dd,
      emissive: 0x002244,
      emissiveIntensity: 0.2,
      shininess: 40,
      transparent: true,
      opacity: 0.85
    });

    const headMat = new THREE.MeshPhongMaterial({
      color: 0x00ccff,
      emissive: 0x004466,
      emissiveIntensity: 0.4,
      shininess: 80,
      transparent: true,
      opacity: 0.9
    });

    const boneMat = new THREE.LineBasicMaterial({
      color: 0x00ffcc,
      transparent: true,
      opacity: 0.6,
      linewidth: 2
    });

    return { joint: jointMat, limb: limbMat, head: headMat, bone: boneMat };
  }

  _buildBody() {
    // Vị trí khớp T-pose mặc định (hệ toạ độ Y-hướng lên)
    // Chiều cao tính bằng mét, tỷ lệ cơ thể người xấp xỉ (cao 1.75m)
    const defaultJoints = {
      head:            { x: 0, y: 1.70, z: 0 },
      neck:            { x: 0, y: 1.55, z: 0 },
      chest:           { x: 0, y: 1.35, z: 0 },
      spine:           { x: 0, y: 1.10, z: 0 },
      pelvis:          { x: 0, y: 0.90, z: 0 },
      left_shoulder:   { x: -0.22, y: 1.48, z: 0 },
      right_shoulder:  { x:  0.22, y: 1.48, z: 0 },
      left_elbow:      { x: -0.45, y: 1.20, z: 0 },
      right_elbow:     { x:  0.45, y: 1.20, z: 0 },
      left_wrist:      { x: -0.55, y: 0.95, z: 0 },
      right_wrist:     { x:  0.55, y: 0.95, z: 0 },
      left_hip:        { x: -0.12, y: 0.88, z: 0 },
      right_hip:       { x:  0.12, y: 0.88, z: 0 },
      left_knee:       { x: -0.13, y: 0.50, z: 0 },
      right_knee:      { x:  0.13, y: 0.50, z: 0 },
      left_ankle:      { x: -0.13, y: 0.08, z: 0 },
      right_ankle:     { x:  0.13, y: 0.08, z: 0 }
    };

    // Tạo các khối cầu khớp
    const jointGeom = new THREE.SphereGeometry(0.035, 12, 12);
    const headGeom = new THREE.SphereGeometry(0.10, 16, 16);

    for (const [name, pos] of Object.entries(defaultJoints)) {
      const geom = name === 'head' ? headGeom : jointGeom;
      const mat = name === 'head' ? this._materials.head.clone() : this._materials.joint.clone();
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(pos.x, pos.y, pos.z);
      mesh.castShadow = true;
      mesh.name = `joint-${name}`;
      this.group.add(mesh);
      this.joints[name] = mesh;
      this.currentPositions[name] = { ...pos };
      this.targetPositions[name] = { ...pos };
    }

    // Tạo các hình trụ chi nối các khớp
    const limbDefs = [
      { name: 'torso_upper', from: 'chest', to: 'neck', radius: 0.06 },
      { name: 'torso_lower', from: 'spine', to: 'chest', radius: 0.07 },
      { name: 'hip_section', from: 'pelvis', to: 'spine', radius: 0.065 },
      { name: 'left_upper_arm', from: 'left_shoulder', to: 'left_elbow', radius: 0.03 },
      { name: 'right_upper_arm', from: 'right_shoulder', to: 'right_elbow', radius: 0.03 },
      { name: 'left_forearm', from: 'left_elbow', to: 'left_wrist', radius: 0.025 },
      { name: 'right_forearm', from: 'right_elbow', to: 'right_wrist', radius: 0.025 },
      { name: 'left_thigh', from: 'left_hip', to: 'left_knee', radius: 0.04 },
      { name: 'right_thigh', from: 'right_hip', to: 'right_knee', radius: 0.04 },
      { name: 'left_shin', from: 'left_knee', to: 'left_ankle', radius: 0.03 },
      { name: 'right_shin', from: 'right_knee', to: 'right_ankle', radius: 0.03 },
      { name: 'left_clavicle', from: 'chest', to: 'left_shoulder', radius: 0.025 },
      { name: 'right_clavicle', from: 'chest', to: 'right_shoulder', radius: 0.025 },
      { name: 'left_pelvis', from: 'pelvis', to: 'left_hip', radius: 0.03 },
      { name: 'right_pelvis', from: 'pelvis', to: 'right_hip', radius: 0.03 },
      { name: 'neck_head', from: 'neck', to: 'head', radius: 0.025 }
    ];

    for (const def of limbDefs) {
      const limb = this._createLimb(def.from, def.to, def.radius);
      limb.name = `limb-${def.name}`;
      this.group.add(limb);
      this.limbs[def.name] = { mesh: limb, from: def.from, to: def.to, radius: def.radius };
    }

    // Tạo các đường xương bộ xương
    this._createBoneLines();

    // Tạo lưới phát sáng bộ phận cơ thể cho kích hoạt phần DensePose
    this._createPartGlows();
  }

  _createLimb(fromName, toName, radius) {
    const from = this.currentPositions[fromName];
    const to = this.currentPositions[toName];
    const dir = new THREE.Vector3(to.x - from.x, to.y - from.y, to.z - from.z);
    const length = dir.length();

    const geom = new THREE.CylinderGeometry(radius, radius, length, 8, 1);
    const mat = this._materials.limb.clone();
    const mesh = new THREE.Mesh(geom, mat);
    mesh.castShadow = true;

    this._positionLimb(mesh, from, to, length);
    return mesh;
  }

  _positionLimb(mesh, from, to, length) {
    const mid = {
      x: (from.x + to.x) / 2,
      y: (from.y + to.y) / 2,
      z: (from.z + to.z) / 2
    };
    mesh.position.set(mid.x, mid.y, mid.z);

    const dir = new THREE.Vector3(to.x - from.x, to.y - from.y, to.z - from.z).normalize();
    const up = new THREE.Vector3(0, 1, 0);

    if (Math.abs(dir.dot(up)) < 0.999) {
      const quat = new THREE.Quaternion();
      quat.setFromUnitVectors(up, dir);
      mesh.quaternion.copy(quat);
    }

    // Cập nhật chiều dài hình trụ
    mesh.scale.y = length / mesh.geometry.parameters.height;
  }

  _createBoneLines() {
    const boneGeom = new THREE.BufferGeometry();
    // Chúng ta sẽ cập nhật vị trí mỗi khung hình
    const positions = new Float32Array(BodyModel.BONE_CONNECTIONS.length * 6);
    boneGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const boneLine = new THREE.LineSegments(boneGeom, this._materials.bone);
    boneLine.name = 'skeleton-bones';
    this.group.add(boneLine);
    this._boneLine = boneLine;
  }

  _createPartGlows() {
    // Tạo chỉ báo phát sáng nhẹ cho mỗi vùng cơ thể DensePose
    // Chúng sáng lên dựa trên bộ phận nào đang được cảm biến
    const partRegions = {
      torso: { pos: [0, 1.2, 0], scale: [0.2, 0.3, 0.1], parts: [1, 2] },
      left_upper_arm: { pos: [-0.35, 1.35, 0], scale: [0.06, 0.15, 0.06], parts: [15, 17] },
      right_upper_arm: { pos: [0.35, 1.35, 0], scale: [0.06, 0.15, 0.06], parts: [16, 18] },
      left_lower_arm: { pos: [-0.50, 1.08, 0], scale: [0.05, 0.13, 0.05], parts: [19, 21] },
      right_lower_arm: { pos: [0.50, 1.08, 0], scale: [0.05, 0.13, 0.05], parts: [20, 22] },
      left_hand: { pos: [-0.55, 0.95, 0], scale: [0.04, 0.04, 0.03], parts: [4] },
      right_hand: { pos: [0.55, 0.95, 0], scale: [0.04, 0.04, 0.03], parts: [3] },
      left_upper_leg: { pos: [-0.13, 0.70, 0], scale: [0.07, 0.18, 0.07], parts: [8, 10] },
      right_upper_leg: { pos: [0.13, 0.70, 0], scale: [0.07, 0.18, 0.07], parts: [7, 9] },
      left_lower_leg: { pos: [-0.13, 0.30, 0], scale: [0.05, 0.18, 0.05], parts: [12, 14] },
      right_lower_leg: { pos: [0.13, 0.30, 0], scale: [0.05, 0.18, 0.05], parts: [11, 13] },
      left_foot: { pos: [-0.13, 0.05, 0.03], scale: [0.04, 0.03, 0.06], parts: [5] },
      right_foot: { pos: [0.13, 0.05, 0.03], scale: [0.04, 0.03, 0.06], parts: [6] },
      head: { pos: [0, 1.72, 0], scale: [0.09, 0.10, 0.09], parts: [23, 24] }
    };

    const glowGeom = new THREE.SphereGeometry(1, 8, 8);

    for (const [name, region] of Object.entries(partRegions)) {
      const mat = new THREE.MeshBasicMaterial({
        color: 0x00ffcc,
        transparent: true,
        opacity: 0,
        depthWrite: false
      });
      const mesh = new THREE.Mesh(glowGeom, mat);
      mesh.position.set(...region.pos);
      mesh.scale.set(...region.scale);
      mesh.name = `part-glow-${name}`;
      this.group.add(mesh);
      for (const partId of region.parts) {
        this.partMeshes[partId] = mesh;
      }
    }
  }

  // Cập nhật tư thế từ mảng điểm khớp
  // keypoints: mảng {x, y, confidence} trong toạ độ chuẩn hoá [0,1]
  // Ánh xạ theo định dạng COCO 17-điểm khớp:
  // 0:mũi, 1:mắt_trái, 2:mắt_phải, 3:tai_trái, 4:tai_phải,
  // 5:vai_trái, 6:vai_phải, 7:khuỷu_trái, 8:khuỷu_phải,
  // 9:cổ_tay_trái, 10:cổ_tay_phải, 11:hông_trái, 12:hông_phải,
  // 13:gối_trái, 14:gối_phải, 15:mắt_cá_trái, 16:mắt_cá_phải
  updateFromKeypoints(keypoints, personConfidence) {
    if (!keypoints || keypoints.length < 17) return;

    this.confidence = personConfidence || 0;
    this.isVisible = this.confidence > 0.15;
    this.group.visible = this.isVisible;

    if (!this.isVisible) return;

    // Ánh xạ điểm khớp COCO sang vị trí khớp của chúng ta
    // Chuyển đổi toạ độ chuẩn hoá [0,1] sang không gian 3D căn giữa tại gốc
    // x: trái-phải (chuẩn hoá 0-1 ánh xạ xấp xỉ -2 đến 2 mét)
    // y: lên (tính từ vị trí tương đối)
    // z: độ sâu (suy ra từ một số heuristic)
    const kp = keypoints;

    const mapX = (val) => (val - 0.5) * 4;
    const mapZ = (val) => (val - 0.5) * 0.5; // Độ sâu nhẹ từ offset x

    // Hàm trợ giúp tính vị trí 3D từ điểm khớp COCO
    const kpPos = (idx, defaultY) => {
      const k = kp[idx];
      if (!k || k.confidence < 0.1) return null;
      return {
        x: mapX(k.x),
        y: defaultY !== undefined ? defaultY : (1.75 - k.y * 1.75),
        z: mapZ(k.x) * 0.2
      };
    };

    // Ước tính tỷ lệ dọc từ khoảng cách vai-đến-mắt-cá
    const lShoulder = kp[5], lAnkle = kp[15];
    let scale = 1.0;
    if (lShoulder && lAnkle && lShoulder.confidence > 0.2 && lAnkle.confidence > 0.2) {
      const pixelHeight = Math.abs(lAnkle.y - lShoulder.y);
      if (pixelHeight > 0.05) {
        scale = 0.85 / pixelHeight; // vai-đến-mắt-cá khoảng 0.85m theo tỷ lệ
      }
    }

    const mapY = (val) => {
      // Ánh xạ y từ toạ độ chuẩn hoá (0=trên, 1=dưới) sang y trong thế giới
      // Tìm điểm thấp nhất (mắt cá) và dùng làm tham chiếu mặt đất
      const groundRef = Math.max(
        (kp[15] && kp[15].confidence > 0.2) ? kp[15].y : 0.95,
        (kp[16] && kp[16].confidence > 0.2) ? kp[16].y : 0.95
      );
      return (groundRef - val) * scale * 1.75;
    };

    // Tính giữa-hông làm tâm cơ thể
    const midHipX = this._avgCoord(kp, [11, 12], 'x');
    const midHipY = this._avgCoord(kp, [11, 12], 'y');
    const centerX = midHipX !== null ? mapX(midHipX) : 0;

    // Ánh xạ tất cả các khớp
    const updateJoint = (name, idx, fallbackY) => {
      const k = kp[idx];
      if (k && k.confidence > 0.1) {
        this.targetPositions[name] = {
          x: mapX(k.x) - centerX,
          y: mapY(k.y),
          z: 0
        };
      }
    };

    // Đầu (trung bình của mũi, mắt, tai)
    const headX = this._avgCoord(kp, [0, 1, 2, 3, 4], 'x');
    const headY = this._avgCoord(kp, [0, 1, 2, 3, 4], 'y');
    if (headX !== null && headY !== null) {
      this.targetPositions.head = { x: mapX(headX) - centerX, y: mapY(headY) + 0.08, z: 0 };
    }

    // Cổ (giữa mũi và giữa-vai)
    const midShoulderX = this._avgCoord(kp, [5, 6], 'x');
    const midShoulderY = this._avgCoord(kp, [5, 6], 'y');
    const noseK = kp[0];
    if (midShoulderX !== null && noseK && noseK.confidence > 0.1) {
      this.targetPositions.neck = {
        x: mapX((midShoulderX + noseK.x) / 2) - centerX,
        y: mapY((midShoulderY + noseK.y) / 2),
        z: 0
      };
    }

    // Ngực (giữa-vai)
    if (midShoulderX !== null) {
      this.targetPositions.chest = {
        x: mapX(midShoulderX) - centerX,
        y: mapY(midShoulderY),
        z: 0
      };
    }

    // Cột sống (giữa ngực và xương chậu)
    if (midShoulderX !== null && midHipX !== null) {
      this.targetPositions.spine = {
        x: mapX((midShoulderX + midHipX) / 2) - centerX,
        y: mapY((midShoulderY + midHipY) / 2),
        z: 0
      };
    }

    // Xương chậu
    if (midHipX !== null) {
      this.targetPositions.pelvis = {
        x: mapX(midHipX) - centerX,
        y: mapY(midHipY),
        z: 0
      };
    }

    // Tay và chân
    updateJoint('left_shoulder', 5);
    updateJoint('right_shoulder', 6);
    updateJoint('left_elbow', 7);
    updateJoint('right_elbow', 8);
    updateJoint('left_wrist', 9);
    updateJoint('right_wrist', 10);
    updateJoint('left_hip', 11);
    updateJoint('right_hip', 12);
    updateJoint('left_knee', 13);
    updateJoint('right_knee', 14);
    updateJoint('left_ankle', 15);
    updateJoint('right_ankle', 16);

    // Điều chỉnh tất cả vị trí tương đối so với tâm
    // Áp dụng offset vị trí toàn cục (vị trí người trong phòng)
    // Dịch chuyển mô hình cơ thể đến vị trí trong thế giới
    this.group.position.x = centerX;
  }

  _avgCoord(keypoints, indices, coord) {
    let sum = 0;
    let count = 0;
    for (const idx of indices) {
      const k = keypoints[idx];
      if (k && k.confidence > 0.1) {
        sum += k[coord];
        count++;
      }
    }
    return count > 0 ? sum / count : null;
  }

  // Kích hoạt vùng bộ phận cơ thể DensePose (parts: mảng ID bộ phận với độ tin cậy)
  activateParts(partConfidences) {
    // partConfidences: { partId: độ_tin_cậy, ... }
    for (const [partId, mesh] of Object.entries(this.partMeshes)) {
      const conf = partConfidences[partId] || 0;
      mesh.material.opacity = conf * 0.4;
      // Nhiệt độ màu: xanh dương (thấp) -> lục lam -> xanh lá -> vàng -> cam (cao)
      const hue = (1 - conf) * 0.55; // 0.55 = xanh dương, 0 = đỏ
      mesh.material.color.setHSL(hue, 1.0, 0.5 + conf * 0.2);
    }
  }

  // Cập nhật hoạt hình mượt mà - gọi mỗi khung hình
  update(delta) {
    if (!this.isVisible) return;

    const lerpFactor = 1 - Math.pow(0.001, delta); // Nội suy hàm mũ mượt

    // Nội suy vị trí khớp
    for (const [name, joint] of Object.entries(this.joints)) {
      const target = this.targetPositions[name];
      const current = this.currentPositions[name];
      if (!target) continue;

      current.x += (target.x - current.x) * lerpFactor;
      current.y += (target.y - current.y) * lerpFactor;
      current.z += (target.z - current.z) * lerpFactor;

      joint.position.set(current.x, current.y, current.z);
    }

    // Cập nhật hình trụ chi
    for (const limb of Object.values(this.limbs)) {
      const from = this.currentPositions[limb.from];
      const to = this.currentPositions[limb.to];
      if (!from || !to) continue;

      const dir = new THREE.Vector3(to.x - from.x, to.y - from.y, to.z - from.z);
      const length = dir.length();
      if (length < 0.001) continue;

      this._positionLimb(limb.mesh, from, to, length);
    }

    // Cập nhật đường xương
    this._updateBoneLines();

    // Cập nhật màu vật liệu dựa trên độ tin cậy
    this._updateMaterialColors();
  }

  _updateBoneLines() {
    const posAttr = this._boneLine.geometry.getAttribute('position');
    const arr = posAttr.array;
    let i = 0;

    for (const [fromName, toName] of BodyModel.BONE_CONNECTIONS) {
      const from = this.currentPositions[fromName];
      const to = this.currentPositions[toName];
      if (from && to) {
        arr[i]     = from.x; arr[i + 1] = from.y; arr[i + 2] = from.z;
        arr[i + 3] = to.x;   arr[i + 4] = to.y;   arr[i + 5] = to.z;
      }
      i += 6;
    }
    posAttr.needsUpdate = true;
  }

  _updateMaterialColors() {
    // Độ tin cậy điều khiển nhiệt độ màu
    // Độ tin cậy thấp = xanh dương lạnh, cao = lục lam/xanh lá ấm
    const conf = this.confidence;
    const hue = 0.55 - conf * 0.25; // xanh dương -> lục lam -> xanh lá
    const saturation = 0.8;
    const lightness = 0.35 + conf * 0.2;

    for (const joint of Object.values(this.joints)) {
      if (joint.name !== 'joint-head') {
        joint.material.color.setHSL(hue, saturation, lightness);
        joint.material.emissive.setHSL(hue, saturation, lightness * 0.3);
        joint.material.opacity = 0.5 + conf * 0.5;
      }
    }

    for (const limb of Object.values(this.limbs)) {
      limb.mesh.material.color.setHSL(hue, saturation * 0.9, lightness * 0.9);
      limb.mesh.material.emissive.setHSL(hue, saturation * 0.9, lightness * 0.2);
      limb.mesh.material.opacity = 0.4 + conf * 0.5;
    }

    // Đầu
    const headJoint = this.joints.head;
    if (headJoint) {
      headJoint.material.color.setHSL(hue - 0.05, saturation, lightness + 0.1);
      headJoint.material.emissive.setHSL(hue - 0.05, saturation, lightness * 0.4);
      headJoint.material.opacity = 0.6 + conf * 0.4;
    }

    // Màu đường xương
    this._materials.bone.color.setHSL(hue + 0.1, 1.0, 0.5 + conf * 0.2);
    this._materials.bone.opacity = 0.3 + conf * 0.4;
  }

  // Đặt vị trí trong thế giới của mô hình cơ thể này (cho cảnh nhiều người)
  setWorldPosition(x, y, z) {
    this.group.position.set(x, y || 0, z || 0);
  }

  getGroup() {
    return this.group;
  }

  dispose() {
    this.group.traverse((child) => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach(m => m.dispose());
        } else {
          child.material.dispose();
        }
      }
    });
  }
}


// Quản lý nhiều mô hình cơ thể (theo dõi nhiều người)
export class BodyModelManager {
  constructor(scene) {
    this.scene = scene;
    this.models = new Map(); // personId -> BodyModel
    this.maxModels = 6;
    this.inactiveTimeout = 3000; // mili giây trước khi xoá mô hình không hoạt động
    this.lastSeen = new Map(); // personId -> dấu thời gian
  }

  // Cập nhật với dữ liệu tư thế mới cho có thể nhiều người
  update(personsData, delta) {
    const now = Date.now();

    if (personsData && personsData.length > 0) {
      for (let i = 0; i < Math.min(personsData.length, this.maxModels); i++) {
        const person = personsData[i];
        const personId = person.id || `person_${i}`;

        // Lấy hoặc tạo mô hình
        let model = this.models.get(personId);
        if (!model) {
          model = new BodyModel();
          this.models.set(personId, model);
          this.scene.add(model.getGroup());
        }

        // Cập nhật mô hình
        if (person.keypoints) {
          model.updateFromKeypoints(person.keypoints, person.confidence);
        }

        // Kích hoạt các phần DensePose nếu có
        if (person.body_parts) {
          model.activateParts(person.body_parts);
        }

        this.lastSeen.set(personId, now);
      }
    }

    // Hoạt hình tất cả mô hình
    for (const model of this.models.values()) {
      model.update(delta);
    }

    // Xoá các mô hình cũ
    for (const [id, lastTime] of this.lastSeen.entries()) {
      if (now - lastTime > this.inactiveTimeout) {
        const model = this.models.get(id);
        if (model) {
          this.scene.remove(model.getGroup());
          model.dispose();
          this.models.delete(id);
          this.lastSeen.delete(id);
        }
      }
    }
  }

  getActiveCount() {
    return this.models.size;
  }

  getAverageConfidence() {
    if (this.models.size === 0) return 0;
    let sum = 0;
    for (const model of this.models.values()) {
      sum += model.confidence;
    }
    return sum / this.models.size;
  }

  dispose() {
    for (const model of this.models.values()) {
      this.scene.remove(model.getGroup());
      model.dispose();
    }
    this.models.clear();
    this.lastSeen.clear();
  }
}
