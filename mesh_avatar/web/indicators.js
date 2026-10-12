// TEMPORARY DEMO (branch demo/viewer-indicators-2026-10, for the week-of-2026-10-12 presentation; to be discarded).
// Stage 6a: descriptive indicators from the CURRENT frame only. No thresholds, no normal/poor judgement,
// no stored reference (no calibration), no smoothing. Not F1/F2 features, not research measurements.
// Stage 6b: shows a PredictionResult only if the payload carries one; nothing produces it yet.
//
// Inputs are avatar-world points {x, y, z} in metres (camToWorld already applied):
//   +X = subject's left, +Y = up, +Z = toward the camera (forward for a subject facing the camera).

const RAD = 180 / Math.PI;
const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const mid = (a, b) => (a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 } : null);
const len = (v) => Math.hypot(v.x, v.y, v.z);

// headAxesWorld: {forward, vertical} already in world frame, or null
export function computeIndicators(j, headAxesWorld) {
  const out = {};
  const S = mid(j.left_shoulder, j.right_shoulder);
  const H = mid(j.left_hip, j.right_hip);
  const W = j.left_shoulder && j.right_shoulder ? len(sub(j.left_shoulder, j.right_shoulder)) : null;

  if (S && j.nose) {
    const d = sub(j.nose, S);
    out.headForwardCm = d.z * 100;                         // nose surface ahead of shoulder-joint midpoint
    out.headForwardPerShoulderW = W ? d.z / W : null;
    out.headLateralCm = d.x * 100;                         // + = toward subject's left
  }
  if (S && H) {
    const t = sub(S, H);
    out.torsoPitchDeg = Math.atan2(t.z, t.y) * RAD;        // + = shoulders ahead of hips (forward)
    out.torsoRollDeg = Math.atan2(t.x, t.y) * RAD;         // + = shoulders toward subject's left
  }
  if (j.left_shoulder && j.right_shoulder) {
    out.shoulderHeightDiffCm = (j.left_shoulder.y - j.right_shoulder.y) * 100;  // + = left shoulder higher
  }
  for (const side of ['left', 'right']) {
    const s = j[side + '_shoulder'], e = j[side + '_elbow'];
    if (s && e) {
      const u = sub(e, s), n = len(u);
      if (n > 0.05) out[side + 'ArmElevationDeg'] = Math.acos(Math.max(-1, Math.min(1, -u.y / n))) * RAD;  // 0 = hanging
    }
  }
  if (headAxesWorld) {
    const F = headAxesWorld.forward, U = headAxesWorld.vertical;
    const nf = len(F), nu = len(U);
    if (nf > 1e-6 && nu > 1e-6) {
      out.headYawDeg = Math.atan2(F.x, F.z) * RAD;                               // + = face turned to subject's left
      out.headPitchDeg = Math.asin(Math.max(-1, Math.min(1, -F.y / nf))) * RAD;  // + = face pointing down
      out.headRollDeg = Math.atan2(U.x, U.y) * RAD;                              // + = head top toward subject's left
    }
  }
  return out;
}

// TEMPORARY DEMO RULES (stage 6c stand-in), approved by the branch owner on 2026-10-12 for presentation photos only.
// Thresholds were picked from ONE person's single-session observation (2026-10-12); NOT validated, NOT research
// criteria, NOT a PredictionResult. Must be replaced by the owner-approved stage-6c rules and then discarded.
export const DEMO_RULES = {
  headForwardCm: 18, torsoForwardDeg: 0, torsoBackDeg: -25,
  headRollDeg: 15, headYawDeg: 20, torsoRollDeg: 10, armElevationDeg: 60,
};

export function demoJudgement(ind) {
  if (ind.headForwardCm == null || ind.torsoPitchDeg == null) return { ok: null, msgs: ['판정 불가 (머리·몸통 값 없음)'] };
  const R = DEMO_RULES, msgs = [];
  if (ind.headForwardCm >= R.headForwardCm && ind.torsoPitchDeg < R.torsoForwardDeg) msgs.push('거북목입니다');
  if (ind.torsoPitchDeg >= R.torsoForwardDeg) msgs.push('상체가 앞으로 숙여졌습니다');
  if (ind.torsoPitchDeg <= R.torsoBackDeg) msgs.push('등을 뒤로 기댔습니다');
  if (ind.headRollDeg != null && Math.abs(ind.headRollDeg) >= R.headRollDeg) msgs.push('고개가 기울어졌습니다');
  if (ind.headYawDeg != null && Math.abs(ind.headYawDeg) >= R.headYawDeg) msgs.push('고개를 돌렸습니다');
  if (ind.torsoRollDeg != null && Math.abs(ind.torsoRollDeg) >= R.torsoRollDeg) msgs.push('몸통이 옆으로 기울었습니다');
  if ((ind.leftArmElevationDeg ?? 0) >= R.armElevationDeg || (ind.rightArmElevationDeg ?? 0) >= R.armElevationDeg) msgs.push('팔을 들었습니다');
  return msgs.length ? { ok: false, msgs: ['바른 자세가 아닙니다', ...msgs] } : { ok: true, msgs: ['바른 자세입니다'] };
}

const f1 = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
const dir = (v, pos, neg) => (Math.abs(v) < 0.05 ? '' : ' ' + (v > 0 ? pos : neg));

function row(label, value, note = '') {
  return `<tr><td>${label}</td><td class="v">${value}</td><td class="n">${note}</td></tr>`;
}

export function renderPanel(ind, prediction) {
  const na = '<span class="na">—</span>';
  const cm = (v, pos, neg) => (v == null ? na : `${f1(v)} cm${dir(v, pos, neg)}`);
  const deg = (v, pos, neg) => (v == null ? na : `${f1(v)}°${dir(v, pos, neg)}`);
  const rows = [
    row('머리 앞뒤 (코 − 어깨 중점)', cm(ind.headForwardCm, '앞', '뒤'),
      ind.headForwardPerShoulderW == null ? '' : `어깨너비의 ${ind.headForwardPerShoulderW.toFixed(2)}배 · 바른 자세에서도 0 아님`),
    row('몸통 앞뒤 기울기 (hip → 어깨)', deg(ind.torsoPitchDeg, '앞', '뒤'), 'hip depth 오차로 뒤쪽으로 치우침'),
    row('몸통 좌우 기울기', deg(ind.torsoRollDeg, '왼쪽', '오른쪽')),
    row('머리 좌우 이동 (코 − 어깨 중점)', cm(ind.headLateralCm, '왼쪽', '오른쪽')),
    row('머리 회전 좌우 / 숙임 / 기울기', ind.headYawDeg == null ? na
      : `${deg(ind.headYawDeg, '왼쪽', '오른쪽')} / ${deg(ind.headPitchDeg, '아래', '위')} / ${deg(ind.headRollDeg, '왼쪽', '오른쪽')}`, 'Face Matrix'),
    row('어깨 높이 차 (왼 − 오)', cm(ind.shoulderHeightDiffCm, '왼쪽 높음', '오른쪽 높음')),
    row('팔 올림 왼 / 오', `${deg(ind.leftArmElevationDeg, '', '')} / ${deg(ind.rightArmElevationDeg, '', '')}`, '0° = 내림, 90° = 수평'),
  ];
  const pred = prediction && typeof prediction === 'object'
    ? `${prediction.prediction_class ?? prediction.class ?? '?'} (${prediction.reason ?? '-'})`
    : 'UNAVAILABLE — 분류 모델 미연결';
  const jd = demoJudgement(ind);
  const jcls = jd.ok === true ? 'jok' : jd.ok === false ? 'jbad' : 'jna';
  return `<div class="jd ${jcls}">${jd.msgs[0]}</div>`
    + (jd.msgs.length > 1 ? `<div class="jd2">${jd.msgs.slice(1).join(' · ')}</div>` : '')
    + `<div class="jw">임시 데모 규칙 · 검증 안 됨 (1인 관찰로 정한 기준, 연구 판정 아님)</div>`
    + `<div class="ph">측정 지표 — 현재 프레임 값 · 기준선 없음</div>`
    + `<table>${rows.join('')}</table>`
    + `<div class="pr">판정 결과 (PredictionResult): <b>${pred}</b></div>`
    + `<div class="pn">방향: 왼쪽/오른쪽 = 앉은 사람 기준 · 현재 프레임 값 그대로(평활 없음) · 연구 측정값 아님</div>`;
}
