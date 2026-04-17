import { useEffect, useRef } from 'react';
import type { Segment } from './useSubtitleSync';

const AUTO_PAUSE_EPSILON = 0.08;

/**
 * Fires player.pauseVideo() once when currentTime reaches segment.end ± epsilon.
 *
 * - Fires at most once per segment (tracked by lastFiredIndexRef).
 * - Resets fire guard when currentIndex changes.
 * - Disabled when enabled=false or player/segment is absent.
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

  // Reset fire guard whenever the active segment changes
  useEffect(() => {
    lastFiredIndexRef.current = -2;
  }, [currentIndex]);

  useEffect(() => {
    if (!enabled || !player || currentIndex < 0) return;
    const seg = segments[currentIndex];
    if (!seg) return;

    const rafId = requestAnimationFrame(() => {
      if (lastFiredIndexRef.current === currentIndex) return;
      const t = player.getCurrentTime();
      if (t >= seg.end - AUTO_PAUSE_EPSILON) {
        lastFiredIndexRef.current = currentIndex;
        player.pauseVideo();
      }
    });

    return () => cancelAnimationFrame(rafId);
  });
}
