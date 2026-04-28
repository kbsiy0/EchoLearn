/**
 * useVideoProgress — loads, saves (debounced), and resets one video's
 * playback progress.
 *
 * Lifecycle:
 *   mount  → GET /api/videos/{id}/progress (once)
 *   save() → debounced 1s PUT; multiple calls within window coalesce
 *   flush  → unmount / visibilitychange=hidden / beforeunload
 *   reset()→ immediate DELETE; resolves on 204, rejects on error
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { VideoProgress } from '../../../types/subtitle';
import {
  getProgress,
  putProgress,
  deleteProgress,
  type VideoProgressIn,
} from '../../../api/progress';

const DEFAULTS: VideoProgressIn = {
  last_played_sec: 0,
  last_segment_idx: 0,
  playback_rate: 1.0,
  loop_enabled: false,
};

export interface UseVideoProgressResult {
  value: VideoProgress | null;
  loaded: boolean;
  save: (partial: Partial<Omit<VideoProgress, 'updated_at'>>) => void;
  reset: () => Promise<void>;
}

export function useVideoProgress(
  videoId: string | null,
): UseVideoProgressResult {
  const [value, setValue] = useState<VideoProgress | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Refs used inside effects/callbacks — never read during render
  const valueRef = useRef<VideoProgress | null>(null);
  const pendingDiffRef = useRef<Partial<VideoProgressIn> | null>(null);
  const debounceHandleRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  // Keep valueRef in sync with state
  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  // ---- helpers (defined before effects so they're stable refs) -----------

  const buildMerged = useCallback(
    (diff: Partial<VideoProgressIn>): VideoProgressIn => {
      const base: VideoProgressIn = valueRef.current
        ? {
            last_played_sec: valueRef.current.last_played_sec,
            last_segment_idx: valueRef.current.last_segment_idx,
            playback_rate: valueRef.current.playback_rate,
            loop_enabled: valueRef.current.loop_enabled,
          }
        : { ...DEFAULTS };
      return { ...base, ...diff };
    },
    [],
  );

  const flushNow = useCallback(() => {
    if (pendingDiffRef.current === null) return;
    const diff = pendingDiffRef.current;
    pendingDiffRef.current = null;
    if (debounceHandleRef.current !== null) {
      clearTimeout(debounceHandleRef.current);
      debounceHandleRef.current = null;
    }
    if (videoId === null) return;
    const body = buildMerged(diff);
    // fire-and-forget
    void putProgress(videoId, body);
  }, [videoId, buildMerged]);

  // ---- main effect: load + listeners + cleanup ---------------------------
  useEffect(() => {
    if (videoId === null) return;

    cancelledRef.current = false;
    setValue(null);
    setLoaded(false);
    valueRef.current = null;

    // Load
    getProgress(videoId).then(
      (result) => {
        if (cancelledRef.current) return;
        setValue(result);
        valueRef.current = result;
        setLoaded(true);
      },
      () => {
        if (cancelledRef.current) return;
        setValue(null);
        valueRef.current = null;
        setLoaded(true);
      },
    );

    // Flush triggers
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flushNow();
    };
    const onBeforeUnload = () => {
      flushNow();
    };

    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('beforeunload', onBeforeUnload);

    return () => {
      cancelledRef.current = true;
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('beforeunload', onBeforeUnload);
      flushNow(); // unmount flush
    };
    // flushNow depends on videoId — videoId is the loop key so this is correct
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  // ---- public API --------------------------------------------------------

  const save = useCallback(
    (partial: Partial<Omit<VideoProgress, 'updated_at'>>) => {
      if (videoId === null) return;

      // Merge incoming partial into the accumulated pending diff
      pendingDiffRef.current = {
        ...(pendingDiffRef.current ?? {}),
        ...partial,
      };

      // Reset debounce timer
      if (debounceHandleRef.current !== null) {
        clearTimeout(debounceHandleRef.current);
      }
      debounceHandleRef.current = setTimeout(() => {
        debounceHandleRef.current = null;
        if (pendingDiffRef.current === null) return;
        const diff = pendingDiffRef.current;
        pendingDiffRef.current = null;
        const body = buildMerged(diff);
        void putProgress(videoId, body);
      }, 1000);
    },
    [videoId, buildMerged],
  );

  const reset = useCallback(async () => {
    if (videoId === null) return;

    // Cancel any pending debounced save
    if (debounceHandleRef.current !== null) {
      clearTimeout(debounceHandleRef.current);
      debounceHandleRef.current = null;
    }
    pendingDiffRef.current = null;

    await deleteProgress(videoId);
    // Only clear value on success (deleteProgress throws on error)
    setValue(null);
    valueRef.current = null;
  }, [videoId]);

  return { value, loaded, save, reset };
}
