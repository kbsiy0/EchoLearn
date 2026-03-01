import { useState, useEffect, useRef, useMemo } from 'react';
import type { SubtitleSegment } from '../types/subtitle';

interface UseSubtitleSyncReturn {
  currentIndex: number;
  setCurrentIndex: (index: number) => void;
  currentWordIndex: number;
}

export function useSubtitleSync(
  segments: SubtitleSegment[],
  currentTime: number,
  playerState: number
): UseSubtitleSyncReturn {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentWordIndex, setCurrentWordIndex] = useState(-1);
  const lastIndexRef = useRef(0);

  useEffect(() => {
    // Only auto-advance when playing (playerState === 1)
    if (playerState !== 1 || segments.length === 0) return;

    // Pointer-based search: start from last known index
    let idx = lastIndexRef.current;

    // If current time is before the current segment, search forward from 0
    if (idx >= segments.length || currentTime < segments[idx].start) {
      idx = 0;
    }

    // Search forward from the pointer
    while (idx < segments.length - 1 && currentTime >= segments[idx + 1].start) {
      idx++;
    }

    // Verify the segment actually contains the current time
    // Use <= for end to ensure the last word gets highlighted before moving on
    const seg = segments[idx];
    if (seg && currentTime >= seg.start && currentTime <= seg.end) {
      lastIndexRef.current = idx;
      if (idx !== currentIndex) {
        setCurrentIndex(idx);
      }

      // Find current word within active segment
      const words = seg.words;
      if (words && words.length > 0) {
        let wIdx = -1;
        for (let i = 0; i < words.length; i++) {
          const isLast = i === words.length - 1;
          // Use <= for the last word so it gets highlighted at the boundary
          if (currentTime >= words[i].start && (isLast ? currentTime <= words[i].end : currentTime < words[i].end)) {
            wIdx = i;
            break;
          }
        }
        setCurrentWordIndex(wIdx);
      } else {
        setCurrentWordIndex(-1);
      }
    }
  }, [currentTime, playerState, segments, currentIndex]);

  // Reset pointer when currentIndex is set externally
  const wrappedSetCurrentIndex = useMemo(() => {
    return (index: number) => {
      lastIndexRef.current = index;
      setCurrentIndex(index);
      setCurrentWordIndex(-1);
    };
  }, []);

  return { currentIndex, setCurrentIndex: wrappedSetCurrentIndex, currentWordIndex };
}
