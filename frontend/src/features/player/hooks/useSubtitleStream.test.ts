/**
 * Tests for useSubtitleStream — polling hook that fetches subtitle data every
 * 1000ms and stops automatically on terminal status (completed / failed).
 *
 * Strategy:
 * - vi.useFakeTimers() to control setInterval ticks
 * - vi.mock('../../../api/subtitles') to intercept getSubtitles calls
 * - renderHook + act to drive React state updates
 * - Deferred promise pattern for in-flight discard test
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SubtitleResponse } from '../../../types/subtitle';

vi.mock('../../../api/subtitles', () => ({
  getSubtitles: vi.fn(),
}));

import { getSubtitles } from '../../../api/subtitles';
import { useSubtitleStream } from './useSubtitleStream';

const mockGetSubtitles = getSubtitles as ReturnType<typeof vi.fn>;

function makeResp(overrides: Partial<SubtitleResponse> = {}): SubtitleResponse {
  return {
    video_id: 'abc',
    status: 'processing',
    progress: 10,
    title: null,
    duration_sec: null,
    segments: [],
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  mockGetSubtitles.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useSubtitleStream', () => {
  it('test_initial_fetch_fires_synchronously_on_mount', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp());

    renderHook(() => useSubtitleStream('abc'));

    // The call is made synchronously (within the same effect tick); the promise
    // resolution is async, but the *invocation* of getSubtitles should already
    // have happened before we await anything.
    expect(mockGetSubtitles).toHaveBeenCalledTimes(1);
    expect(mockGetSubtitles).toHaveBeenCalledWith('abc');
  });

  it('test_polls_every_1000ms', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'processing' }));

    renderHook(() => useSubtitleStream('abc'));

    // 1 initial fetch already fired
    expect(mockGetSubtitles).toHaveBeenCalledTimes(1);

    // Advance 3 ticks → 3 more fetches
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3001);
    });

    expect(mockGetSubtitles).toHaveBeenCalledTimes(4);
  });

  it('test_updates_data_on_response', async () => {
    const respA = makeResp({ video_id: 'a', progress: 10 });
    const respB = makeResp({ video_id: 'b', progress: 50 });
    const respC = makeResp({ video_id: 'c', progress: 90 });

    mockGetSubtitles
      .mockResolvedValueOnce(respA)
      .mockResolvedValueOnce(respB)
      .mockResolvedValueOnce(respC);

    const { result } = renderHook(() => useSubtitleStream('abc'));

    // After initial fetch resolves
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.data).toEqual(respA);

    // After tick 1
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toEqual(respB);

    // After tick 2
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toEqual(respC);
  });

  it('test_cleans_up_interval_on_unmount', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'processing' }));

    const { unmount } = renderHook(() => useSubtitleStream('abc'));

    // Let initial fetch complete
    await act(async () => { await Promise.resolve(); });

    const callsBeforeUnmount = mockGetSubtitles.mock.calls.length;
    unmount();

    // Advance time after unmount — no more fetches should fire
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(mockGetSubtitles).toHaveBeenCalledTimes(callsBeforeUnmount);
  });

  it('test_null_video_id_is_inert', async () => {
    const { result } = renderHook(() => useSubtitleStream(null));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(mockGetSubtitles).not.toHaveBeenCalled();
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('test_in_flight_fetch_discarded_after_unmount', async () => {
    // Controlled deferred promise — won't resolve until we say so
    let resolveDeferred!: (value: SubtitleResponse) => void;
    const deferred = new Promise<SubtitleResponse>((res) => {
      resolveDeferred = res;
    });
    mockGetSubtitles.mockReturnValueOnce(deferred);

    const { result, unmount } = renderHook(() => useSubtitleStream('abc'));

    // Unmount before the deferred resolves
    unmount();

    // Now resolve the in-flight promise
    await act(async () => {
      resolveDeferred(makeResp({ video_id: 'late' }));
      await Promise.resolve();
    });

    // data must remain null — cancelled flag prevented setData
    expect(result.current.data).toBeNull();
  });

  it('test_transient_error_surfaces_but_does_not_stop_polling', async () => {
    const successResp = makeResp({ status: 'processing', progress: 30 });

    // First call rejects, subsequent call resolves
    mockGetSubtitles
      .mockRejectedValueOnce(new Error('network blip'))
      .mockResolvedValue(successResp);

    const { result } = renderHook(() => useSubtitleStream('abc'));

    // Let initial (failing) fetch settle
    await act(async () => { await Promise.resolve(); });
    expect(result.current.error).not.toBeNull();
    expect(result.current.error?.message).toBe('network blip');

    // Advance 1 tick → success response
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    // Error should be cleared; data populated; polling still continued
    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual(successResp);
    // 2 total calls: 1 initial failure + 1 tick success
    expect(mockGetSubtitles).toHaveBeenCalledTimes(2);
  });

  it('test_videoId_change_restarts_polling', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'processing' }));

    const { rerender } = renderHook(
      ({ videoId }: { videoId: string }) => useSubtitleStream(videoId),
      { initialProps: { videoId: 'a' } },
    );

    await act(async () => { await Promise.resolve(); });
    const callsAfterA = mockGetSubtitles.mock.calls.length;
    expect(callsAfterA).toBe(1);
    expect(mockGetSubtitles).toHaveBeenLastCalledWith('a');

    // Change videoId — effect re-runs, old interval cleared, new fetch fires
    rerender({ videoId: 'b' });

    expect(mockGetSubtitles).toHaveBeenCalledTimes(callsAfterA + 1);
    expect(mockGetSubtitles).toHaveBeenLastCalledWith('b');

    // Advance time — interval for 'b' fires, not 'a'
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    const calls = mockGetSubtitles.mock.calls;
    // All calls after the switch should be for 'b'
    const callsForA = calls.filter(([id]) => id === 'a').length;
    const callsForB = calls.filter(([id]) => id === 'b').length;
    expect(callsForA).toBe(1);
    expect(callsForB).toBeGreaterThanOrEqual(2);
  });

  it('test_stops_polling_after_completed', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'completed' }));

    renderHook(() => useSubtitleStream('abc'));

    // Let initial fetch resolve
    await act(async () => { await Promise.resolve(); });

    // Advance 5 seconds — no further ticks should fire
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    // Only 1 fetch: the initial one. Interval must have been cleared.
    expect(mockGetSubtitles).toHaveBeenCalledTimes(1);
  });

  it('test_stops_polling_after_failed', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'failed' }));

    renderHook(() => useSubtitleStream('abc'));

    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(mockGetSubtitles).toHaveBeenCalledTimes(1);
  });

  it('test_no_memory_leak_on_terminal_then_unmount', async () => {
    mockGetSubtitles.mockResolvedValue(makeResp({ status: 'completed' }));

    const { unmount } = renderHook(() => useSubtitleStream('abc'));

    // Let terminal fetch settle and interval be cleared
    await act(async () => { await Promise.resolve(); });

    // Unmount after terminal stop — must not throw
    expect(() => unmount()).not.toThrow();

    // Advance time — absolutely no further fetches
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(mockGetSubtitles).toHaveBeenCalledTimes(1);
  });
});
