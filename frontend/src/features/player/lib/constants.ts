export const AUTO_PAUSE_EPSILON = 0.08;

export const ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5] as const;
export type PlaybackRate = (typeof ALLOWED_RATES)[number];

/**
 * Snap an arbitrary numeric playback rate to the nearest ALLOWED_RATES value.
 * Used by resume / restore paths where the persisted rate may fall outside
 * the literal union (e.g. legacy 1.75 / 2.0 from a wider clamp range).
 */
export function snapToAllowedRate(n: number): PlaybackRate {
  return ALLOWED_RATES.reduce((a, b) =>
    Math.abs(b - n) < Math.abs(a - n) ? b : a,
  );
}
