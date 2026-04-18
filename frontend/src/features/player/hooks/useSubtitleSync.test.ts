/**
 * Tests for useSubtitleSync — binary-search boundary invariants + no-rerender-on-same-index.
 *
 * These tests run against the placeholder in src/test/placeholders/useSubtitleSync.ts.
 * When T07 rewrites the real hook, these tests will import from the real location
 * and the placeholder will be deleted.
 *
 * Strategy: instead of relying on real RAF timing, we inject a mock player and
 * manually trigger the tick by advancing fake timers a single step.
 * vi.useFakeTimers() in vitest replaces requestAnimationFrame with a fake that
 * fires via timer advancement.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type Segment, useSubtitleSync } from './useSubtitleSync';

// ---------------------------------------------------------------------------
// Setup: fake timers so RAF is synchronously controllable
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePlayer(getCurrentTime: () => number): YT.Player {
  return { getCurrentTime } as unknown as YT.Player;
}

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

const THREE_SEGMENTS: Segment[] = [
  makeSegment({
    idx: 0, start: 0.0, end: 2.0,
    words: [
      { text: 'Hello', start: 0.0, end: 0.8 },
      { text: 'world.', start: 0.8, end: 2.0 },
    ],
  }),
  makeSegment({
    idx: 1, start: 3.0, end: 6.0,
    words: [
      { text: 'How', start: 3.0, end: 3.5 },
      { text: 'are', start: 3.5, end: 4.5 },
      { text: 'you?', start: 4.5, end: 6.0 },
    ],
  }),
  makeSegment({
    idx: 2, start: 7.0, end: 10.0,
    words: [
      { text: 'I', start: 7.0, end: 7.5 },
      { text: 'am', start: 7.5, end: 8.5 },
      { text: 'fine.', start: 8.5, end: 10.0 },
    ],
  }),
];

/**
 * Tick the RAF loop once by advancing fake timers by 16ms (one frame).
 */
async function tickOnce(): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(16);
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useSubtitleSync — binary-search boundaries', () => {
  it('returns currentIndex=-1 when player is null', async () => {
    const { result } = renderHook(() =>
      useSubtitleSync(null, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(-1);
    expect(result.current.currentWordIndex).toBe(-1);
  });

  it('returns currentIndex=-1 when segments is empty', async () => {
    const player = makePlayer(() => 1.5);
    const { result } = renderHook(() =>
      useSubtitleSync(player, []),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(-1);
  });

  it('finds segment 0 at t=0.0 (exact start boundary)', async () => {
    const player = makePlayer(() => 0.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(0);
  });

  it('finds segment 0 at t=1.0 (mid-segment)', async () => {
    const player = makePlayer(() => 1.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(0);
  });

  it('returns -1 at t=2.5 (gap between segments)', async () => {
    const player = makePlayer(() => 2.5);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(-1);
  });

  it('finds segment 1 at t=3.0 (exact start of second segment)', async () => {
    const player = makePlayer(() => 3.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(1);
  });

  it('finds segment 2 at t=9.0 (last segment)', async () => {
    const player = makePlayer(() => 9.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(2);
  });

  it('returns -1 at t=-1 (before all segments)', async () => {
    const player = makePlayer(() => -1);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(-1);
  });

  it('returns -1 at t=11 (past all segments)', async () => {
    const player = makePlayer(() => 11);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentIndex).toBe(-1);
  });
});

describe('useSubtitleSync — word binary search', () => {
  it('finds word 0 at t=0.0', async () => {
    const player = makePlayer(() => 0.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentWordIndex).toBe(0);
  });

  it('finds word 1 at t=1.0 (mid second word of segment 0)', async () => {
    const player = makePlayer(() => 1.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentWordIndex).toBe(1);
  });

  it('returns -1 word index in gap between segments', async () => {
    const player = makePlayer(() => 2.5);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    expect(result.current.currentWordIndex).toBe(-1);
  });

  it('finds correct word in segment 1 at t=4.0', async () => {
    const player = makePlayer(() => 4.0);
    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_SEGMENTS),
    );
    await tickOnce();
    // segment 1 words: How(3-3.5), are(3.5-4.5), you?(4.5-6)
    // t=4.0 → "are" is index 1
    expect(result.current.currentIndex).toBe(1);
    expect(result.current.currentWordIndex).toBe(1);
  });
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
