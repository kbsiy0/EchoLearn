/**
 * Tests for useJobPolling — interval, terminal-state stop, cancel-on-unmount, null jobId.
 *
 * These tests run against the placeholder in src/test/placeholders/useJobPolling.ts.
 * When T06 creates the real hook at src/features/jobs/hooks/useJobPolling.ts,
 * these tests will be updated to import from the real location; the placeholder
 * will be deleted.
 *
 * MSW intercepts are defined per-test to keep tests hermetic.
 * We use real timers (no fake timers) with a short intervalMs (50ms) injected
 * into the placeholder so tests don't require wall-clock waits.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../../../test/setup';
import {
  type JobStatus,
  useJobPolling,
} from './useJobPolling';

// Short poll interval for all tests — avoids wall-clock waits
const TEST_INTERVAL_MS = 50;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJob(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    job_id: 'job-001',
    video_id: 'dQw4w9WgXcQ',
    status: 'queued',
    progress: 0,
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useJobPolling', () => {
  it('returns null job and null error when jobId is null', () => {
    const { result } = renderHook(() => useJobPolling(null, TEST_INTERVAL_MS));
    expect(result.current.job).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('polls the jobs endpoint and updates job state', async () => {
    server.use(
      http.get('/api/subtitles/jobs/job-001', () => {
        return HttpResponse.json(makeJob({ status: 'processing', progress: 20 }));
      }),
    );

    const { result } = renderHook(() => useJobPolling('job-001', TEST_INTERVAL_MS));

    await waitFor(() => {
      expect(result.current.job?.status).toBe('processing');
    });
  });

  it('stops polling when status becomes completed', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/subtitles/jobs/job-002', () => {
        callCount++;
        return HttpResponse.json(makeJob({ job_id: 'job-002', status: 'completed', progress: 100 }));
      }),
    );

    const { result } = renderHook(() => useJobPolling('job-002', TEST_INTERVAL_MS));

    await waitFor(() => expect(result.current.job?.status).toBe('completed'));
    const countAfterComplete = callCount;
    expect(countAfterComplete).toBeGreaterThanOrEqual(1);

    // Wait another 200ms (4+ intervals) — call count must not grow
    await new Promise((r) => setTimeout(r, 200));
    expect(callCount).toBe(countAfterComplete);
  });

  it('stops polling when status becomes failed', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/subtitles/jobs/job-003', () => {
        callCount++;
        return HttpResponse.json(
          makeJob({ job_id: 'job-003', status: 'failed', error_code: 'WHISPER_ERROR' }),
        );
      }),
    );

    const { result } = renderHook(() => useJobPolling('job-003', TEST_INTERVAL_MS));

    await waitFor(() => expect(result.current.job?.status).toBe('failed'));
    const countAfterFailed = callCount;

    await new Promise((r) => setTimeout(r, 200));
    expect(callCount).toBe(countAfterFailed);
  });

  it('clears interval on unmount (cancel-on-unmount)', async () => {
    let callCount = 0;
    server.use(
      http.get('/api/subtitles/jobs/job-004', () => {
        callCount++;
        return HttpResponse.json(makeJob({ job_id: 'job-004', status: 'processing' }));
      }),
    );

    const { unmount } = renderHook(() => useJobPolling('job-004', TEST_INTERVAL_MS));

    // Wait for at least one poll
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(1));
    const countAtUnmount = callCount;
    unmount();

    // Wait another 200ms — no more polls should fire
    await new Promise((r) => setTimeout(r, 200));
    expect(callCount).toBe(countAtUnmount);
  });

  it('returns correct job fields from response', async () => {
    server.use(
      http.get('/api/subtitles/jobs/job-005', () => {
        return HttpResponse.json(
          makeJob({ job_id: 'job-005', video_id: 'abc12345678', status: 'queued' }),
        );
      }),
    );

    const { result } = renderHook(() => useJobPolling('job-005', TEST_INTERVAL_MS));

    await waitFor(() => {
      expect(result.current.job?.job_id).toBe('job-005');
      expect(result.current.job?.video_id).toBe('abc12345678');
    });
  });
});
