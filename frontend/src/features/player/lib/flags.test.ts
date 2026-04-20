import { describe, expect, it } from 'vitest';
import { computePlaybackFlags } from './flags';

describe('computePlaybackFlags', () => {
  /**
   * Full (measure, loop) matrix.
   * Invariants:
   *  - At most one of {autoPauseEnabled, loopEnabled} is true.
   *  - (T,*) → both false (measure mode disables everything).
   */
  const cases: [boolean, boolean, boolean, boolean][] = [
    // measure, loop, autoPauseEnabled, loopEnabled
    [false, false, true,  false],
    [false, true,  false, true ],
    [true,  false, false, false],
    [true,  true,  false, false],
  ];

  it.each(cases)(
    'computePlaybackFlags(measure=%s, loop=%s) → autoPause=%s loopEnabled=%s',
    (measure, loop, expectedAutoPause, expectedLoop) => {
      const flags = computePlaybackFlags(measure, loop);

      // at most one flag may be true
      expect(
        (flags.autoPauseEnabled ? 1 : 0) + (flags.loopEnabled ? 1 : 0),
      ).toBeLessThanOrEqual(1);

      expect(flags.autoPauseEnabled).toBe(expectedAutoPause);
      expect(flags.loopEnabled).toBe(expectedLoop);
    },
  );
});
