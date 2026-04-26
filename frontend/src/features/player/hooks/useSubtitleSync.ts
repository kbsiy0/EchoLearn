import { useEffect, useRef, useState } from 'react';

import type { Segment, WordTiming } from '../../../types/subtitle';
export type { Segment, WordTiming };

// Debug stats written to window in DEV mode for ui-verifier p95 measurement.
interface SyncTransition {
  at: number;        // player.getCurrentTime() at transition
  expected: number;  // segment/word start time
  delta: number;     // |at - expected| in seconds
}

declare global {
  interface Window {
    __subtitleSyncStats?: {
      sentenceTransitions: SyncTransition[];
      wordTransitions: SyncTransition[];
    };
  }
}

/** Find the rightmost segment whose start <= t. Returns -1 if none. */
export function binarySearchSegment(segments: Segment[], t: number): number {
  let lo = 0, hi = segments.length - 1, result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (segments[mid].start <= t) { result = mid; lo = mid + 1; }
    else { hi = mid - 1; }
  }
  return result;
}

/** Find the rightmost word whose start <= t. Returns -1 if none. */
export function binarySearchWord(words: WordTiming[], t: number): number {
  let lo = 0, hi = words.length - 1, result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (words[mid].start <= t) { result = mid; lo = mid + 1; }
    else { hi = mid - 1; }
  }
  return result;
}

/** Pushes a sync-stat entry unless skip is armed (post-resume IFrame latency). */
function pushStatIfNotSkipped(
  bucket: SyncTransition[], t: number, expected: number, skip: boolean,
): boolean {
  if (!skip) bucket.push({ at: t, expected, delta: Math.abs(t - expected) });
  return false;
}

/**
 * Syncs the active subtitle segment and word to the player's current time.
 * Uses requestAnimationFrame (~60fps) + binary search (O(log n)).
 * setState only fires on index changes — no wasted re-renders.
 *
 * Signature per specs/sync.md:
 *   useSubtitleSync(player, segments) → { currentIndex, currentWordIndex }
 */
export function useSubtitleSync(
  player: YT.Player | null,
  segments: Segment[],
): { currentIndex: number; currentWordIndex: number } {
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [currentWordIndex, setCurrentWordIndex] = useState(-1);
  const rafRef = useRef<number | null>(null);
  const prevIndexRef = useRef(-1);
  const prevWordRef = useRef(-1);
  const seenPauseRef = useRef(false);
  const skipSentenceRef = useRef(false);
  const skipWordRef = useRef(false);

  useEffect(() => {
    if (!player || segments.length === 0) {
      prevIndexRef.current = -1;
      prevWordRef.current = -1;
      seenPauseRef.current = false;
      skipSentenceRef.current = false;
      skipWordRef.current = false;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentIndex(-1);
      setCurrentWordIndex(-1);
      return;
    }

    if (import.meta.env.DEV) {
      window.__subtitleSyncStats = window.__subtitleSyncStats ?? {
        sentenceTransitions: [],
        wordTransitions: [],
      };
    }

    const tick = () => {
      try {
        // Guard: player may be non-null before onReady wires its methods.
        if (typeof player.getCurrentTime !== 'function') {
          rafRef.current = requestAnimationFrame(tick);
          return;
        }

        const t = player.getCurrentTime();

        // Track paused(2) → playing(1) across any intermediate states (e.g.
        // buffering/3). Real IFrame sequence is 1→2→3→1, not 2→1 directly.
        // seenPauseRef is set on state 2 and consumed on next state 1,
        // arming skip flags so post-resume IFrame latency is excluded from stats.
        const state =
          typeof player.getPlayerState === 'function'
            ? player.getPlayerState() : null;
        if (state !== null) {
          if (state === 2) {
            seenPauseRef.current = true;
          } else if (state === 1 && seenPauseRef.current) {
            seenPauseRef.current = false;
            skipSentenceRef.current = true;
            skipWordRef.current = true;
          }
        }

        // Segment lookup
        const segCandidate = binarySearchSegment(segments, t);
        const activeSegIdx =
          segCandidate >= 0 && t <= segments[segCandidate].end ? segCandidate : -1;

        // Word lookup within active segment
        let activeWordIdx = -1;
        if (activeSegIdx >= 0) {
          const words = segments[activeSegIdx].words;
          if (words.length > 0) {
            const wc = binarySearchWord(words, t);
            activeWordIdx = wc >= 0 && t <= words[wc].end ? wc : -1;
          }
        }

        // setState only on transitions (stats push skipped on post-resume tick)
        if (activeSegIdx !== prevIndexRef.current) {
          if (import.meta.env.DEV && window.__subtitleSyncStats && activeSegIdx >= 0) {
            skipSentenceRef.current = pushStatIfNotSkipped(
              window.__subtitleSyncStats.sentenceTransitions,
              t, segments[activeSegIdx].start, skipSentenceRef.current,
            );
          }
          prevIndexRef.current = activeSegIdx;
          setCurrentIndex(activeSegIdx);
        }

        if (activeWordIdx !== prevWordRef.current) {
          if (
            import.meta.env.DEV && window.__subtitleSyncStats &&
            activeWordIdx >= 0 && activeSegIdx >= 0
          ) {
            skipWordRef.current = pushStatIfNotSkipped(
              window.__subtitleSyncStats.wordTransitions,
              t, segments[activeSegIdx].words[activeWordIdx].start,
              skipWordRef.current,
            );
          }
          prevWordRef.current = activeWordIdx;
          setCurrentWordIndex(activeWordIdx);
        }
      } catch (err) {
        if (import.meta.env.DEV) {
          console.error('[useSubtitleSync] tick error (continuing loop):', err);
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      seenPauseRef.current = false;
      skipSentenceRef.current = false;
      skipWordRef.current = false;
    };
  }, [player, segments]);

  return { currentIndex, currentWordIndex };
}
