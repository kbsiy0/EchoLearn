/**
 * Tests for useSubtitleSync — stability (no-rerender on same-index) and
 * multi-segment transition stats instrumentation.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSubtitleSync } from './useSubtitleSync';
import { makePlayer, THREE_SEGMENTS, tickOnce } from './useSubtitleSync.test-helpers';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useSubtitleSync — no rerender on same-index tick', () => {
  it('value stays stable when time advances within same segment', async () => {
    let t = 1.0; // stays in segment 0 throughout
    const player = makePlayer(() => t);

    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );

    // First tick — lands in segment 0
    await tickOnce();
    expect(result.current.currentIndex).toBe(0);

    // Advance time but stay within segment 0 (end=2.0)
    t = 1.5;
    await tickOnce();
    expect(result.current.currentIndex).toBe(0);

    t = 1.9;
    await tickOnce();
    expect(result.current.currentIndex).toBe(0);
  });
});

describe('useSubtitleSync — multi-segment transition stats', () => {
  beforeEach(() => {
    // Reset the stats bucket before each test in this suite
    window.__subtitleSyncStats = undefined;
  });

  it('records exactly 3 sentenceTransitions with correct expected values across 3 segments', async () => {
    // THREE_SEGMENTS: seg0 [0,2), seg1 [3,6), seg2 [7,10)
    // Time sequence visits each segment's interior, with gaps in between.
    // We need ≥9 ticks to cross all 3 segment boundaries.
    const times = [
      0.5,  // seg 0 (transition recorded: expected=0.0)
      1.0,  // seg 0 (no transition)
      2.5,  // gap (-1)
      3.0,  // seg 1 (transition recorded: expected=3.0)
      4.0,  // seg 1 (no transition)
      5.5,  // seg 1 (no transition)
      6.5,  // gap (-1)
      7.0,  // seg 2 (transition recorded: expected=7.0)
      8.0,  // seg 2 (no transition)
      9.5,  // seg 2 (no transition)
    ];
    let callIdx = 0;
    const player = makePlayer(() => times[Math.min(callIdx++, times.length - 1)]);

    renderHook(() => useSubtitleSync(player, THREE_SEGMENTS));

    // Tick once per time value
    for (let i = 0; i < times.length; i++) {
      await tickOnce();
    }

    const stats = window.__subtitleSyncStats;
    expect(stats).toBeDefined();
    const transitions = stats!.sentenceTransitions;

    // Exactly 3 entries — one per segment entry, not one per gap or re-entry
    expect(transitions).toHaveLength(3);

    // Each entry's expected value must be the segment's start time
    expect(transitions[0].expected).toBeCloseTo(THREE_SEGMENTS[0].start, 5);
    expect(transitions[1].expected).toBeCloseTo(THREE_SEGMENTS[1].start, 5);
    expect(transitions[2].expected).toBeCloseTo(THREE_SEGMENTS[2].start, 5);
  });
});
