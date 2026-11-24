export const BEGINNING = -1;
export const PLAY_RAMP_MS = 250;
export const PAUSE_RAMP_MS = 200;

export function clock() {
  return performance.timeOrigin + performance.now();
}

export function upperBound(values, target, value = (item) => item) {
  let left = 0;
  let right = values.length;
  while (left < right) {
    const middle = (left + right) >>> 1;
    if (value(values[middle]) <= target) left = middle + 1;
    else right = middle;
  }
  return left;
}

// The track maps logical UTF-16 offsets to line centers in a particular layout.
function interpolate(track, input, from, to) {
  if (!track.length) return from === 0 ? 0 : BEGINNING;
  const next = upperBound(track, input, (point) => point[from]);
  if (next === 0) return track[0][to];
  if (next === track.length) return track.at(-1)[to];
  const a = track[next - 1];
  const b = track[next];
  return a[to] + (b[to] - a[to]) * (input - a[from]) / (b[from] - a[from]);
}

export const yAtPosition = (track, position) => interpolate(track, position, 0, 1);
export const positionAtY = (track, y) => interpolate(track, y, 1, 0);

function elapsedAt(state, now) {
  return state.moving ? Math.max(0, now - state.at) : 0;
}

export function movingAt(state, now) {
  return state.moving && (state.speed > 0 || Boolean(state.ramp &&
    state.ramp.elapsed + elapsedAt(state, now) < state.ramp.duration));
}

function rampTravel(ramp, speed, elapsed) {
  const progress = Math.min(elapsed / ramp.duration, 1);
  // The integral of smoothstep gives the distance while velocity eases between the two speeds.
  return ramp.duration * (ramp.from * progress + (speed - ramp.from) *
    (progress ** 3 - progress ** 4 / 2)) + speed * Math.max(0, elapsed - ramp.duration);
}

export function positionAt(state, track, now) {
  const elapsed = elapsedAt(state, now);
  if (!elapsed) return state.position;
  const { ramp, speed } = state;
  const travel = ramp ? rampTravel(ramp, speed, ramp.elapsed + elapsed) -
    rampTravel(ramp, speed, ramp.elapsed) : elapsed * speed;
  const y = yAtPosition(track, state.position) + travel / 1000;
  return positionAtY(track, y);
}

export function retimeMotion(state, position, now, visible, speed, duration = 0) {
  let ramp = state.ramp;
  const elapsed = ramp && ramp.elapsed + elapsedAt(state, now);
  if (speed !== state.speed) {
    let from = state.speed;
    if (ramp && elapsed < ramp.duration) {
      duration ||= ramp.duration - elapsed;
      const progress = elapsed / ramp.duration;
      const eased = progress ** 2 * (3 - 2 * progress);
      from = ramp.from + (state.speed - ramp.from) * eased;
    }
    ramp = duration > 0 && from !== speed ? { from, duration, elapsed: 0 } : undefined;
  } else if (ramp) {
    // Reuse the remaining curve when a window hides, a cue is reached, or the layout changes.
    ramp = elapsed < ramp.duration ? { ...ramp, elapsed } : undefined;
  }
  return { position, at: now, speed, ramp, moving: visible && Boolean(speed || ramp) };
}

export function cueIndex(cues, position) {
  return cues.length ? Math.max(0, upperBound(cues, position) - 1) : -1;
}

const rowStart = (point) => point[0];

export function readingRowIndex(track, script, position) {
  if (!track.length || position >= script.end) return -1;
  return upperBound(track, Math.max(script.cues[0], position), rowStart) - 1;
}

function cueBounds(script, cue) {
  return [cue === 0 ? BEGINNING : script.cues[cue - 1], script.cues[cue] ?? script.end];
}

export function rememberPosition(script, position) {
  if (!script.cues.length) return { cue: 0, progress: 0 };
  const cue = position < script.cues[0] ? 0 : cueIndex(script.cues, position) + 1;
  const [start, end] = cueBounds(script, cue);
  return { cue, progress: Math.max(0, Math.min(1, (position - start) / (end - start))) };
}

export function restorePosition(script, bookmark) {
  const { cue, progress } = bookmark ?? {};
  if (!script.cues.length || !Number.isInteger(cue) || cue < 0 || cue > script.cues.length) {
    return BEGINNING;
  }
  const [start, end] = cueBounds(script, cue);
  return Number.isFinite(progress) && progress >= 0 && progress <= 1
    ? start + (end - start) * progress : start;
}

export function adjacentCue(cues, position, direction) {
  if (direction < 0 && position <= cues[0]) return undefined;
  const index = cueIndex(cues, position) + direction;
  if (index < 0 && cues.length) return cues[0];
  return cues[index];
}

const shortcuts = new Map([
  [" ", "play"], ["ArrowRight", "next"], ["ArrowLeft", "previous"],
  ["ArrowUp", "faster"], ["ArrowDown", "slower"], ["Home", "reset"], ["Escape", "pause"],
]);

export function transportShortcut(event) {
  const target = event.target;
  if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey ||
      event.metaKey || event.shiftKey || target.closest?.(
        "input, textarea, select, [contenteditable]:not([contenteditable='false'])",
      ) || (event.key === " " && target.closest?.("button, a"))) return undefined;
  return shortcuts.get(event.key);
}
