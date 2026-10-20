/**
 * Formatting helpers for the player feature.
 * Kept in lib/ so components can re-export from here without triggering
 * react-refresh/only-export-components lint errors.
 */

/** Formats seconds to "M:SS" using floor (not round). e.g. 67.3 → "1:07" */
export function formatPlayedAt(sec: number): string {
  const floored = Math.floor(sec);
  const m = Math.floor(floored / 60);
  const s = floored % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Converts 0-indexed segmentIdx to "第 N 句" (1-indexed display). */
export function formatSegmentLabel(idx: number): string {
  return `第 ${idx + 1} 句`;
}
