import { useEffect, useRef } from 'react';
import type { Segment } from './useSubtitleSync';
import { AUTO_PAUSE_EPSILON } from '../lib/constants';

/**
 * Seeks to segment.start when currentTime reaches segment.end - AUTO_PAUSE_EPSILON,
 * implementing "loop current segment" behavior.
 *
 * Key properties:
 * - Fires seekTo(start, true) at most once per segment cycle.
 * - Watermark guard: after firing, the guard stays engaged until t drops below
 *   the midpoint (start + end) / 2. This tolerates the ~190ms IFrame postMessage
 *   transient during which getCurrentTime() still reports the old end-of-segment
 *   value.
 * - Degenerate segments (end - start <= 2 * EPSILON) are skipped entirely to
 *   prevent infinite seek storms.
 * - enabled=false → pure no-op; no RAF, no side effects.
 * - Never calls pauseVideo.
 *
 * Signature per specs/sync.md:
 *   useLoopSegment(player, segments, currentIndex, enabled) → void
 */
export function useLoopSegment(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,
): void {
  const lastFiredIndexRef = useRef<number>(-1);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || !player || currentIndex < 0) return;
    const seg = segments[currentIndex];
    if (!seg) return;

    // Reset fire guard for the new segment
    lastFiredIndexRef.current = -1;

    const tick = () => {
      const t = player.getCurrentTime();
      const { start, end } = seg;

      // Degenerate segment: not enough playable room — skip without side effects
      if (end - start <= 2 * AUTO_PAUSE_EPSILON) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const midpoint = (start + end) / 2;

      // Watermark guard-release: once t drops below midpoint, re-arm the guard
      if (lastFiredIndexRef.current === currentIndex && t < midpoint) {
        lastFiredIndexRef.current = -1;
      }

      // Fire condition: at end boundary and guard not yet fired for this index
      if (t >= end - AUTO_PAUSE_EPSILON && lastFiredIndexRef.current !== currentIndex) {
        lastFiredIndexRef.current = currentIndex;
        player.seekTo(start, true);
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
