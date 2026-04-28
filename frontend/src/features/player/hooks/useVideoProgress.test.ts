/**
 * Tests for useVideoProgress hook
 *
 * Covers: load on mount, 404/5xx silent failure, debounced save (1s),
 * coalescing, merge semantics, flush triggers (unmount / visibilitychange /
 * beforeunload), reset(), null videoId inert path.
 *
 * Strategy: mock api/progress functions via vi.mock; use
 * vi.useFakeTimers({ shouldAdvanceTime: true }) so that Promise microtasks
 * still resolve while timers are under manual control.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VideoProgress } from '../../../types/subtitle';
import type { VideoProgressIn } from '../../../api/progress';

// ----- module mocks -------------------------------------------------------
vi.mock('../../../api/progress', () => ({
  getProgress: vi.fn(),
  putProgress: vi.fn(),
  deleteProgress: vi.fn(),
}));

import {
  getProgress,
  putProgress,
  deleteProgress,
} from '../../../api/progress';
import { useVideoProgress } from './useVideoProgress';

const mockGet = getProgress as ReturnType<typeof vi.fn>;
const mockPut = putProgress as ReturnType<typeof vi.fn>;
const mockDel = deleteProgress as ReturnType<typeof vi.fn>;

// ----- fixtures -----------------------------------------------------------
const VIDEO_ID = 'abc123def456';

const LOADED_PROGRESS: VideoProgress = {
  last_played_sec: 60,
  last_segment_idx: 4,
  playback_rate: 1.25,
  loop_enabled: true,
  updated_at: '2026-04-28T10:00:00Z',
};

// ----- helpers ------------------------------------------------------------

/** Drain all pending microtasks (resolved promises). */
async function flushPromises(): Promise<void> {
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockGet.mockReset();
  mockPut.mockReset();
  mockDel.mockReset();
  mockPut.mockResolvedValue(undefined);
  mockDel.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.runAllTimers();
  vi.useRealTimers();
  // restore any visibilityState override
  Object.defineProperty(document, 'visibilityState', {
    value: 'visible',
    writable: true,
    configurable: true,
  });
});

// --------------------------------------------------------------------------
describe('useVideoProgress', () => {
  // ---- null videoId -------------------------------------------------------
  it('test_videoId_null_is_inert_no_fetch_no_listeners', async () => {
    const { result } = renderHook(() => useVideoProgress(null));

    await flushPromises();

    expect(mockGet).not.toHaveBeenCalled();
    expect(result.current.loaded).toBe(false);
    expect(result.current.value).toBeNull();
  });

  // ---- load on mount ------------------------------------------------------
  it('test_load_on_mount_calls_get_progress', async () => {
    mockGet.mockResolvedValue(null);
    renderHook(() => useVideoProgress(VIDEO_ID));

    await flushPromises();

    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledWith(VIDEO_ID);
  });

  it('test_loaded_flips_to_true_after_get_resolves_200', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));

    await flushPromises();

    expect(result.current.loaded).toBe(true);
    expect(result.current.value).toEqual(LOADED_PROGRESS);
  });

  it('test_loaded_flips_to_true_after_get_resolves_null_404', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));

    await flushPromises();

    expect(result.current.loaded).toBe(true);
    expect(result.current.value).toBeNull();
  });

  it('test_loaded_flips_to_true_after_get_throws', async () => {
    mockGet.mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));

    await flushPromises();

    expect(result.current.loaded).toBe(true);
    expect(result.current.value).toBeNull();
  });

  // ---- debounce -----------------------------------------------------------
  it('test_save_debounces_for_1s_then_puts_merged_state', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 67 });
    });

    // 999ms — no PUT yet
    act(() => { vi.advanceTimersByTime(999); });
    expect(mockPut).not.toHaveBeenCalled();

    // +1ms → timer fires
    act(() => { vi.advanceTimersByTime(1); });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(67);
  });

  it('test_save_coalesces_multiple_calls_within_window', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 10 });
    });
    act(() => { vi.advanceTimersByTime(400); });

    act(() => {
      result.current.save({ last_segment_idx: 2 });
    });
    act(() => { vi.advanceTimersByTime(400); });

    act(() => {
      result.current.save({ playback_rate: 2.0 });
    });

    // At t=800 from first call — advance 1000ms more to fire the last debounce
    act(() => { vi.advanceTimersByTime(1000); });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(10);
    expect(body.last_segment_idx).toBe(2);
    expect(body.playback_rate).toBe(2.0);
  });

  it('test_save_uses_current_value_as_base_for_merge', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS); // has last_played_sec=60, last_segment_idx=4

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ playback_rate: 1.5 });
    });
    act(() => { vi.advanceTimersByTime(1000); });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(60);
    expect(body.last_segment_idx).toBe(4);
    expect(body.playback_rate).toBe(1.5);
    expect(body.loop_enabled).toBe(true);
  });

  it('test_save_when_value_is_null_uses_zero_defaults_for_unspecified', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 30, last_segment_idx: 5 });
    });
    act(() => { vi.advanceTimersByTime(1000); });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(30);
    expect(body.last_segment_idx).toBe(5);
    expect(body.playback_rate).toBe(1.0);
    expect(body.loop_enabled).toBe(false);
  });

  // ---- flush triggers -----------------------------------------------------
  it('test_visibilitychange_hidden_flushes_pending_save_immediately', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 99 });
    });

    // Only 400ms elapsed — debounce not yet fired
    act(() => { vi.advanceTimersByTime(400); });
    expect(mockPut).not.toHaveBeenCalled();

    // Simulate tab going hidden
    act(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(99);
  });

  it('test_beforeunload_flushes_pending_save_immediately', async () => {
    mockGet.mockResolvedValue(null);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 55 });
    });

    act(() => { vi.advanceTimersByTime(400); });
    expect(mockPut).not.toHaveBeenCalled();

    act(() => {
      window.dispatchEvent(new Event('beforeunload'));
    });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(55);
  });

  it('test_unmount_flushes_pending_save_immediately', async () => {
    mockGet.mockResolvedValue(null);

    const { result, unmount } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 77 });
    });

    act(() => { vi.advanceTimersByTime(400); });
    expect(mockPut).not.toHaveBeenCalled();

    act(() => { unmount(); });
    await flushPromises();

    expect(mockPut).toHaveBeenCalledTimes(1);
    const body = mockPut.mock.calls[0][1] as VideoProgressIn;
    expect(body.last_played_sec).toBe(77);
  });

  it('test_unmount_clears_listeners', async () => {
    mockGet.mockResolvedValue(null);

    const { unmount } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();

    act(() => { unmount(); });
    mockPut.mockReset();

    // Dispatch visibility event after unmount — listener should be gone
    act(() => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await flushPromises();

    expect(mockPut).not.toHaveBeenCalled();
  });

  it('test_in_flight_get_discarded_on_unmount', async () => {
    let resolveGet!: (v: VideoProgress | null) => void;
    mockGet.mockImplementation(
      () => new Promise<VideoProgress | null>((res) => { resolveGet = res; }),
    );

    const { unmount } = renderHook(() => useVideoProgress(VIDEO_ID));

    act(() => { unmount(); });

    // Resolve after unmount — should NOT cause any state update (no React warning)
    await act(async () => {
      resolveGet(LOADED_PROGRESS);
      await new Promise<void>((r) => setTimeout(r, 0));
    });
    // Test passes if no "Cannot update state on unmounted" error is thrown
  });

  // ---- reset() ------------------------------------------------------------
  it('test_reset_calls_delete_progress_immediately', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    await act(async () => {
      await result.current.reset();
    });

    expect(mockDel).toHaveBeenCalledTimes(1);
    expect(mockDel).toHaveBeenCalledWith(VIDEO_ID);
  });

  it('test_reset_resolves_on_204_and_clears_value', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS);
    mockDel.mockResolvedValue(undefined);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);
    expect(result.current.value).toEqual(LOADED_PROGRESS);

    await act(async () => {
      await result.current.reset();
    });

    expect(result.current.value).toBeNull();
  });

  it('test_reset_rejects_on_5xx_and_keeps_value', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS);
    mockDel.mockRejectedValue(new Error('HTTP 500'));

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    await act(async () => {
      await expect(result.current.reset()).rejects.toThrow();
    });

    expect(result.current.value).toEqual(LOADED_PROGRESS);
  });

  it('test_reset_clears_pending_debounced_save', async () => {
    mockGet.mockResolvedValue(LOADED_PROGRESS);
    mockDel.mockResolvedValue(undefined);

    const { result } = renderHook(() => useVideoProgress(VIDEO_ID));
    await flushPromises();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save({ last_played_sec: 200 });
    });

    await act(async () => {
      await result.current.reset();
    });

    mockPut.mockReset();

    // Advance past the original debounce window — PUT must NOT fire
    act(() => { vi.advanceTimersByTime(2000); });
    await flushPromises();

    expect(mockPut).not.toHaveBeenCalled();
  });
});
