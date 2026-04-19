/**
 * Tests for useSubtitleSync — post-resume transition exclusion from stats.
 *
 * Root cause: When auto-pause fires at segment.end, and user resumes, the IFrame
 * postMessage resume latency (~100-200ms) causes the next RAF tick to observe
 * currentTime already ~200ms past the next segment's start. This inflates the
 * sentenceTransitions delta measurement, producing false p95 > 100ms.
 *
 * Fix: detect paused(2) → playing(1) state flip and skip the NEXT stats push
 * for both sentence and word transitions. The UI index update still fires.
 *
 * Tests 1-2 fail against pre-fix code (post-resume transitions ARE recorded).
 * Tests 3-4 pass with any version (buffering and continuous playback are unaffected).
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useSubtitleSync, type Segment } from './useSubtitleSync';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/**
 * Creates a fake YT.Player with controllable getCurrentTime and getPlayerState.
 * Both callbacks are refs so tests can mutate them after construction.
 */
function makePlayerWithState(
  getCurrentTimeFn: () => number,
  getPlayerStateFn: () => number,
): YT.Player {
  return {
    getCurrentTime: getCurrentTimeFn,
    getPlayerState: getPlayerStateFn,
  } as unknown as YT.Player;
}

async function advanceFrames(n: number): Promise<void> {
  for (let i = 0; i < n; i++) {
    await act(async () => {
      vi.advanceTimersByTime(16);
    });
  }
}

// ---------------------------------------------------------------------------
// Fixtures — 3 contiguous segments (no gaps, mirrors real playback)
// ---------------------------------------------------------------------------

// seg0 [0, 5), seg1 [5, 10), seg2 [10, 15)
const SEG0 = makeSegment({
  idx: 0, start: 0.0, end: 5.0,
  words: [
    { text: 'Hello', start: 0.0, end: 2.5 },
    { text: 'world.', start: 2.5, end: 5.0 },
  ],
});
const SEG1 = makeSegment({
  idx: 1, start: 5.0, end: 10.0,
  words: [
    { text: 'How', start: 5.0, end: 7.0 },
    { text: 'are', start: 7.0, end: 10.0 },
  ],
});
const SEG2 = makeSegment({
  idx: 2, start: 10.0, end: 15.0,
  words: [
    { text: 'you?', start: 10.0, end: 12.5 },
    { text: 'Fine.', start: 12.5, end: 15.0 },
  ],
});
const THREE_CONTIGUOUS = [SEG0, SEG1, SEG2];

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  window.__subtitleSyncStats = undefined as unknown as typeof window.__subtitleSyncStats;
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Test 1 — post-resume SENTENCE transition is excluded from stats
// ---------------------------------------------------------------------------

describe('useSubtitleSync — post-resume sentence transition excluded from stats', () => {
  it('skips stats push (but not UI update) for first sentence transition after paused→playing', async () => {
    let currentTime = 1.0;        // start inside seg0
    let playerState = 1;          // playing

    const player = makePlayerWithState(
      () => currentTime,
      () => playerState,
    );

    const { result } = renderHook(() =>
      useSubtitleSync(player, THREE_CONTIGUOUS),
    );

    // --- Step 1: natural seg0 → seg1 transition while playing ---
    // Advance 3 frames inside seg0 first to let hook initialise
    await advanceFrames(3);
    expect(result.current.currentIndex).toBe(0);

    // Reset stats to clean baseline (discard the -1→seg0 init transition)
    window.__subtitleSyncStats = { sentenceTransitions: [], wordTransitions: [] };

    // Move to seg1 (natural transition while playing)
    currentTime = 5.2; // just past seg1.start
    await advanceFrames(3);
    expect(result.current.currentIndex).toBe(1);

    // Stats should have 1 sentence entry (the seg0→seg1 natural transition)
    const statsAfterStep1 = window.__subtitleSyncStats;
    expect(statsAfterStep1?.sentenceTransitions).toHaveLength(1);

    // --- Step 2: player pauses (auto-pause at seg1.end) ---
    playerState = 2; // paused
    currentTime = 9.95;           // near seg1.end
    await advanceFrames(3);

    // Still 1 entry — no new transitions while paused
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);

    // --- Step 3: player resumes — IFrame latency overshoots by ~200ms ---
    playerState = 1; // playing again (paused→playing flip)
    // Simulate IFrame resume latency: time jumps to seg2.start + 0.2
    currentTime = 10.2; // already past seg2.start by 200ms
    await advanceFrames(3);

    // UI MUST update to seg2
    expect(result.current.currentIndex).toBe(2);

    // But stats must NOT have a new entry (post-resume transition skipped)
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);

    // --- Step 4: next natural transition (no further pause) IS recorded ---
    // Advance time out of seg2 into the gap (>= 15.0) → no active segment.
    currentTime = 15.5; // outside all segments (-1)
    await advanceFrames(3);
    // No new sentence entry (transition to -1 isn't pushed per existing logic)
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);

    // Now advance back into seg2 — this is a natural seg entry, flag already
    // cleared in step 3 → this transition IS recorded (skip flag consumed).
    currentTime = 12.0; // seg2 interior
    await advanceFrames(3);
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Test 2 — post-resume WORD transition is excluded from stats
// ---------------------------------------------------------------------------

describe('useSubtitleSync — post-resume word transition excluded from stats', () => {
  it('skips stats push (but not UI update) for first word transition after paused→playing', async () => {
    let currentTime = 0.5;        // inside seg0, word0 (Hello 0-2.5)
    let playerState = 1;          // playing

    const player = makePlayerWithState(
      () => currentTime,
      () => playerState,
    );

    renderHook(() => useSubtitleSync(player, THREE_CONTIGUOUS));

    // --- Step 1: natural word transition within seg0 ---
    await advanceFrames(3); // lands on word0

    // Reset stats after init to get a clean baseline for the word test
    window.__subtitleSyncStats = { sentenceTransitions: [], wordTransitions: [] };

    // Advance to word1 in seg0 (Hello→world.) — natural transition
    currentTime = 3.0; // seg0, word1 (world. 2.5-5.0)
    await advanceFrames(3);

    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(1);

    // --- Step 2: pause ---
    playerState = 2;
    currentTime = 4.8;
    await advanceFrames(2);
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(1);

    // --- Step 3: resume — IFrame latency overshoots into seg1 word0 ---
    playerState = 1; // paused→playing flip
    currentTime = 5.3; // seg1, word0 (How 5.0-7.0)
    await advanceFrames(3);

    // Word index must have advanced (UI updated)
    // (word0 of seg1 = index 0 within segment)
    // But stats push must be skipped
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(1);

    // --- Step 4: natural word transition in seg1 (not skipped) ---
    currentTime = 8.0; // seg1, word1 (are 7.0-10.0)
    await advanceFrames(3);
    // This is a natural transition — word skip flag was consumed — must be recorded
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Test 3 — buffering does NOT trigger skip
// ---------------------------------------------------------------------------

describe('useSubtitleSync — buffering cycle does not trigger post-resume skip', () => {
  it('records the transition after playing→buffering→playing (no pause)', async () => {
    let currentTime = 1.0;        // seg0
    let playerState = 1;          // playing

    const player = makePlayerWithState(
      () => currentTime,
      () => playerState,
    );

    renderHook(() => useSubtitleSync(player, THREE_CONTIGUOUS));

    await advanceFrames(3); // initialise in seg0

    // Reset stats for clean measurement
    window.__subtitleSyncStats = { sentenceTransitions: [], wordTransitions: [] };

    // Enter buffering (state 3) without passing through paused (state 2)
    playerState = 3; // buffering — NOT paused
    await advanceFrames(2);

    // Resume from buffering back to playing
    playerState = 1; // playing (came from buffering, not from paused)
    currentTime = 5.2; // cross seg0→seg1 boundary
    await advanceFrames(3);

    // Transition MUST be recorded — buffering is not a pause
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Test 4 — regression: continuous playback records ALL transitions
// ---------------------------------------------------------------------------

describe('useSubtitleSync — continuous playback records all transitions (no false skips)', () => {
  it('records 3 transitions across 3 segments in pure playing state', async () => {
    const times = [
      1.0,   // seg0 (transition 1)
      2.0,   // seg0
      5.5,   // seg1 (transition 2)
      7.0,   // seg1
      10.5,  // seg2 (transition 3)
      12.0,  // seg2
    ];
    let timeIdx = 0;

    const player = makePlayerWithState(
      () => times[Math.min(timeIdx++, times.length - 1)],
      () => 1, // always playing — no pause
    );

    renderHook(() => useSubtitleSync(player, THREE_CONTIGUOUS));

    for (let i = 0; i < times.length; i++) {
      await advanceFrames(1);
    }

    // All 3 transitions must be recorded (no skip flags were set)
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(3);
  });
});
