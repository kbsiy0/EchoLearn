/**
 * Tests for usePlaybackRate — five-step speed control with localStorage persistence.
 *
 * Strategy: stub localStorage via vi.stubGlobal / vi.spyOn, pass a fake YT.Player
 * with a setPlaybackRate spy, use renderHook + act + rerender-with-prop pattern
 * for the player=null → non-null transition tests.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePlaybackRate, type PlaybackRate } from './usePlaybackRate';

const STORAGE_KEY = 'echolearn.playback_rate';

function makePlayer(setPlaybackRate = vi.fn()): YT.Player {
  return { setPlaybackRate } as unknown as YT.Player;
}

/** Convenience: render hook with a ready player (isReady=true). */
function renderReady(playerArg: YT.Player | null = makePlayer()) {
  return renderHook(() => usePlaybackRate(playerArg, true));
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
    const { result } = renderReady();
    expect(result.current.rate).toBe(1);
  });

  it('test_reads_valid_stored_rate_on_mount', () => {
    localStorage.setItem(STORAGE_KEY, '0.75');
    const { result } = renderReady();
    expect(result.current.rate).toBe(0.75);
  });

  it('test_invalid_stored_rate_falls_back_to_one', () => {
    // subcase: out-of-range float
    localStorage.setItem(STORAGE_KEY, '0.6');
    const { result: r1 } = renderReady();
    expect(r1.current.rate).toBe(1);

    // subcase: non-numeric string
    localStorage.setItem(STORAGE_KEY, 'banana');
    const { result: r2 } = renderReady();
    expect(r2.current.rate).toBe(1);

    // subcase: empty string
    localStorage.setItem(STORAGE_KEY, '');
    const { result: r3 } = renderReady();
    expect(r3.current.rate).toBe(1);
  });

  // ── setRate ─────────────────────────────────────────────────────────────────

  it('test_set_rate_updates_state_player_storage', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player, true));

    act(() => { result.current.setRate(0.5); });

    expect(result.current.rate).toBe(0.5);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.5);
    expect(localStorage.getItem(STORAGE_KEY)).toBe('0.5');
  });

  it('test_set_rate_rejects_disallowed_value', () => {
    const setPlaybackRate = vi.fn();
    const player = makePlayer(setPlaybackRate);
    const { result } = renderHook(() => usePlaybackRate(player, true));

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
    const { result } = renderHook(() => usePlaybackRate(player, true));

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
    const { result } = renderHook(() => usePlaybackRate(player, true));

    act(() => { result.current.setRate(0.5); });
    setPlaybackRate.mockClear();

    act(() => { result.current.stepDown(); });

    expect(result.current.rate).toBe(0.5);
    expect(setPlaybackRate).not.toHaveBeenCalled();
  });

  it('test_step_up_from_one', () => {
    const { result } = renderReady();

    // Default is 1
    act(() => { result.current.stepUp(); });
    expect(result.current.rate).toBe(1.25);
  });

  it('test_step_down_from_one', () => {
    const { result } = renderReady();

    act(() => { result.current.stepDown(); });
    expect(result.current.rate).toBe(0.75);
  });

  // ── player null → ready transitions ─────────────────────────────────────────

  it('test_player_null_then_ready_applies_rate_once', () => {
    const setPlaybackRate = vi.fn();

    const { result, rerender } = renderHook(
      ({ player, isReady }: { player: YT.Player | null; isReady: boolean }) =>
        usePlaybackRate(player, isReady),
      { initialProps: { player: null, isReady: false } },
    );

    // Set a rate while player is null — setPlaybackRate must NOT be called yet
    act(() => { result.current.setRate(0.5); });
    expect(setPlaybackRate).not.toHaveBeenCalled();

    // Now player becomes ready (both player ref and isReady flip together)
    const player = makePlayer(setPlaybackRate);
    rerender({ player, isReady: true });

    // setPlaybackRate should be called exactly once with 0.5
    expect(setPlaybackRate).toHaveBeenCalledTimes(1);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.5);
  });

  it('test_stored_rate_applied_when_player_becomes_ready', () => {
    // Seed storage before mount — simulates page load with a prior session's rate
    localStorage.setItem(STORAGE_KEY, '0.75');

    const setPlaybackRate = vi.fn();

    const { rerender } = renderHook(
      ({ player, isReady }: { player: YT.Player | null; isReady: boolean }) =>
        usePlaybackRate(player, isReady),
      { initialProps: { player: null, isReady: false } },
    );

    // No setRate call in test body — this is the common page-load path (M6 fix)
    expect(setPlaybackRate).not.toHaveBeenCalled();

    // Player becomes ready
    const player = makePlayer(setPlaybackRate);
    rerender({ player, isReady: true });

    expect(setPlaybackRate).toHaveBeenCalledTimes(1);
    expect(setPlaybackRate).toHaveBeenCalledWith(0.75);
  });
});

// ── IFrame readiness race ──────────────────────────────────────────────────────

describe('IFrame readiness race', () => {
  /**
   * Reproduces the runtime crash: new YT.Player() returns a stub object whose
   * IFrame methods (setPlaybackRate etc.) are not yet wired. onReady has NOT
   * fired yet, so calling player.setPlaybackRate() throws TypeError.
   *
   * The hook must guard against this by checking both isReady and typeof.
   */

  it('test_does_not_throw_when_player_has_no_setPlaybackRate_on_mount', () => {
    // Simulate IFrame stub: player object without setPlaybackRate wired yet
    const uninitPlayer = {} as unknown as YT.Player;

    expect(() => {
      renderHook(
        ({ player, isReady }: { player: YT.Player | null; isReady: boolean }) =>
          usePlaybackRate(player, isReady),
        { initialProps: { player: uninitPlayer, isReady: false } },
      );
    }).not.toThrow();
  });

  it('test_setPlaybackRate_called_once_after_isReady_transitions_to_true', () => {
    const setPlaybackRate = vi.fn();

    // Start: player object exists but setPlaybackRate is not yet wired (isReady=false)
    const uninitPlayer = {} as unknown as YT.Player;

    const { rerender } = renderHook(
      ({ player, isReady }: { player: YT.Player | null; isReady: boolean }) =>
        usePlaybackRate(player, isReady),
      { initialProps: { player: uninitPlayer, isReady: false } },
    );

    // setPlaybackRate must NOT be called before onReady fires
    expect(setPlaybackRate).not.toHaveBeenCalled();

    // Simulate onReady: same player reference but now methods are wired + isReady=true
    const readyPlayer = makePlayer(setPlaybackRate);
    rerender({ player: readyPlayer, isReady: true });

    // Hook must now call setPlaybackRate with the stored rate (default 1)
    expect(setPlaybackRate).toHaveBeenCalledTimes(1);
    expect(setPlaybackRate).toHaveBeenCalledWith(1 as PlaybackRate);
  });
});
