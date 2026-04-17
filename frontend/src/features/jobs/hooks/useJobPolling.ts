import { useEffect, useRef, useState } from 'react';

export interface JobStatus {
  job_id: string;
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  error_code: string | null;
  error_message: string | null;
}

/**
 * Polls GET /api/subtitles/jobs/{jobId} every `intervalMs` milliseconds (default 1000ms).
 * The intervalMs parameter is exposed for testability — tests pass a short value (e.g. 50ms).
 *
 * Stops on terminal states (completed | failed).
 * Aborts in-flight fetch and clears interval on unmount.
 * Returns { job: null, error: null } when jobId is null.
 */
export function useJobPolling(
  jobId: string | null,
  intervalMs = 1000,
): {
  job: JobStatus | null;
  error: Error | null;
} {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const terminatedRef = useRef(false);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setJob(null);
    setError(null);
    /* eslint-enable react-hooks/set-state-in-effect */

    if (!jobId) {
      return;
    }

    terminatedRef.current = false;

    const poll = async () => {
      if (terminatedRef.current) return;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const res = await fetch(`/api/subtitles/jobs/${jobId}`, {
          signal: controller.signal,
        });
        if (!res.ok) {
          setError(new Error(`HTTP ${res.status}`));
          return;
        }
        const data: JobStatus = await res.json();
        setJob(data);
        if (data.status === 'completed' || data.status === 'failed') {
          terminatedRef.current = true;
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name !== 'AbortError') {
          setError(err);
        }
      }
    };

    poll();
    intervalRef.current = setInterval(poll, intervalMs);

    return () => {
      terminatedRef.current = true;
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      abortRef.current?.abort();
    };
  }, [jobId, intervalMs]);

  return { job, error };
}
