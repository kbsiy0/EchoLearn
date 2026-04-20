/**
 * Tests for useLoopSegment — seeks to segment.start once per segment cycle
 * when currentTime reaches segment.end - AUTO_PAUSE_EPSILON (loop mode).
 *
 * Key invariants tested:
 * - seekTo fires at most once per cycle (fire-guard)
 * - Watermark guard holds across ~190ms IFrame postMessage transient
 * - Guard re-arms after watermark is crossed
 * - Degenerate segments (too-short, zero, negative) are no-ops
 * - pauseVideo is NEVER called
 * - RAF cleanup on unmount
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Segment } from './useSubtitleSync';
import { useLoopSegment } from './useLoopSegment';

const EPSILON = 0.08;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function makePlayer(
  getCurrentTime: () => number,
  seekTo = vi.fn(),
  pauseVideo = vi.fn(),
): YT.Player {
  return { getCurrentTime, seekTo, pauseVideo } as unknown as YT.Player;
}

function makeSegment(
  overrides: Partial<Segment> & Pick<Segment, 'idx' | 'start' | 'end'>,
): Segment {
  return {
    text_en: 'Hello.',
    text_zh: '你好。',
    words: [],
    ...overrides,
  };
}

const SEG_A: Segment = makeSegment({ idx: 0, start: 1.0, end: 4.0 });
const SEG_B: Segment = makeSegment({ idx: 1, start: 5.0, end: 9.0 });
const SEGMENTS: Segment[] = [SEG_A, SEG_B];

/** Advance one RAF frame (16ms) */
async function tick(): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(16);
  });
}

/** Run N RAF ticks */
async function ticks(n: number): Promise<void> {
  for (let i = 0; i < n; i++) await tick();
}

describe('useLoopSegment', () => {
  it('test_fires_seek_at_end_minus_epsilon', async () => {
    // seekTo(seg.start, true) fires exactly once; pauseVideo never called
    const seekTo = vi.fn();
    const pauseVideo = vi.fn();
    const player = makePlayer(() => SEG_A.end - EPSILON, seekTo, pauseVideo);

    renderHook(() => useLoopSegment(player, SEGMENTS, 0, true));
    await tick();

    expect(seekTo).toHaveBeenCalledTimes(1);
    expect(seekTo).toHaveBeenCalledWith(SEG_A.start, true);
    expect(pauseVideo).not.toHaveBeenCalled();
  });

  it('test_no_fire_when_disabled', async () => {
    // enabled=false → zero seekTo calls across ≥10 ticks
    const seekTo = vi.fn();
    const player = makePlayer(() => SEG_A.end - EPSILON, seekTo);

    renderHook(() => useLoopSegment(player, SEGMENTS, 0, false));
    await ticks(10);

    expect(seekTo).not.toHaveBeenCalled();
  });

  it('test_no_fire_before_epsilon_band', async () => {
    // t < end - epsilon → no seek over many ticks
    const seekTo = vi.fn();
    const player = makePlayer(() => SEG_A.end - EPSILON - 0.001, seekTo);

    renderHook(() => useLoopSegment(player, SEGMENTS, 0, true));
    await ticks(15);

    expect(seekTo).not.toHaveBeenCalled();
  });

  it('test_does_not_pause', async () => {
    // pauseVideo is never called, even when seekTo fires
    const seekTo = vi.fn();
    const pauseVideo = vi.fn();
    const player = makePlayer(() => SEG_A.end + 0.1, seekTo, pauseVideo);

    renderHook(() => useLoopSegment(player, SEGMENTS, 0, true));
    await ticks(5);

    expect(pauseVideo).not.toHaveBeenCalled();
  });

  it('test_fire_guard_holds_through_postmessage_transient', async () => {
    // After seek fires, 10 consecutive ticks still reporting t >= end - epsilon
    // must produce ZERO additional seekTo calls (watermark guard blocks them).
    const seekTo = vi.fn();
    // getCurrentTime always reports the old end-of-segment value (simulating the
    // ~190ms IFrame postMessage transient where time hasn't updated yet)
    const player = makePlayer(() => SEG_A.end - EPSILON, seekTo);

    renderHook(() => useLoopSegment(player, SEGMENTS, 0, true));

    // First tick fires the seek
    await tick();
    expect(seekTo).toHaveBeenCalledTimes(1);

    // 10 more ticks — still at end-of-segment time, guard must hold
    await ticks(10);
    expect(seekTo).toHaveBeenCalledTimes(1); // still exactly 1
  });

  it('test_fire_guard_rearms_after_watermark_crossed', async () => {
    // After seek fires, once t < midpoint watermark, guard re-arms.
    // Next tick at t >= end - epsilon fires exactly one more seek.
    const seekTo = vi.fn();
    const midpoint = (SEG_A.start + SEG_A.end) / 2; // 2.5
    let reportedTime = SEG_A.end - EPSILON; // starts at fire boundary

    const player = makePlayer(() => reportedTime, seekTo);
    renderHook(() => useLoopSegment(player, SEGMENTS, 0, true));

    // Tick 1: fires seek
    await tick();
    expect(seekTo).toHaveBeenCalledTimes(1);

    // Ticks 2-5: still at end (simulating transient) — guard holds
    await ticks(4);
    expect(seekTo).toHaveBeenCalledTimes(1);

    // Time now crosses below the midpoint watermark → guard should re-arm
    reportedTime = midpoint - 0.01;
    await tick();
    // Guard has re-armed, but t is still < end-epsilon so no new fire yet
    expect(seekTo).toHaveBeenCalledTimes(1);

    // Now time crosses back to end-epsilon → guard is re-armed, fires again
    reportedTime = SEG_A.end - EPSILON;
    await tick();
    expect(seekTo).toHaveBeenCalledTimes(2);
  });

  it('test_guard_resets_on_segment_change', async () => {
    // currentIndex change → next segment's end still triggers a seek (one fire per segment)
    const seekTo = vi.fn();
    let time = SEG_A.end - EPSILON;
    const player = makePlayer(() => time, seekTo);

    const { rerender } = renderHook(
      ({ idx }: { idx: number }) =>
        useLoopSegment(player, SEGMENTS, idx, true),
      { initialProps: { idx: 0 } },
    );

    // Fire once for segment 0
    await tick();
    expect(seekTo).toHaveBeenCalledTimes(1);
    expect(seekTo).toHaveBeenLastCalledWith(SEG_A.start, true);

    // Move to segment 1, time at its end boundary
    time = SEG_B.end - EPSILON;
    rerender({ idx: 1 });
    await tick();

    // Should fire again for segment 1
    expect(seekTo).toHaveBeenCalledTimes(2);
    expect(seekTo).toHaveBeenLastCalledWith(SEG_B.start, true);
  });

  it('test_noop_on_degenerate_segment', async () => {
    // (a) end < start  (b) end == start  (c) end-start == EPSILON (still degenerate)
    // (d) end-start == 2*EPSILON + 0.001 (just barely OK → fires normally)
    const seekTo = vi.fn();

    // (a) end < start
    const degA = makeSegment({ idx: 0, start: 5.0, end: 4.0 });
    // t would be "past end" of the nominal boundary if degenerate check weren't there
    // We put t = 5.0 which is past both start and end
    let time = 5.0;
    const playerA = makePlayer(() => time, seekTo);
    const { unmount: unmountA } = renderHook(() =>
      useLoopSegment(playerA, [degA], 0, true),
    );
    await ticks(20);
    expect(seekTo).not.toHaveBeenCalled();
    unmountA();

    // (b) end == start
    const degB = makeSegment({ idx: 0, start: 3.0, end: 3.0 });
    time = 3.0;
    const playerB = makePlayer(() => time, seekTo);
    const { unmount: unmountB } = renderHook(() =>
      useLoopSegment(playerB, [degB], 0, true),
    );
    await ticks(20);
    expect(seekTo).not.toHaveBeenCalled();
    unmountB();

    // (c) end - start == EPSILON (still degenerate: threshold is 2 * EPSILON)
    const degC = makeSegment({ idx: 0, start: 2.0, end: 2.0 + EPSILON });
    time = 2.0 + EPSILON;
    const playerC = makePlayer(() => time, seekTo);
    const { unmount: unmountC } = renderHook(() =>
      useLoopSegment(playerC, [degC], 0, true),
    );
    await ticks(20);
    expect(seekTo).not.toHaveBeenCalled();
    unmountC();

    // (d) end - start == 2*EPSILON + 0.001 (just barely OK → fires normally)
    const okSeg = makeSegment({ idx: 0, start: 1.0, end: 1.0 + 2 * EPSILON + 0.001 });
    time = okSeg.end - EPSILON; // at fire boundary
    const playerD = makePlayer(() => time, seekTo);
    renderHook(() => useLoopSegment(playerD, [okSeg], 0, true));
    await tick();
    expect(seekTo).toHaveBeenCalledTimes(1);
    expect(seekTo).toHaveBeenCalledWith(okSeg.start, true);
  });

  it('test_raf_cleanup_on_unmount', async () => {
    // After unmount, no further getCurrentTime calls
    let callCount = 0;
    const getCurrentTime = vi.fn(() => {
      callCount++;
      return 0.5; // well before end, so RAF keeps looping
    });
    const player = makePlayer(getCurrentTime);

    const { unmount } = renderHook(() =>
      useLoopSegment(player, SEGMENTS, 0, true),
    );

    // Run a few ticks to prove loop is active
    await ticks(3);
    const countBeforeUnmount = callCount;
    expect(countBeforeUnmount).toBeGreaterThan(0);

    // Unmount — RAF should be cancelled
    unmount();

    // Advance more time — no new getCurrentTime calls
    await ticks(5);
    expect(callCount).toBe(countBeforeUnmount);
  });
});
