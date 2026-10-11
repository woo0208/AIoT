// Display-only mesh avatar. Joint directions measured elsewhere -> bone rotations.
// URL options:  ?demo=1  synthetic motion (no Python/camera)   ?side=left  face-left side view
import * as THREE from 'three';
import { FBXLoader } from './vendor/three/examples/jsm/loaders/FBXLoader.js';

// ---------- tunables (visual only; not research parameters) ----------
const POSE_URL = '/pose';
const POLL_MS = 33;
const HOLD_MS = 1000;          // keep last joint this long when it drops out
const TARGET_HEIGHT_M = 1.75;
const params = new URLSearchParams(location.search);
// Visual aids below are OFF by default (VIEWER_3D_HANDOFF_RULES §3-4); enable explicitly via URL.
// ?smooth=0.45  exponential smoothing weight of the newest sample (0 < w <= 1; 1 = off, lower = smoother/laggier)
const SMOOTH = clampParam(params.get('smooth'), 0.05, 1, 1);
// ?nose_down=10  assumed nose-below-ear pitch (deg) subtracted from the head direction; 0 = off
const NEUTRAL_NOSE_DOWN_DEG = clampParam(params.get('nose_down'), -30, 30, 0);
function clampParam(v, lo, hi, dflt) {
  if (v === null || v === '') return dflt;
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : dflt;
}
const DEMO = params.get('demo') === '1';
const LOOK_MODE = params.get('look') || 'original';
const LIGHT_BG = params.get('bg') === 'light';
const SIDE_FACES_LEFT = params.get('side') === 'left';
// ?head=landmarks forces the stage-0 ear/nose head method (for comparison); default uses the face matrix when present
const HEAD_MODE = params.get('head') === 'landmarks' ? 'landmarks' : 'auto';
const MODEL_FILE = (params.get('model') || 'X_Bot.fbx').replace(/[^\w.\-]/g, ''); // file inside ./models/
// D455 mounting pitch in degrees (+ = camera looks downward). Display transform only; default 0 = level camera.
const CAM_PITCH_MAX_DEG = 60;
let camPitchDeg = parsePitch(params.get('cam_pitch'));
function parsePitch(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(-CAM_PITCH_MAX_DEG, Math.min(CAM_PITCH_MAX_DEG, n)) : 0;
}

// ---------- scene ----------
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setScissorTest(true);
const scene = new THREE.Scene();
scene.background = new THREE.Color(LIGHT_BG ? 0xdfe3e8 : 0x14161a);
if (LIGHT_BG) { document.body.style.background = '#dfe3e8'; document.body.style.color = '#1b1e23'; document.querySelectorAll('.hud,.lbl,.tag').forEach((e) => { e.style.textShadow = 'none'; }); }
scene.add(new THREE.HemisphereLight(0xffffff, 0x303640, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 2.0); key.position.set(2, 3, 3); scene.add(key);
const rim = new THREE.DirectionalLight(0x88aaff, 0.8); rim.position.set(-3, 2, -2); scene.add(rim);
const floor = new THREE.Mesh(new THREE.CircleGeometry(1.6, 48), new THREE.MeshStandardMaterial({ color: LIGHT_BG ? 0xc3c9d1 : 0x1d2128, roughness: 1 }));
floor.rotation.x = -Math.PI / 2; scene.add(floor);
scene.add(new THREE.GridHelper(3.2, 16, 0x2c333d, 0x23282f));

const frontCam = new THREE.PerspectiveCamera(32, 1, 0.05, 20);
const sideCam = new THREE.PerspectiveCamera(32, 1, 0.05, 20);
const LOOK = new THREE.Vector3(0, 0.85, 0.15);
frontCam.position.set(0, 1.1, 3.6); frontCam.lookAt(LOOK);
// avatar faces +Z. Camera on avatar's right (-X) => face points image-right.
sideCam.position.set(SIDE_FACES_LEFT ? 3.6 : -3.6, 1.0, 0.15); sideCam.lookAt(LOOK);

// ---------- helpers ----------
const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const UP = V(0, 1, 0);
const statusEl = document.getElementById('status');
const infoEl = document.getElementById('info');
function setStatus(text, cls) { statusEl.textContent = text; statusEl.className = cls; }

// camera frame (+X right, +Y down, +Z away) -> avatar world (Y up, avatar faces +Z, avatar-left = +X)
// First undo the camera's downward pitch about its X axis (camera frame -> level frame), then flip axes.
// Measured coordinates are not changed; this only re-expresses them for drawing.
function camToWorld(p) {
  const t = THREE.MathUtils.degToRad(camPitchDeg), c = Math.cos(t), s = Math.sin(t);
  const yLevel = p[1] * c + p[2] * s;
  const zLevel = -p[1] * s + p[2] * c;
  return V(p[0], -yLevel, -zLevel);
}

// [ / ] adjust the pitch by 1 deg (Shift: 5 deg), 0 resets; value is kept in the URL.
addEventListener('keydown', (e) => {
  const step = e.shiftKey ? 5 : 1;
  let next = camPitchDeg;
  if (e.key === ']' || e.key === '}') next += step;
  else if (e.key === '[' || e.key === '{') next -= step;
  else if (e.key === '0') next = 0;
  else return;
  camPitchDeg = parsePitch(next);
  for (const n in smoothed) delete smoothed[n];   // re-seed joints in the new frame
  const q = new URLSearchParams(location.search); q.set('cam_pitch', String(camPitchDeg));
  history.replaceState(null, '', '?' + q.toString());
});

// ---------- rig ----------
const bones = {};      // short name -> Bone
const restQ = {};      // short name -> local quaternion at rest (T-pose)
let avatar = null, hipsRestY = 0, legScale = 1;

function short(name) { return name.replace(/^mixamorig[:_]?/, ''); }

function worldPos(b) { return b.getWorldPosition(V()); }
function worldQuat(b) { return b.getWorldQuaternion(new THREE.Quaternion()); }

// rotate `bone` (world) so that the direction bone->child points along `target`
function aim(bone, child, target) {
  bone.updateWorldMatrix(true, true);
  const cur = worldPos(child).sub(worldPos(bone)).normalize();
  const dq = new THREE.Quaternion().setFromUnitVectors(cur, target.clone().normalize());
  const parentQ = worldQuat(bone.parent).invert();
  const newWorld = dq.multiply(worldQuat(bone));
  bone.quaternion.copy(parentQ.multiply(newWorld));
  bone.updateWorldMatrix(false, true);
}

// aim a local direction (in the bone's own frame at rest) toward a world target
function aimLocalAxis(bone, localAxis, target) {
  bone.updateWorldMatrix(true, true);
  const cur = localAxis.clone().applyQuaternion(worldQuat(bone)).normalize();
  const dq = new THREE.Quaternion().setFromUnitVectors(cur, target.clone().normalize());
  const parentQ = worldQuat(bone.parent).invert();
  bone.quaternion.copy(parentQ.multiply(dq.multiply(worldQuat(bone))));
  bone.updateWorldMatrix(false, true);
}

let headFwdLocal = V(0, 0, 1);
let headRestWorldQ = new THREE.Quaternion();   // Head world rotation in T-pose (faces +Z, up +Y)
let headSource = '없음';

// Stage 2: orient Head from face-matrix axes (RealSense frame; vertical -> head top, forward -> out of face).
// Same camera->world transform as joints (incl. cam_pitch); no offset, no smoothing.
function orientHeadFromAxes(axes) {
  const F = camToWorld(axes.forward).normalize();
  const U = camToWorld(axes.vertical);
  U.sub(F.clone().multiplyScalar(U.dot(F)));
  if (U.length() < 1e-6) return false;
  U.normalize();
  const X = new THREE.Vector3().crossVectors(U, F);
  const R = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(X, U, F));
  bones.Head.updateWorldMatrix(true, false);
  const parentQ = worldQuat(bones.Head.parent).invert();
  bones.Head.quaternion.copy(parentQ.multiply(R.multiply(headRestWorldQ.clone())));
  bones.Head.updateWorldMatrix(false, true);
  return true;
}

function resetRest() {
  for (const n in bones) bones[n].quaternion.copy(restQ[n]);
  bones.Hips.updateWorldMatrix(true, true);
}

function slerpDir(a, b, t) {
  const q = new THREE.Quaternion().setFromUnitVectors(a, b);
  const id = new THREE.Quaternion();
  return a.clone().applyQuaternion(id.slerp(q, t)).normalize();
}

function applyPose(j) {
  resetRest();

  // --- seated lower body (fixed by design; legs are not observed) ---
  const fwd = V(0, 0, 1), down = V(0, -1, 0);
  for (const s of ['Left', 'Right']) {
    aim(bones[s + 'UpLeg'], bones[s + 'Leg'], fwd);
    aim(bones[s + 'Leg'], bones[s + 'Foot'], down);
    aim(bones[s + 'Foot'], bones[s + 'ToeBase'], fwd);
  }

  // --- torso lean: hip-mid -> shoulder-mid ---
  const sh = mid(j.left_shoulder, j.right_shoulder);
  const hp = mid(j.left_hip, j.right_hip);
  let torso = UP.clone();
  if (sh && hp) {
    const d = sh.clone().sub(hp);
    if (d.length() > 0.05) torso = d.normalize();
  }
  aim(bones.Spine, bones.Spine1, slerpDir(UP, torso, 0.4));
  aim(bones.Spine1, bones.Spine2, slerpDir(UP, torso, 0.8));
  aim(bones.Spine2, bones.Neck, torso);

  // --- shoulder-line twist/roll about the torso axis ---
  if (j.left_shoulder && j.right_shoulder) {
    const meas = j.left_shoulder.clone().sub(j.right_shoulder);          // subject right -> left
    meas.sub(torso.clone().multiplyScalar(meas.dot(torso)));
    const cur = worldPos(bones.LeftArm).sub(worldPos(bones.RightArm));
    cur.sub(torso.clone().multiplyScalar(cur.dot(torso)));
    if (meas.length() > 1e-3 && cur.length() > 1e-3) {
      const dq = new THREE.Quaternion().setFromUnitVectors(cur.normalize(), meas.normalize());
      const pQ = worldQuat(bones.Spine2.parent).invert();
      bones.Spine2.quaternion.copy(pQ.multiply(dq.multiply(worldQuat(bones.Spine2))));
      bones.Spine2.updateWorldMatrix(false, true);
    }
  }

  // --- neck + head ---
  const ear = mid(j.left_ear, j.right_ear);
  const shoulderMid = sh || worldPos(bones.Neck);
  if (ear && sh) {
    const nh = ear.clone().sub(sh);
    if (nh.length() > 0.05) {
      aim(bones.Neck, bones.Head, slerpDir(torso, nh.normalize(), 0.7));
    }
  }
  headSource = '없음';
  if (j.head && orientHeadFromAxes(j.head)) {
    headSource = 'Face Matrix';
  } else if (ear && j.nose) {
    headSource = '귀·코 (대체)';
    const f = j.nose.clone().sub(ear);
    // remove the typical nose-below-ear offset so a neutral head stays level
    const right = V(1, 0, 0);
    f.applyAxisAngle(right, THREE.MathUtils.degToRad(-NEUTRAL_NOSE_DOWN_DEG));
    if (f.length() > 0.03) aimLocalAxis(bones.Head, headFwdLocal, f);
  }

  // --- arms (subject-left = avatar-left = +X) ---
  const relaxed = { Left: V(0.15, -1, 0.35), Right: V(-0.15, -1, 0.35) };
  for (const [s, k] of [['Left', 'left'], ['Right', 'right']]) {
    const S = j[k + '_shoulder'], E = j[k + '_elbow'], W = j[k + '_wrist'];
    const upper = bones[s + 'Arm'], fore = bones[s + 'ForeArm'], hand = bones[s + 'Hand'];
    if (S && E && E.distanceTo(S) > 0.05) aim(upper, fore, E.clone().sub(S));
    else aim(upper, fore, relaxed[s]);
    if (E && W && W.distanceTo(E) > 0.05) aim(fore, hand, W.clone().sub(E));
    else if (!(S && E)) aim(fore, hand, relaxed[s]);
  }

  // --- pin hips on the seat ---
}

function mid(a, b) {
  if (a && b) return a.clone().add(b).multiplyScalar(0.5);
  return a || b || null;
}

// ---------- chair ----------
function addChair(seatTopY) {
  const mat = new THREE.MeshStandardMaterial({ color: 0x3a4250, roughness: 0.8 });
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.05, 0.46), mat);
  seat.position.set(0, seatTopY - 0.025, -0.02);
  const back = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.5, 0.04), mat);
  back.position.set(0, seatTopY + 0.27, -0.27);
  const post = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, seatTopY - 0.05, 12), mat);
  post.position.set(0, (seatTopY - 0.05) / 2, -0.02);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.03, 24), mat);
  base.position.set(0, 0.015, -0.02);
  scene.add(seat, back, post, base);
}

// ---------- load ----------
new FBXLoader().load('./models/' + MODEL_FILE, (obj) => {
  avatar = obj;
  scene.add(obj);
  obj.traverse((o) => {
    // FBXLoader yields a same-named leaf Bone under each real joint (the skinning copy).
    // Drive the outer (first-visited, hierarchy-carrying) one; the copy follows it.
    if (o.isBone && !bones[short(o.name)]) bones[short(o.name)] = o;
    if (o.isMesh) {
      o.frustumCulled = false;
      // ?look=original (model's own textures) | clay (light grey, like a sculpt) | skin (uniform skin tone)
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      const textured = mats.some((m) => m && m.map);
      if (LOOK_MODE === 'clay' || (LOOK_MODE === 'original' && !textured)) {
        o.material = new THREE.MeshStandardMaterial({ color: 0xc9ced6, roughness: 0.55, metalness: 0.05 });
      } else if (LOOK_MODE === 'skin') {
        o.material = new THREE.MeshStandardMaterial({ color: 0xd9a98a, roughness: 0.6, metalness: 0.0 });
      }
    }
  });
  const need = ['Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftArm', 'LeftForeArm', 'LeftHand',
    'RightArm', 'RightForeArm', 'RightHand', 'LeftUpLeg', 'LeftLeg', 'LeftFoot', 'LeftToeBase',
    'RightUpLeg', 'RightLeg', 'RightFoot', 'RightToeBase'];
  const missing = need.filter((n) => !bones[n]);
  if (missing.length) { setStatus('뼈대 누락: ' + missing.join(', '), 'status-wait'); return; }

  // normalise to a 1.75 m human, feet on the floor, in T-pose
  obj.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(obj);
  const s = TARGET_HEIGHT_M / (box.max.y - box.min.y);
  obj.scale.multiplyScalar(s);
  obj.position.set(0, 0, 0);
  obj.updateMatrixWorld(true);
  const box2 = new THREE.Box3().setFromObject(obj);
  obj.position.y -= box2.min.y;
  obj.updateMatrixWorld(true);

  for (const n in bones) restQ[n] = bones[n].quaternion.clone();
  headFwdLocal = V(0, 0, 1).applyQuaternion(worldQuat(bones.Head).invert());
  headRestWorldQ = worldQuat(bones.Head);

  // seated placement: hips so that (shin vertical) feet touch the floor
  resetRest();
  const shin = worldPos(bones.LeftLeg).distanceTo(worldPos(bones.LeftFoot));
  const footH = worldPos(bones.LeftFoot).y - 0; // foot bone above floor (T-pose standing, floor at 0)
  const thigh = worldPos(bones.LeftUpLeg).distanceTo(worldPos(bones.LeftLeg));
  const hipsToUpLeg = worldPos(bones.Hips).y - worldPos(bones.LeftUpLeg).y;
  const upLegY = shin + footH;
  const hipsY = upLegY + hipsToUpLeg;
  const hipsWorld = worldPos(bones.Hips);
  // shift whole avatar so Hips ends at (0, hipsY, 0) with thighs forward
  obj.position.y += hipsY - hipsWorld.y;
  obj.position.z += 0 - hipsWorld.z;
  obj.updateMatrixWorld(true);
  addChair(upLegY - 0.07);
  setStatus(DEMO ? 'DEMO 모드 (가짜 데이터)' : '모델 로드 완료 · 데이터 대기', DEMO ? 'status-demo' : 'status-wait');
  applyPose({});
  requestAnimationFrame(frame);
}, undefined, (e) => { console.error(e); setStatus('FBX 로드 실패 — models/' + MODEL_FILE + ' 확인', 'status-wait'); });

// ---------- data ----------
const JN = ['nose', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
  'left_wrist', 'right_wrist', 'left_hip', 'right_hip'];
const smoothed = {};   // name -> {p: Vector3, t: ms}
let latestHead = null;  // {axes, t}: face-matrix head axes, held like joints
let lastFrameId = -1, lastPoseAt = 0, fpsCount = 0, fpsT = performance.now(), fps = 0, synthetic = false;

function ingest(payload) {
  const now = performance.now();
  synthetic = !!payload.synthetic;
  for (const n of JN) {
    const raw = payload.joints && payload.joints[n];
    if (raw) {
      const w = camToWorld(raw);
      const s = smoothed[n];
      if (s) { s.p.lerp(w, SMOOTH); s.t = now; } else smoothed[n] = { p: w, t: now };
    }
  }
  if (payload.head) latestHead = { axes: payload.head, t: now };
  lastPoseAt = now;
}

function currentJoints() {
  const now = performance.now(), j = {};
  for (const n of JN) { const s = smoothed[n]; j[n] = s && now - s.t < HOLD_MS ? s.p.clone() : null; }
  j.head = HEAD_MODE !== 'landmarks' && latestHead && now - latestHead.t < HOLD_MS ? latestHead.axes : null;
  return j;
}

async function poll() {
  if (DEMO) return;
  try {
    const r = await fetch(POSE_URL, { cache: 'no-store' });
    const p = await r.json();
    if (p.joints && p.frame_id !== lastFrameId) { lastFrameId = p.frame_id; ingest(p); }
  } catch (_) { /* server not ready */ }
  setTimeout(poll, POLL_MS);
}
poll();

function demoJoints(t) {
  // synthetic: forward-head sway + slight torso lean (camera frame, metres)
  const z = 0.8, head = 0.10 * (1 + Math.sin(t * 0.8)), lean = 0.04 * (1 + Math.sin(t * 0.8 + 0.5));
  const arm = 0.05 * Math.sin(t * 1.3);
  return {
    left_shoulder: [0.19, 0, z - lean], right_shoulder: [-0.19, 0, z - lean],
    left_hip: [0.10, 0.5, z], right_hip: [-0.10, 0.5, z],
    left_ear: [0.08, -0.22, z - lean - head], right_ear: [-0.08, -0.22, z - lean - head],
    nose: [0, -0.20, z - lean - head - 0.09],
    left_elbow: [0.24, 0.22, z - 0.05], right_elbow: [-0.24, 0.22, z - 0.05],
    left_wrist: [0.17, 0.38 + arm, z - 0.28], right_wrist: [-0.17, 0.38 - arm, z - 0.28],
  };
}

// ---------- render ----------
function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  frontCam.aspect = sideCam.aspect = (w / 2) / h;
  frontCam.updateProjectionMatrix(); sideCam.updateProjectionMatrix();
}
addEventListener('resize', resize); resize();

function frame(now) {
  requestAnimationFrame(frame);
  if (DEMO) { ingest({ synthetic: true, joints: demoJoints(now / 1000) }); }
  const j = currentJoints();
  applyPose(j);

  const w = innerWidth, h = innerHeight, dpr = renderer.getPixelRatio();
  renderer.setViewport(0, 0, w / 2, h); renderer.setScissor(0, 0, w / 2, h); renderer.render(scene, frontCam);
  renderer.setViewport(w / 2, 0, w / 2, h); renderer.setScissor(w / 2, 0, w / 2, h); renderer.render(scene, sideCam);

  fpsCount++;
  if (now - fpsT > 1000) { fps = fpsCount; fpsCount = 0; fpsT = now; }
  const have = JN.filter((n) => j[n]).length;
  if (!DEMO) {
    const age = now - lastPoseAt;
    if (!lastPoseAt) setStatus('카메라 데이터 대기 중…', 'status-wait');
    else if (age > 1000) setStatus('데이터 끊김 (' + Math.round(age / 1000) + 's)', 'status-wait');
    else setStatus(synthetic ? '연결됨 · SYNTHETIC (가짜 데이터)' : '연결됨 · 실시간', synthetic ? 'status-demo' : 'status-ok');
  }
  infoEl.textContent = `${fps} fps · 관절 ${have}/${JN.length} · 카메라 기울기 보정 ${camPitchDeg}° ([ ] 조정, 0 초기화)`
    + ` · 머리: ${headSource}` + ` · 평활 ${SMOOTH < 1 ? SMOOTH : '꺼짐'} · 고개 보정 ${NEUTRAL_NOSE_DOWN_DEG ? NEUTRAL_NOSE_DOWN_DEG + '°' : '꺼짐'}`;
}
