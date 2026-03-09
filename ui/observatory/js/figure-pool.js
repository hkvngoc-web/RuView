/**
 * FigurePool — Quản lý nhóm hình người khung dây cho kết xuất đa người.
 *
 * Trích xuất từ lớp Observatory trong main.js. Sở hữu vòng đời của tối đa MAX_FIGURES
 * nhóm hình Three.js, mỗi nhóm chứa khớp, xương, phân đoạn cơ thể, và hào quang.
 *
 * Cải tiến so với triển khai inline gốc:
 * - Nội suy khớp mượt (lerp tới mục tiêu thay vì nhảy đột ngột)
 * - Nhịp đập khớp đồng bộ với hơi thở
 * - Xương có độ dày tự nhiên (dày hơn ở vai/hông, mỏng hơn ở tứ chi)
 * - Chuyển động thứ cấp với độ trễ/vượt quá nhẹ cho cảm giác hữu cơ
 * - Hào quang thích ứng theo tư thế (rộng hơn khi tập, hẹp hơn khi ngồi xổm)
 */
import * as THREE from 'three';

// Kết nối khung xương COCO 17 điểm chính
export const SKELETON_PAIRS = [
  [0, 1], [0, 2], [1, 3], [2, 4],
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16],
];

// Hình trụ phân đoạn cơ thể tạo thể tích cho khung dây
export const BODY_SEGMENT_DEFS = [
  { joints: [5, 11], radius: 0.12 },   // thân trái
  { joints: [6, 12], radius: 0.12 },   // thân phải
  { joints: [5, 6], radius: 0.1 },     // thanh vai
  { joints: [11, 12], radius: 0.1 },   // thanh hông
  { joints: [5, 7], radius: 0.05 },    // bắp tay trái
  { joints: [6, 8], radius: 0.05 },    // bắp tay phải
  { joints: [7, 9], radius: 0.04 },    // cẳng tay trái
  { joints: [8, 10], radius: 0.04 },   // cẳng tay phải
  { joints: [11, 13], radius: 0.07 },  // đùi trái
  { joints: [12, 14], radius: 0.07 },  // đùi phải
  { joints: [13, 15], radius: 0.05 },  // ống chân trái
  { joints: [14, 16], radius: 0.05 },  // ống chân phải
  { joints: [0, 0], radius: 0.1, isHead: true },
];

// Hệ số độ dày xương — dày hơn ở thân, mỏng hơn ở tứ chi
const BONE_TAPER = (() => {
  const tapers = new Map();
  // Kết nối thân và vai/hông dày nhất
  tapers.set('5-6', 1.4);    // thanh vai
  tapers.set('11-12', 1.3);  // thanh hông
  tapers.set('5-11', 1.3);   // thân trái
  tapers.set('6-12', 1.3);   // thân phải
  // Chi trên
  tapers.set('5-7', 1.0);    // bắp tay trái
  tapers.set('6-8', 1.0);    // bắp tay phải
  tapers.set('11-13', 1.1);  // đùi trái
  tapers.set('12-14', 1.1);  // đùi phải
  // Chi dưới / tứ chi — mỏng nhất
  tapers.set('7-9', 0.7);    // cẳng tay trái
  tapers.set('8-10', 0.7);   // cẳng tay phải
  tapers.set('13-15', 0.8);  // ống chân trái
  tapers.set('14-16', 0.8);  // ống chân phải
  // Kết nối đầu
  tapers.set('0-1', 0.5);
  tapers.set('0-2', 0.5);
  tapers.set('1-3', 0.4);
  tapers.set('2-4', 0.4);
  return tapers;
})();

// Hệ số trễ chuyển động thứ cấp theo khớp — tứ chi trễ nhiều hơn
const SECONDARY_DELAY = [
  0.12, // 0 mũi
  0.10, // 1 mắt trái
  0.10, // 2 mắt phải
  0.08, // 3 tai trái
  0.08, // 4 tai phải
  0.18, // 5 vai trái
  0.18, // 6 vai phải
  0.14, // 7 khuỷu tay trái
  0.14, // 8 khuỷu tay phải
  0.10, // 9 cổ tay trái (trễ nhất)
  0.10, // 10 cổ tay phải
  0.20, // 11 hông trái (neo, theo nhanh)
  0.20, // 12 hông phải
  0.15, // 13 đầu gối trái
  0.15, // 14 đầu gối phải
  0.10, // 15 mắt cá trái
  0.10, // 16 mắt cá phải
];

// Hệ số vượt quá — tứ chi vượt quá nhiều hơn cho cảm giác hữu cơ
const OVERSHOOT = [
  0.02, // 0 mũi
  0.01, // 1 mắt trái
  0.01, // 2 mắt phải
  0.01, // 3 tai trái
  0.01, // 4 tai phải
  0.03, // 5 vai trái
  0.03, // 6 vai phải
  0.05, // 7 khuỷu tay trái
  0.05, // 8 khuỷu tay phải
  0.08, // 9 cổ tay trái
  0.08, // 10 cổ tay phải
  0.02, // 11 hông trái
  0.02, // 12 hông phải
  0.04, // 13 đầu gối trái
  0.04, // 14 đầu gối phải
  0.06, // 15 mắt cá trái
  0.06, // 16 mắt cá phải
];

const MAX_FIGURES = 4;

// Vector tái sử dụng tránh cấp phát mỗi khung hình
const _vecFrom = new THREE.Vector3();
const _vecTo = new THREE.Vector3();
const _vecTarget = new THREE.Vector3();

export class FigurePool {
  /**
   * @param {THREE.Scene} scene - Cảnh Three.js để thêm hình vào
   * @param {object} settings - Đối tượng cài đặt dùng chung (boneThick, jointSize, glow, v.v.)
   * @param {object} poseSystem - Thực thể PoseSystem với generateKeypoints(person, elapsed, breathPulse)
   */
  constructor(scene, settings, poseSystem) {
    this._scene = scene;
    this._settings = settings;
    this._poseSystem = poseSystem;
    this._figures = [];
    this._maxFigures = MAX_FIGURES;
    this._build();
  }

  /** @returns {Array} Mảng các đối tượng hình */
  get figures() { return this._figures; }

  // ---- Construction ----

  _build() {
    for (let f = 0; f < this._maxFigures; f++) {
      this._figures.push(this._createFigure());
    }
  }

  _createFigure() {
    const group = new THREE.Group();
    this._scene.add(group);
    const wireColor = new THREE.Color(this._settings.wireColor);
    const jointColor = new THREE.Color(this._settings.jointColor);

    // Joints (17 COCO keypoints)
    const joints = [];
    for (let i = 0; i < 17; i++) {
      const isNose = i === 0;
      const size = isNose ? this._settings.jointSize * 0.7 : this._settings.jointSize;
      const geo = new THREE.SphereGeometry(size, 12, 12);
      const mat = new THREE.MeshStandardMaterial({
        color: isNose ? wireColor : jointColor,
        emissive: isNose ? wireColor : jointColor,
        emissiveIntensity: 0.35,
        transparent: true, opacity: 0,
        roughness: 0.3, metalness: 0.2,
      });
      const sphere = new THREE.Mesh(geo, mat);
      sphere.castShadow = true;
      group.add(sphere);
      joints.push(sphere);

      // Halo glow on key joints
      if ([5, 6, 9, 10, 11, 12, 15, 16].includes(i)) {
        const haloGeo = new THREE.SphereGeometry(size * 1.3, 8, 8);
        const haloMat = new THREE.MeshBasicMaterial({
          color: jointColor,
          transparent: true, opacity: 0,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const halo = new THREE.Mesh(haloGeo, haloMat);
        sphere.add(halo);
        sphere._halo = halo;
        sphere._haloMat = haloMat;

        const glow = new THREE.PointLight(jointColor, 0, 0.8);
        sphere.add(glow);
        sphere._glow = glow;
      }
    }

    // Bones — tapered thickness
    const bones = [];
    for (const [a, b] of SKELETON_PAIRS) {
      const taperKey = `${Math.min(a, b)}-${Math.max(a, b)}`;
      const taper = BONE_TAPER.get(taperKey) || 1.0;
      const thick = this._settings.boneThick * taper;
      // Top radius thicker than bottom for natural taper along bone length
      const topRadius = thick;
      const botRadius = thick * 0.65;
      const geo = new THREE.CylinderGeometry(topRadius, botRadius, 1, 8, 1);
      geo.translate(0, 0.5, 0);
      geo.rotateX(Math.PI / 2);
      const mat = new THREE.MeshStandardMaterial({
        color: wireColor, emissive: wireColor, emissiveIntensity: 0.3,
        transparent: true, opacity: 0, roughness: 0.4, metalness: 0.1,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      group.add(mesh);
      bones.push({ mesh, a, b, taper });
    }

    // Body segments (volume cylinders and head sphere)
    const bodySegments = [];
    for (const seg of BODY_SEGMENT_DEFS) {
      const geo = seg.isHead
        ? new THREE.SphereGeometry(seg.radius, 12, 12)
        : new THREE.CylinderGeometry(seg.radius, seg.radius * 0.85, 1, 8, 1);
      if (!seg.isHead) {
        geo.translate(0, 0.5, 0);
        geo.rotateX(Math.PI / 2);
      }
      const mat = new THREE.MeshStandardMaterial({
        color: wireColor, emissive: wireColor, emissiveIntensity: 0.12,
        transparent: true, opacity: 0, roughness: 0.5, metalness: 0.1,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geo, mat);
      group.add(mesh);
      bodySegments.push({ mesh, mat, a: seg.joints[0], b: seg.joints[1], isHead: seg.isHead });
    }

    // Aura cylinder
    const auraGeo = new THREE.CylinderGeometry(0.4, 0.3, 1.7, 16, 1, true);
    const auraMat = new THREE.MeshBasicMaterial({
      color: wireColor, transparent: true, opacity: 0,
      side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const aura = new THREE.Mesh(auraGeo, auraMat);
    aura.position.y = 1;
    group.add(aura);

    // Per-figure point light
    const personLight = new THREE.PointLight(wireColor, 0, 6);
    personLight.position.y = 1;
    group.add(personLight);

    // Interpolation state: previous positions for smooth lerp and secondary motion
    const prevPositions = [];
    const velocities = [];
    for (let i = 0; i < 17; i++) {
      prevPositions.push(new THREE.Vector3(0, 0, 0));
      velocities.push(new THREE.Vector3(0, 0, 0));
    }

    return {
      group, joints, bones, bodySegments, aura, auraMat, personLight,
      visible: false,
      prevPositions,
      velocities,
      _initialized: false,
      _lastPose: null,
    };
  }

  // ---- Per-frame update ----

  /**
   * Update all figures based on current data frame.
   * @param {object} data - Current sensing data with persons[], vital_signs, classification
   * @param {number} elapsed - Elapsed time in seconds
   */
  update(data, elapsed) {
    const persons = data?.persons || [];
    const vs = data?.vital_signs || {};
    const isPresent = data?.classification?.presence || false;
    const breathBpm = vs.breathing_rate_bpm || 0;
    const breathPulse = breathBpm > 0
      ? Math.sin(elapsed * Math.PI * 2 * (breathBpm / 60)) * 0.012
      : 0;

    for (let f = 0; f < this._figures.length; f++) {
      const fig = this._figures[f];
      if (f < persons.length && isPresent) {
        const p = persons[f];
        const kps = this._poseSystem.generateKeypoints(p, elapsed, breathPulse);
        this.applyKeypoints(fig, kps, breathPulse, p.position || [0, 0, 0], elapsed, p.pose);
        fig.visible = true;
      } else {
        if (fig.visible) {
          this.hide(fig);
          fig.visible = false;
        }
      }
    }
  }

  /**
   * Apply keypoints to a figure with smooth interpolation, pulsation, and secondary motion.
   * @param {object} fig - Figure object from the pool
   * @param {Array} kps - 17-element array of [x,y,z] keypoint positions
   * @param {number} breathPulse - Current breathing pulse value
   * @param {Array} pos - Person world position [x,y,z]
   * @param {number} elapsed - Elapsed time for pulsation effects
   * @param {string} pose - Current pose name for aura adaptation
   */
  applyKeypoints(fig, kps, breathPulse, pos, elapsed = 0, pose = 'standing') {
    const lerpFactor = fig._initialized ? 0.18 : 1.0;

    // Joints with smooth interpolation and secondary motion
    for (let i = 0; i < 17 && i < kps.length; i++) {
      const j = fig.joints[i];
      _vecTarget.set(kps[i][0], kps[i][1], kps[i][2]);

      if (fig._initialized) {
        // Compute velocity for overshoot
        const prev = fig.prevPositions[i];
        const vel = fig.velocities[i];

        // Smooth lerp with per-joint delay
        const delay = SECONDARY_DELAY[i];
        const jointLerp = lerpFactor + delay;
        j.position.lerp(_vecTarget, Math.min(jointLerp, 0.95));

        // Apply subtle overshoot based on velocity change
        const overshoot = OVERSHOOT[i];
        vel.subVectors(j.position, prev).multiplyScalar(overshoot);
        j.position.add(vel);

        prev.copy(j.position);
      } else {
        // First frame: snap to position
        j.position.copy(_vecTarget);
        fig.prevPositions[i].copy(_vecTarget);
        fig.velocities[i].set(0, 0, 0);
      }

      j.material.opacity = 0.95;

      // Joint pulsation synced with breathing
      const pulseFactor = 1.0 + Math.abs(breathPulse) * 8.0;
      j.material.emissiveIntensity = 0.35 * pulseFactor;

      const baseScale = this._settings.jointSize / 0.04;
      // Subtle size pulsation on breathing
      const pulseScale = baseScale * (1.0 + Math.abs(breathPulse) * 3.0);
      j.scale.setScalar(pulseScale);

      if (j._haloMat) {
        j._haloMat.opacity = 0.04 * this._settings.glow * pulseFactor;
      }
      if (j._glow) {
        j._glow.intensity = this._settings.glow * 0.12 * pulseFactor;
      }
    }

    fig._initialized = true;

    // Bones with tapered thickness
    for (const bone of fig.bones) {
      const pA = kps[bone.a], pB = kps[bone.b];
      if (pA && pB) {
        _vecFrom.set(pA[0], pA[1], pA[2]);
        _vecTo.set(pB[0], pB[1], pB[2]);
        const len = _vecFrom.distanceTo(_vecTo);

        // Use interpolated joint positions for smooth bone movement
        if (fig._initialized) {
          const jA = fig.joints[bone.a];
          const jB = fig.joints[bone.b];
          bone.mesh.position.copy(jA.position);
          bone.mesh.scale.set(1, 1, jA.position.distanceTo(jB.position));
          bone.mesh.lookAt(jB.position);
        } else {
          bone.mesh.position.copy(_vecFrom);
          bone.mesh.scale.set(1, 1, len);
          bone.mesh.lookAt(_vecTo);
        }

        bone.mesh.material.opacity = 0.85;
        bone.mesh.material.emissiveIntensity = 0.3 + Math.abs(breathPulse) * 2.0;
      }
    }

    // Body segments
    for (const seg of fig.bodySegments) {
      if (seg.isHead) {
        const headJoint = fig.joints[seg.a];
        seg.mesh.position.set(headJoint.position.x, headJoint.position.y + 0.05, headJoint.position.z);
        seg.mat.opacity = 0.15;
      } else {
        const jA = fig.joints[seg.a];
        const jB = fig.joints[seg.b];
        if (jA && jB) {
          const len = jA.position.distanceTo(jB.position);
          seg.mesh.position.copy(jA.position);
          seg.mesh.scale.set(1, 1, len);
          seg.mesh.lookAt(jB.position);
          seg.mat.opacity = 0.12;
        }
      }
      seg.mat.emissiveIntensity = 0.1 + Math.abs(breathPulse) * 0.4;
    }

    // Aura — adapt shape to pose
    const hipY = (fig.joints[11].position.y + fig.joints[12].position.y) / 2;
    const cx = (fig.joints[11].position.x + fig.joints[12].position.x) / 2;
    const cz = (fig.joints[11].position.z + fig.joints[12].position.z) / 2;
    fig.aura.position.set(cx, hipY, cz);
    fig.auraMat.opacity = this._settings.aura + Math.abs(breathPulse) * 0.8;

    // Pose-adaptive aura: compute from actual keypoint spread
    const auraShape = this._computeAuraShape(fig, pose, breathPulse);
    fig.aura.scale.set(auraShape.scaleX, auraShape.scaleY, auraShape.scaleZ);

    // Person light
    fig.personLight.position.set(pos[0], 1.2, pos[2]);
    fig.personLight.intensity = this._settings.glow * 0.4;

    fig._lastPose = pose;
  }

  /**
   * Compute pose-adaptive aura shape based on actual keypoint spread.
   * Wider for exercise/spread poses, narrower for crouching/compact poses.
   */
  _computeAuraShape(fig, pose, breathPulse) {
    // Measure horizontal spread from shoulders and hips
    const lShoulder = fig.joints[5].position;
    const rShoulder = fig.joints[6].position;
    const lHip = fig.joints[11].position;
    const rHip = fig.joints[12].position;
    const nose = fig.joints[0].position;
    const lAnkle = fig.joints[15].position;
    const rAnkle = fig.joints[16].position;

    // Horizontal spread (X-Z plane)
    const shoulderWidth = Math.sqrt(
      (rShoulder.x - lShoulder.x) ** 2 +
      (rShoulder.z - lShoulder.z) ** 2
    );
    const ankleWidth = Math.sqrt(
      (rAnkle.x - lAnkle.x) ** 2 +
      (rAnkle.z - lAnkle.z) ** 2
    );
    const maxWidth = Math.max(shoulderWidth, ankleWidth);

    // Vertical extent
    const headY = nose.y;
    const footY = Math.min(lAnkle.y, rAnkle.y);
    const height = headY - footY;

    // Normalize to base aura dimensions
    const baseWidth = 0.44; // default shoulder width
    const baseHeight = 1.7; // default standing height

    const widthRatio = Math.max(0.6, Math.min(2.0, maxWidth / baseWidth));
    const heightRatio = Math.max(0.4, Math.min(1.3, height / baseHeight));

    // Breathing modulation
    const breathMod = 1 + breathPulse * 2;

    return {
      scaleX: widthRatio * breathMod,
      scaleY: heightRatio * breathMod,
      scaleZ: widthRatio * breathMod,
    };
  }

  /**
   * Hide a figure by fading all materials to invisible.
   * @param {object} fig - Figure object to hide
   */
  hide(fig) {
    for (const j of fig.joints) {
      j.material.opacity = 0;
      if (j._haloMat) j._haloMat.opacity = 0;
      if (j._glow) j._glow.intensity = 0;
    }
    for (const b of fig.bones) b.mesh.material.opacity = 0;
    for (const seg of fig.bodySegments) seg.mat.opacity = 0;
    fig.auraMat.opacity = 0;
    fig.personLight.intensity = 0;
    fig._initialized = false;
  }

  /**
   * Apply wire and joint colors to all figures in the pool.
   * @param {THREE.Color} wireColor
   * @param {THREE.Color} jointColor
   */
  applyColors(wireColor, jointColor) {
    for (const fig of this._figures) {
      for (let i = 0; i < fig.joints.length; i++) {
        const j = fig.joints[i];
        if (i === 0) {
          j.material.color.copy(wireColor);
          j.material.emissive.copy(wireColor);
        } else {
          j.material.color.copy(jointColor);
          j.material.emissive.copy(jointColor);
        }
        if (j._haloMat) j._haloMat.color.copy(jointColor);
        if (j._glow) j._glow.color.copy(jointColor);
      }
      for (const b of fig.bones) {
        b.mesh.material.color.copy(wireColor);
        b.mesh.material.emissive.copy(wireColor);
      }
      for (const seg of fig.bodySegments) {
        seg.mat.color.copy(wireColor);
        seg.mat.emissive.copy(wireColor);
      }
      fig.auraMat.color.copy(wireColor);
      fig.personLight.color.copy(wireColor);
    }
  }
}
