/**
 * Tests for usePlaybackRate — five-step speed control with localStorage persistence.
 *
 * Strategy: stub localStorage via vi.stubGlobal / vi.spyOn, pass a fake YT.Player
 * with a setPlaybackRate spy, use renderHook + act + rerender-with-prop pattern
 * for the player=null → non-null transition tests.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePlaybackRate } from './usePlaybackRate';

const STORAGE_KEY = 'echolearn.playback_rate';

function makePlayer(setPlaybackRate = vi.fn()): YT.Player {
  return { setPlaybackRate } as unknown as YT.Player;
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('usePlaybackRate', () => {
  // ── Mount / init ────────────────────────────────────────────────────────────

  it('test_default_rate_is_one_when_storage_empty', () => {
    const player = makePlayer();
    const { result } = renderHook(() => usePlaybackRate(player));
    expect(result.current.rate).toBe(1);
  });

  it('test_reads_valid_stored_rate_on_mount', () => {
    localStorage.setItem(STORAGE_KEY, '0.75');
    const player = makePlayer();
    const { result } = renderHook(() => usePlaybackRate(player));
    expect(result.current.rate).toBe(0.75);
  });

  it('test_invalid_stored_rate_falls_back_to_one', () => {
    const player = makePlayer();

    // subcase: out-of-range float
    localStorage.setItem(STORAGE_KEY, '0.6');
    const { result: r1 } = renderHook(() => usePlaybackRate(player));
    expect(r1.current.rate).toBe(1);

    // subcase: non-numeric string
    localStorage.setItem(STORAGE_KEY, 'banana');
    const { result: r2 } = renderHook(() => usePlaybackRate(player));
    expect(r2.current.rate).toBe(1);

    // subcase: empty string
    localStorage.setItem(STORAGE_KEY, '');
    const { result: r3 } = renderHook(() => usePlaybackRate(player));
    expect(r3.current.rate).toBe(1);
  });

  // ── setRate ─────────────────────────────────────────────────────────────────

  it('test_set_rate_updates_state_player_storage', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player));

    act(() => { result.current.setRate(0.5); });

    expect(result.current.rate).toBe(0.5);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.5);
    expect(localStorage.getItem(STORAGE_KEY)).toBe('0.5');
  });

  it('test_set_rate_rejects_disallowed_value', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player));

    const before = result.current.rate;
    act(() => { result.current.setRate(0.6 as never); });

    expect(result.current.rate).toBe(before);
    expect(setPlaybackRate).not.toHaveBeenCalledWith(0.6);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  // ── stepUp / stepDown ───────────────────────────────────────────────────────

  it('test_step_up_at_max_is_noop', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player));

    // Navigate to 1.5
    act(() => { result.current.setRate(1.5); });
    setPlaybackRate.mockClear();

    act(() => { result.current.stepUp(); });

    expect(result.current.rate).toBe(1.5);
    expect(setPlaybackRate).not.toHaveBeenCalled();
  });

  it('test_step_down_at_min_is_noop', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player));

    act(() => { result.current.setRate(0.5); });
    setPlaybackRate.mockClear();

    act(() => { result.current.stepDown(); });

    expect(result.current.rate).toBe(0.5);
    expect(setPlaybackRate).not.toHaveBeenCalled();
  });

  it('test_step_up_from_one', () => {
    const player = makePlayer();
    const { result } = renderHook(() => usePlaybackRate(player));

    // Default is 1
    act(() => { result.current.stepUp(); });
    expect(result.current.rate).toBe(1.25);
  });

  it('test_step_down_from_one', () => {
    const player = makePlayer();
    const { result } = renderHook(() => usePlaybackRate(player));

    act(() => { result.current.stepDown(); });
    expect(result.current.rate).toBe(0.75);
  });

  // ── player null → ready transitions ─────────────────────────────────────────

  it('test_player_null_then_ready_applies_rate_once', () => {
    const setPlaybackRate = vi.fn();

    const { result, rerender } = renderHook(
      ({ player }: { player: YT.Player | null }) => usePlaybackRate(player),
      { initialProps: { player: null } },
    );

    // Set a rate while player is null — setPlaybackRate must NOT be called yet
    act(() => { result.current.setRate(0.5); });
    expect(setPlaybackRate).not.toHaveBeenCalled();

    // Now player becomes ready
    const player = makePlayer(setPlaybackRate);
    rerender({ player });

    // setPlaybackRate should be called exactly once with 0.5
    expect(setPlaybackRate).toHaveBeenCalledTimes(1);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.5);
  });

  it('test_stored_rate_applied_when_player_becomes_ready', () => {
    // Seed storage before mount — simulates page load with a prior session's rate
    localStorage.setItem(STORAGE_KEY, '0.75');

    const setPlaybackRate = vi.fn();

    const { rerender } = renderHook(
      ({ player }: { player: YT.Player | null }) => usePlaybackRate(player),
      { initialProps: { player: null } },
    );

    // No setRate call in test body — this is the common page-load path (M6 fix)
    expect(setPlaybackRate).not.toHaveBeenCalled();

    // Player becomes ready
    const player = makePlayer(setPlaybackRate);
    rerender({ player });

    expect(setPlaybackRate).toHaveBeenCalledTimes(1);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.75);
  });
});
