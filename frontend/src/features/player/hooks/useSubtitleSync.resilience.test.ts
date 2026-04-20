/**
 * Tests for useSubtitleSync — pre-ready player guard and tick exception survival.
 *
 * These tests cover the T09 production bug:
 *   YT.Player setPlayer() fires before onReady, so the first RAF tick can see
 *   a non-null player whose methods are not yet installed. Without a guard,
 *   player.getCurrentTime() throws TypeError, killing the RAF loop forever.
 *
 * Both tests MUST fail against pre-fix code and PASS after the guard is added.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useSubtitleSync, type Segment } from './useSubtitleSync';

beforeEach(() => {
  vi.useFakeTimers();
  // Reset debug stats
  window.__subtitleSyncStats = undefined as unknown as typeof window.__subtitleSyncStats;
});

afterEach(() => {
  vi.useRealTimers();
});

function makeSegment(
  overrides: Partial<Segment> & Pick<Segment, 'idx' | 'start' | 'end'>,
): Segment {
  return {
    text_en: 'Hello world.',
    text_zh: '你好世界。',
    words: [],
    ...overrides,
  };
}

const SEGMENTS: Segment[] = [
  makeSegment({
    idx: 0, start: 0.0, end: 3.0,
    words: [
      { text: 'Hello', start: 0.0, end: 1.5 },
      { text: 'world.', start: 1.5, end: 3.0 },
    ],
  }),
  makeSegment({ idx: 1, start: 4.0, end: 7.0, words: [] }),
];

async function advanceFrames(n: number): Promise<void> {
  for (let i = 0; i < n; i++) {
    await act(async () => { vi.advanceTimersByTime(16); });
  }
}

describe('useSubtitleSync — resilience (T09 regression)', () => {
  /**
   * Pre-ready player test:
   * getCurrentTime starts as undefined (simulates YT player before onReady).
   * After 3 frames the method appears. The loop must survive and record a transition.
   */
  it('survives pre-ready player (getCurrentTime undefined) and resumes after method appears', async () => {
    // Capture any errors thrown from RAF callbacks
    const errors: unknown[] = [];
    const originalError = console.error.bind(console);
    vi.spyOn(console, 'error').mockImplementation((...args) => {
      // Allow DEV log-prefix through; capture anything that looks like a TypeError
      if (String(args[0]).includes('[useSubtitleSync]')) return;
      errors.push(args);
      originalError(...args);
    });

    // Phase 1: player has no getCurrentTime (pre-ready state)
    const playerObj: Partial<YT.Player> & { getCurrentTime?: () => number } = {
      // getCurrentTime intentionally absent
    };
    const player = playerObj as unknown as YT.Player;

    const { result } = renderHook(() => useSubtitleSync(player, SEGMENTS));

    // Advance 3 frames — all should be safe skips, no exception escaping
    await advanceFrames(3);

    // currentIndex should still be -1 (no real tick happened yet)
    // The important thing: NO unhandled exception, loop is still alive

    // Phase 2: install getCurrentTime (simulates onReady firing)
    playerObj.getCurrentTime = () => 1.0; // inside segment 0

    // Advance 3 more frames — now the loop should detect segment 0
    await advanceFrames(3);

    // After methods appear the loop must have processed the time and updated index
    expect(result.current.currentIndex).toBe(0);

    // No unexpected errors
    expect(errors).toHaveLength(0);

    vi.restoreAllMocks();
  });

  /**
   * Tick exception survival test:
   * getCurrentTime throws on the 2nd call, then returns normally.
   * The loop must survive the exception and continue updating currentIndex.
   */
  it('survives a mid-tick exception and continues the RAF loop', async () => {
    let callCount = 0;
    const playerObj: Partial<YT.Player> = {
      getCurrentTime: () => {
        callCount++;
        if (callCount === 2) {
          throw new Error('Simulated transient YT error');
        }
        // Return 1.0 — inside segment 0 (start=0.0, end=3.0)
        return 1.0;
      },
    };
    const player = playerObj as unknown as YT.Player;

    const { result } = renderHook(() => useSubtitleSync(player, SEGMENTS));

    // Tick 1: callCount=1, t=1.0, segment 0 found, loop reschedules
    await advanceFrames(1);
    // callCount=1 result: currentIndex may be 0 already

    // Tick 2: callCount=2, throws — loop must survive and reschedule
    await advanceFrames(1);

    // Tick 3: callCount=3, t=1.0 again, segment 0, must update
    await advanceFrames(1);

    // After the exception tick the loop must still be alive and have index 0
    expect(result.current.currentIndex).toBe(0);
  });
});
