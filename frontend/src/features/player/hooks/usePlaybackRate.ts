/**
 * usePlaybackRate — five-step YouTube playback speed control with persistence.
 *
 * Reads the stored rate on mount. Applies the current rate to the player
 * whenever `player` becomes non-null AND `isReady` is true (IFrame onReady
 * has fired and all IFrame API methods are wired).
 *
 * Guards against the IFrame transient state where `new YT.Player()` has
 * returned but `onReady` has not yet fired — calling `setPlaybackRate` in
 * that window throws TypeError. The `isReady` gate ensures the effect only
 * runs when the API is fully wired. A typeof check provides defence-in-depth.
 *
 * Writes to localStorage on every change (no debounce — five legal values).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { readValidated, writeString } from '../../../lib/storage';

export const ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5] as const;
export type PlaybackRate = (typeof ALLOWED_RATES)[number];

const STORAGE_KEY = 'echolearn.playback_rate';

function parseRate(raw: string): PlaybackRate | null {
  const n = parseFloat(raw);
  return (ALLOWED_RATES as readonly number[]).includes(n)
    ? (n as PlaybackRate)
    : null;
}

export function usePlaybackRate(
  player: YT.Player | null,
  isReady: boolean,
): {
  rate: PlaybackRate;
  setRate: (r: PlaybackRate) => void;
  stepUp: () => void;
  stepDown: () => void;
} {
  const [rate, setRateState] = useState<PlaybackRate>(() =>
    readValidated(STORAGE_KEY, parseRate, 1),
  );

  // Track whether the player was previously null so we can detect the
  // null → non-null transition and apply the current rate exactly once.
  const prevPlayerRef = useRef<YT.Player | null>(null);

  // Apply rate to player whenever player becomes non-null AND isReady is true.
  // isReady in deps ensures the effect re-fires once onReady has wired methods.
  // typeof guard provides defence-in-depth against the IFrame transient state.
  useEffect(() => {
    if (player === null) {
      prevPlayerRef.current = null;
      return;
    }
    if (!isReady || typeof player.setPlaybackRate !== 'function') return;
    player.setPlaybackRate(rate);
    prevPlayerRef.current = player;
  }, [player, isReady, rate]);

  const setRate = useCallback((r: PlaybackRate) => {
    if (!(ALLOWED_RATES as readonly number[]).includes(r)) return;
    setRateState(r);
    writeString(STORAGE_KEY, String(r));
  }, []);

  const stepUp = useCallback(() => {
    setRateState((prev) => {
      const idx = ALLOWED_RATES.indexOf(prev);
      if (idx === ALLOWED_RATES.length - 1) return prev; // already at max
      const next = ALLOWED_RATES[idx + 1];
      writeString(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  const stepDown = useCallback(() => {
    setRateState((prev) => {
      const idx = ALLOWED_RATES.indexOf(prev);
      if (idx === 0) return prev; // already at min
      const next = ALLOWED_RATES[idx - 1];
      writeString(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  return { rate, setRate, stepUp, stepDown };
}
