/**
 * Five-step YouTube playback speed with localStorage persistence.
 *
 * Guards against the IFrame transient where `new YT.Player()` has returned
 * but `onReady` has not fired: calling `setPlaybackRate` in that window
 * throws. Gated on `isReady` + typeof for defence-in-depth (mirrors
 * useSubtitleSync's guard on getCurrentTime).
 */

import { useCallback, useEffect, useState } from 'react';
import { readValidated, writeString } from '../../../lib/storage';
import { ALLOWED_RATES, type PlaybackRate } from '../lib/constants';

export { ALLOWED_RATES, type PlaybackRate };

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

  useEffect(() => {
    if (!player || !isReady) return;
    if (typeof player.setPlaybackRate !== 'function') return;
    player.setPlaybackRate(rate);
  }, [player, isReady, rate]);

  const setRate = useCallback((r: PlaybackRate) => {
    if (!(ALLOWED_RATES as readonly number[]).includes(r)) return;
    setRateState(r);
    writeString(STORAGE_KEY, String(r));
  }, []);

  const stepUp = useCallback(() => {
    setRateState((prev) => {
      const idx = ALLOWED_RATES.indexOf(prev);
      if (idx === ALLOWED_RATES.length - 1) return prev;
      const next = ALLOWED_RATES[idx + 1];
      writeString(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  const stepDown = useCallback(() => {
    setRateState((prev) => {
      const idx = ALLOWED_RATES.indexOf(prev);
      if (idx === 0) return prev;
      const next = ALLOWED_RATES[idx - 1];
      writeString(STORAGE_KEY, String(next));
      return next;
    });
  }, []);

  return { rate, setRate, stepUp, stepDown };
}
