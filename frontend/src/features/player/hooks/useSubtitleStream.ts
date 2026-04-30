import { useEffect, useState } from 'react';
import type { SubtitleResponse } from '../../../types/subtitle';
import { getSubtitles } from '../../../api/subtitles';

const POLL_INTERVAL_MS = 1000;

/**
 * Polls `GET /subtitles/{videoId}` every POLL_INTERVAL_MS and stops automatically when
 * the response status is "completed" or "failed" (terminal states).
 *
 * - videoId === null → no fetch, no interval (inert)
 * - Transient errors surface via `error` state but do NOT stop polling
 * - `cancelled` flag prevents state-after-unmount
 */
export function useSubtitleStream(videoId: string | null): {
  data: SubtitleResponse | null;
  error: string | null;
} {
  const [data, setData] = useState<SubtitleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (videoId === null) return;

    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const tick = async () => {
      try {
        const resp = await getSubtitles(videoId);
        if (cancelled) return;
        setData((prev) => (sameShape(prev, resp) ? prev : resp));
        setError(null);
        if (resp.status === 'completed' || resp.status === 'failed') {
          if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      }
    };

    tick();
    intervalId = setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [videoId]);

  return { data, error };
}

function sameShape(prev: SubtitleResponse | null, next: SubtitleResponse): boolean {
  if (prev === null) return false;
  return (
    prev.status === next.status &&
    prev.progress === next.progress &&
    prev.segments.length === next.segments.length &&
    prev.error_code === next.error_code
  );
}
