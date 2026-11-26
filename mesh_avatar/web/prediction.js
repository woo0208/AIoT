// RF prediction display only. The page never classifies posture: it shows the engineering RF demo
// prediction the probe computed for the payload's own frame, or PREDICTION UNAVAILABLE with a reason.
// No thresholds, no history: a missing, stale, mismatched or unknown prediction is never replaced.
export const RF_DEMO_BANNER = 'ENGINEERING RF DEMO — ACCURACY NOT VALIDATED';
export const UNAVAILABLE = 'PREDICTION UNAVAILABLE';
export const STALE_MS = 1000;   // no new probe frame for this long -> unavailable
const DISPLAY_CLASS = { 'UPRIGHT': 'pred-upright', 'FORWARD HEAD': 'pred-fh', 'BODY FORWARD': 'pred-bf' };

// payload: latest /pose payload (or null); ageMs: time since that payload arrived.
export function predictionView(payload, ageMs) {
  const frameId = payload && Number.isInteger(payload.frame_id) ? payload.frame_id : null;
  const unavailable = (reason) => ({ text: UNAVAILABLE, cls: 'pred-na', reason: String(reason), frameId });
  if (!payload || !payload.joints) return unavailable('no probe frame yet');
  if (payload.synthetic) return unavailable('synthetic mode: no RF prediction');
  if (!(ageMs <= STALE_MS)) return unavailable(`no new probe frame for ${Math.round(ageMs / 1000)} s`);
  const p = payload.prediction;
  if (!p || typeof p !== 'object') return unavailable('payload carries no prediction');
  if (p.frame_id !== payload.frame_id) return unavailable('prediction is not from this frame');
  if (p.status !== 'available') return unavailable(p.reason || 'prediction unavailable');
  if (!Object.prototype.hasOwnProperty.call(DISPLAY_CLASS, p.display)) {
    return unavailable(`unsupported prediction: ${p.display}`);
  }
  return { text: p.display, cls: DISPLAY_CLASS[p.display], reason: p.reason || '', frameId };
}
