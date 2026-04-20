import { useEffect, useRef } from 'react';
import type { Segment } from './useSubtitleSync';
import { AUTO_PAUSE_EPSILON } from '../lib/constants';

/**
 * Fires player.pauseVideo() once when currentTime reaches segment.end ± epsilon.
 *
 * Uses a sustained RAF loop (mirrors useSubtitleSync) so the check runs every
 * ~16ms regardless of whether React re-renders. Without a sustained loop,
 * the hook would only sample on render ticks — which stop after the last
 * word transition, leaving the segment end undetected.
 *
 * - Fires at most once per segment (tracked by lastFiredIndexRef).
 * - Resets fire guard when currentIndex changes (via the ref reset in the loop).
 * - Disabled when enabled=false or player/segment is absent.
 * - Cleans up cancelAnimationFrame on unmount or dep change.
 *
 * Signature per specs/sync.md:
 *   useAutoPause(player, segments, currentIndex, enabled) → void
 */
export function useAutoPause(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,
): void {
  const lastFiredIndexRef = useRef<number>(-2); // -2 = never fired
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || !player || currentIndex < 0) return;
    const seg = segments[currentIndex];
    if (!seg) return;

    // Reset fire guard for the new segment
    lastFiredIndexRef.current = -2;

    const tick = () => {
      if (lastFiredIndexRef.current === currentIndex) {
        // Already fired for this segment — stop looping
        return;
      }
      const t = player.getCurrentTime();
      if (t >= seg.end - AUTO_PAUSE_EPSILON) {
        lastFiredIndexRef.current = currentIndex;
        player.pauseVideo?.();
        return; // Stop loop after firing
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [player, segments, currentIndex, enabled]);
}
