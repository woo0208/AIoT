// Display existing probe geometry only. This module applies no posture rule,
// threshold, smoothing, history, or label mapping. Missing/stale/mismatched
// values stay N/A rather than being replaced by a previous frame.
export const STALE_MS = 1000;
export const GEOMETRY_KIND = 'exploratory-current-frame-geometry/1';
export const GEOMETRY_BANNER = 'EXPLORATORY GEOMETRY — NOT A POSTURE CLASSIFICATION';
export const GEOMETRY_METRICS = Object.freeze([
  { key: 'sagittal_torso_lean_deg', elementId: 'gTorso', unit: '°', decimals: 2, signed: true },
  { key: 'exploratory_head_pitch_deg', elementId: 'gHeadPitch', unit: '°', decimals: 2, signed: true },
  { key: 'nose_forward_normalized_by_shoulder_width_3d', elementId: 'gHeadForward', unit: '', decimals: 3, signed: true },
  { key: 'shoulder_width_3d_m', elementId: 'gShoulderWidth', unit: ' m', decimals: 3, signed: false },
  { key: 'head_to_torso_lateral_angle_deg', elementId: 'gHeadLateral', unit: '°', decimals: 2, signed: true },
  { key: 'face_matrix_yaw_deg', elementId: 'gFaceYaw', unit: '°', decimals: 2, signed: true },
]);

const emptyValues = () => Object.fromEntries(GEOMETRY_METRICS.map((metric) => [metric.key, null]));

export function geometryView(payload, ageMs) {
  const frameId = payload && Number.isInteger(payload.frame_id) ? payload.frame_id : null;
  const unavailable = (reason) => ({ values: emptyValues(), reason: String(reason), frameId });
  if (!payload || !payload.joints) return unavailable('no probe frame yet');
  if (payload.synthetic) return unavailable('synthetic mode: no measured geometry');
  if (!(ageMs <= STALE_MS)) return unavailable(`no new probe frame for ${Math.round(ageMs / 1000)} s`);
  const geometry = payload.exploratory_geometry;
  if (!geometry || typeof geometry !== 'object') return unavailable('payload carries no exploratory geometry');
  if (geometry.kind !== GEOMETRY_KIND) return unavailable('unsupported exploratory geometry payload');
  if (geometry.frame_id !== payload.frame_id) return unavailable('geometry is not from this frame');
  const supplied = geometry.values && typeof geometry.values === 'object' ? geometry.values : {};
  const values = emptyValues();
  for (const metric of GEOMETRY_METRICS) {
    const value = supplied[metric.key];
    values[metric.key] = typeof value === 'number' && Number.isFinite(value) ? value : null;
  }
  return { values, reason: 'current-frame exploratory values; N/A means unavailable', frameId };
}
