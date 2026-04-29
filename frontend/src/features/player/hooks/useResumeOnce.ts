/**
 * useResumeOnce — runs the resume sequence exactly once when isReady and
 * progress are loaded. Implements INV-OOB (clamp seek target, binary search)
 * and INV-REF (restoredRef mutated only inside useEffect).
 *
 * Returns:
 *   restoredRef  — ref whose .current flips true after resume runs
 *   showToast    — whether to render ResumeToast
 *   toastMeta    — props to forward to ResumeToast (null when suppressed)
 *   dismissToast — call to hide toast
 */
import { useState, useRef, useEffect } from 'react';
import type { SubtitleResponse } from '../../../types/subtitle';
import type { UseVideoProgressResult } from './useVideoProgress';

const RATE_MIN = 0.5;
const RATE_MAX = 2.0;

/** Binary search: last segment whose start <= seekSec. Returns -1 if none. */
function findSegmentIdx(
  segments: SubtitleResponse['segments'],
  seekSec: number,
): number {
  let lo = 0;
  let hi = segments.length - 1;
  let result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].start <= seekSec) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

interface ResumeOnceResult {
  restoredRef: React.MutableRefObject<boolean>;
  showToast: boolean;
  toastMeta: { playedAtSec: number; segmentIdx: number } | null;
  dismissToast: () => void;
}

export function useResumeOnce(
  progress: UseVideoProgressResult,
  isReady: boolean,
  segments: SubtitleResponse['segments'],
  durationSec: number | undefined,
  seekTo: (sec: number) => void,
  setRate: (rate: number) => void,
  setLoop: (enabled: boolean) => void,
): ResumeOnceResult {
  // INV-REF: restoredRef.current ONLY mutated inside useEffect
  const restoredRef = useRef(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMeta, setToastMeta] = useState<{
    playedAtSec: number;
    segmentIdx: number;
  } | null>(null);

  useEffect(() => {
    if (!isReady || !progress.loaded || restoredRef.current) return;

    if (!progress.value) {
      restoredRef.current = true;
      return;
    }

    restoredRef.current = true;

    const { last_played_sec, playback_rate, loop_enabled } = progress.value;

    // INV-OOB: clamp to [0, duration_sec]; never use raw stored last_segment_idx
    const duration = durationSec ?? 0;
    const seekTarget = Math.min(Math.max(last_played_sec, 0), duration);

    // Clamp rate to [0.5, 2.0]
    const clampedRate = Math.min(Math.max(playback_rate, RATE_MIN), RATE_MAX);

    // Recompute idx via binary search (never index segments[] with stored idx)
    const recomputedIdx = findSegmentIdx(segments, seekTarget);

    seekTo(seekTarget);
    setRate(clampedRate);
    if (loop_enabled) setLoop(loop_enabled);

    // Suppress toast at position 0 (design.md §13)
    if (seekTarget > 0 && recomputedIdx >= 0) {
      setToastMeta({ playedAtSec: seekTarget, segmentIdx: recomputedIdx });
      setShowToast(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReady, progress.loaded, progress.value, segments, durationSec]);
  // seekTo/setRate/setLoop are stable refs — intentionally omitted to avoid
  // spurious re-runs. segments IS included so recompute runs after Phase 1b append.

  const dismissToast = () => setShowToast(false);

  return { restoredRef, showToast, toastMeta, dismissToast };
}
