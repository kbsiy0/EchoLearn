/**
 * Derive playback mode flags from the measure and loop booleans.
 * Invariant: at most one of {autoPauseEnabled, loopEnabled} is true.
 * measure=true disables both (raw measurement mode — no auto-pausing or looping).
 */
export function computePlaybackFlags(
  measure: boolean,
  loop: boolean,
): { autoPauseEnabled: boolean; loopEnabled: boolean } {
  return {
    autoPauseEnabled: !measure && !loop,
    loopEnabled: !measure && loop,
  };
}
