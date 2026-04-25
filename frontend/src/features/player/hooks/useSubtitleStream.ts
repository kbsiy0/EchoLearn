import { useEffect, useState } from 'react';
import type { SubtitleResponse } from '../../../types/subtitle';
import { getSubtitles } from '../../../api/subtitles';

/**
 * Polls `GET /subtitles/{videoId}` every 1000ms and stops automatically when
 * the response status is "completed" or "failed" (terminal states).
 *
 * - videoId === null → no fetch, no interval (inert)
 * - Transient errors surface via `error` state but do NOT stop polling
 * - `cancelled` flag prevents state-after-unmount
 */
export function useSubtitleStream(videoId: string | null): {
  data: SubtitleResponse | null;
  error: Error | null;
} {
  const [data, setData] = useState<SubtitleResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (videoId === null) return;

    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const tick = async () => {
      try {
        const resp = await getSubtitles(videoId);
        if (cancelled) return;
        setData(resp);
        setError(null);
        if (resp.status === 'completed' || resp.status === 'failed') {
          if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      }
    };

    tick();
    intervalId = setInterval(tick, 1000);

    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [videoId]);

  return { data, error };
}
