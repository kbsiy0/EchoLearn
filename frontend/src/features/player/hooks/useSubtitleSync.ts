import { useEffect, useRef, useState } from 'react';

// -- Types (exported so tests and consumers can use the same shape) ----------

export interface WordTiming {
  text: string;
  start: number;
  end: number;
}

export interface Segment {
  idx: number;
  start: number;
  end: number;
  text_en: string;
  text_zh: string;
  words: WordTiming[];
}

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

// -- Binary search helpers (pure functions, O(log n)) -----------------------

/**
 * Find the rightmost segment whose start <= t.
 * Returns -1 if none.
 */
export function binarySearchSegment(segments: Segment[], t: number): number {
  let lo = 0;
  let hi = segments.length - 1;
  let result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (segments[mid].start <= t) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

/**
 * Find the rightmost word whose start <= t.
 * Returns -1 if none.
 */
export function binarySearchWord(words: WordTiming[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let result = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (words[mid].start <= t) {
      result = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return result;
}

// -- Hook --------------------------------------------------------------------

/**
 * Syncs the active subtitle segment and word to the player's current time.
 *
 * Uses requestAnimationFrame for ~60fps polling.
 * Uses binary search for O(log n) segment/word lookup.
 * setState is called only when index actually changes — no wasted re-renders.
 *
 * Signature per specs/sync.md:
 *   useSubtitleSync(player, segments) → { currentIndex, currentWordIndex }
 */
export function useSubtitleSync(
  player: YT.Player | null,
  segments: Segment[],
): {
  currentIndex: number;
  currentWordIndex: number;
} {
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [currentWordIndex, setCurrentWordIndex] = useState(-1);
  const rafRef = useRef<number | null>(null);
  const prevIndexRef = useRef(-1);
  const prevWordRef = useRef(-1);

  useEffect(() => {
    if (!player || segments.length === 0) {
      prevIndexRef.current = -1;
      prevWordRef.current = -1;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentIndex(-1);
      setCurrentWordIndex(-1);
      return;
    }

    // Initialize debug stats bucket (DEV only)
    if (import.meta.env.DEV) {
      window.__subtitleSyncStats = window.__subtitleSyncStats ?? {
        sentenceTransitions: [],
        wordTransitions: [],
      };
    }

    const tick = () => {
      try {
        // Guard: player may be non-null before onReady wires its methods (T09).
        if (typeof player.getCurrentTime !== 'function') {
          rafRef.current = requestAnimationFrame(tick);
          return;
        }

        const t = player.getCurrentTime();

        // Segment lookup
        const segCandidate = binarySearchSegment(segments, t);
        const activeSegIdx =
          segCandidate >= 0 && t <= segments[segCandidate].end ? segCandidate : -1;

        // Word lookup within active segment
        let activeWordIdx = -1;
        if (activeSegIdx >= 0) {
          const words = segments[activeSegIdx].words;
          if (words.length > 0) {
            const wCandidate = binarySearchWord(words, t);
            activeWordIdx =
              wCandidate >= 0 && t <= words[wCandidate].end ? wCandidate : -1;
          }
        }

        // setState only on transitions
        if (activeSegIdx !== prevIndexRef.current) {
          if (import.meta.env.DEV && window.__subtitleSyncStats && activeSegIdx >= 0) {
            const expected = segments[activeSegIdx].start;
            window.__subtitleSyncStats.sentenceTransitions.push({
              at: t,
              expected,
              delta: Math.abs(t - expected),
            });
          }
          prevIndexRef.current = activeSegIdx;
          setCurrentIndex(activeSegIdx);
        }

        if (activeWordIdx !== prevWordRef.current) {
          if (
            import.meta.env.DEV &&
            window.__subtitleSyncStats &&
            activeWordIdx >= 0 &&
            activeSegIdx >= 0
          ) {
            const words = segments[activeSegIdx].words;
            const expected = words[activeWordIdx].start;
            window.__subtitleSyncStats.wordTransitions.push({
              at: t,
              expected,
              delta: Math.abs(t - expected),
            });
          }
          prevWordRef.current = activeWordIdx;
          setCurrentWordIndex(activeWordIdx);
        }
      } catch (err) {
        // Don't kill the loop on transient errors — log in DEV, silent in prod.
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
    };
  }, [player, segments]);

  return { currentIndex, currentWordIndex };
}
