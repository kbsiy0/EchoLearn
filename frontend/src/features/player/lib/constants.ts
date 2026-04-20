export const AUTO_PAUSE_EPSILON = 0.08;

export const ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5] as const;
export type PlaybackRate = (typeof ALLOWED_RATES)[number];
