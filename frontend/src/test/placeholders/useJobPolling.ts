/**
 * PLACEHOLDER — DO NOT import from production code.
 *
 * This file exists ONLY in T01 so that useJobPolling.test.ts can compile and
 * run against a controllable stub before the real hook is created in T06.
 *
 * When T06 creates frontend/src/features/jobs/hooks/useJobPolling.ts, this
 * placeholder MUST be deleted as part of that same task (per spec invariant).
 *
 * ESLint guard: eslint.config.js has a no-restricted-imports rule preventing
 * files outside src/test/ (and non-test files) from importing anything from
 * src/test/placeholders/.
 */

import { useEffect, useRef, useState } from 'react';

// These types match the spec's JobStatus shape (specs/jobs-api.md).
export interface JobStatus {
  job_id: string;
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  error_code: string | null;
  error_message: string | null;
}

/**
 * Placeholder implementation of useJobPolling.
 *
 * Polls GET /api/subtitles/jobs/{jobId} every `intervalMs` milliseconds (default 1000ms).
 * The intervalMs parameter is exposed for testability — tests pass a short value
 * (e.g. 50ms) to avoid wall-clock waits.
 *
 * Stops on terminal states (completed | failed).
 * Clears interval on unmount.
 * Returns {job: null, error: null} when jobId is null.
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
    // Reset state when jobId changes (including to null).
    setJob(null);
    setError(null);

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
