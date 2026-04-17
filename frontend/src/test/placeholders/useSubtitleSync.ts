/**
 * PLACEHOLDER — DO NOT import from production code.
 *
 * This file exists ONLY in T01 so that useSubtitleSync.test.ts can compile
 * and run binary-search boundary tests before the real hook is rewritten in T07.
 *
 * When T07 rewrites the hook, this placeholder MUST be deleted as part of
 * that same task (per spec invariant).
 *
 * ESLint guard: eslint.config.js has a no-restricted-imports rule preventing
 * files outside src/test/ (and non-test files) from importing anything from
 * src/test/placeholders/.
 */

import { useEffect, useRef, useState } from 'react';

// Segment shape matches specs/jobs-api.md (Segment model)
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

/**
 * Binary search: find the rightmost segment whose start <= t.
 * Returns -1 if no such segment exists.
 */
function binarySearchSegment(segments: Segment[], t: number): number {
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
 * Binary search: find the rightmost word whose start <= t within a segment.
 * Returns -1 if no such word exists.
 */
function binarySearchWord(words: WordTiming[], t: number): number {
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

/**
 * Placeholder implementation matching the spec signature from sync.md:
 *   useSubtitleSync(player: YT.Player | null, segments: Segment[])
 *   → { currentIndex: number; currentWordIndex: number }
 *
 * Uses requestAnimationFrame for timing and binary search for O(log n) lookup.
 * setState is called only on transitions (index change) — no-rerender-on-same-index.
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
  const prevWordIndexRef = useRef(-1);

  useEffect(() => {
    if (!player || segments.length === 0) {
      // Reset to -1 on dependency change that invalidates sync.
      prevIndexRef.current = -1;
      prevWordIndexRef.current = -1;
      setCurrentIndex(-1);
      setCurrentWordIndex(-1);
      return;
    }

    const tick = () => {
      const t = player.getCurrentTime();

      // Find active segment via binary search
      const segIdx = binarySearchSegment(segments, t);
      let activeSegIdx = -1;
      if (segIdx >= 0 && t <= segments[segIdx].end) {
        activeSegIdx = segIdx;
      }

      // Find active word via binary search within the active segment
      let activeWordIdx = -1;
      if (activeSegIdx >= 0) {
        const words = segments[activeSegIdx].words;
        if (words.length > 0) {
          const wIdx = binarySearchWord(words, t);
          if (wIdx >= 0 && t <= words[wIdx].end) {
            activeWordIdx = wIdx;
          }
        }
      }

      // Only call setState on transitions — spec invariant
      if (activeSegIdx !== prevIndexRef.current) {
        prevIndexRef.current = activeSegIdx;
        setCurrentIndex(activeSegIdx);
      }
      if (activeWordIdx !== prevWordIndexRef.current) {
        prevWordIndexRef.current = activeWordIdx;
        setCurrentWordIndex(activeWordIdx);
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
