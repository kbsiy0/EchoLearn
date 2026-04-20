/**
 * Tests for useSubtitleSync — post-resume transition exclusion from stats.
 *
 * IFrame resume sequence: 1(playing)→2(paused)→3(buffering)→1(playing).
 * Post-resume tick arrives with prevState=3, so a simple 2→1 check never
 * fires. Fix: arm seenPauseSinceResume flag on state 2, fire on next state 1.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useSubtitleSync, type Segment } from './useSubtitleSync';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSegment(overrides: Partial<Segment> & Pick<Segment, 'idx' | 'start' | 'end'>): Segment {
  return { text_en: 'Hello world.', text_zh: '你好世界。', words: [], ...overrides };
}

function makePlayer(timeFn: () => number, stateFn: () => number): YT.Player {
  return { getCurrentTime: timeFn, getPlayerState: stateFn } as unknown as YT.Player;
}

async function advanceFrames(n: number): Promise<void> {
  for (let i = 0; i < n; i++) {
    await act(async () => { vi.advanceTimersByTime(16); });
  }
}

const SEG0 = makeSegment({ idx: 0, start: 0.0, end: 5.0,
  words: [{ text: 'Hello', start: 0.0, end: 2.5 }, { text: 'world.', start: 2.5, end: 5.0 }] });
const SEG1 = makeSegment({ idx: 1, start: 5.0, end: 10.0,
  words: [{ text: 'How', start: 5.0, end: 7.0 }, { text: 'are', start: 7.0, end: 10.0 }] });
const SEG2 = makeSegment({ idx: 2, start: 10.0, end: 15.0,
  words: [{ text: 'you?', start: 10.0, end: 12.5 }, { text: 'Fine.', start: 12.5, end: 15.0 }] });
const SEGS = [SEG0, SEG1, SEG2];

function resetStats() {
  window.__subtitleSyncStats = { sentenceTransitions: [], wordTransitions: [] };
}

beforeEach(() => { vi.useFakeTimers(); window.__subtitleSyncStats = undefined as unknown as typeof window.__subtitleSyncStats; });
afterEach(() => { vi.useRealTimers(); });

// ---------------------------------------------------------------------------
// Test 1 — direct 2→1 flip: sentence transition excluded from stats
// ---------------------------------------------------------------------------

describe('direct paused(2)→playing(1) flip excludes sentence transition from stats', () => {
  it('skips stat push but fires UI update', async () => {
    let t = 1.0, state = 1;
    const { result } = renderHook(() => useSubtitleSync(makePlayer(() => t, () => state), SEGS));
    await advanceFrames(3); // init in seg0
    resetStats();

    // Natural transition seg0→seg1
    t = 5.2; await advanceFrames(3);
    expect(result.current.currentIndex).toBe(1);
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);

    // Pause then resume directly (2→1, no buffering — covers mocks/hypothetical)
    state = 2; t = 9.95; await advanceFrames(2);
    state = 1; t = 10.2; await advanceFrames(3); // post-resume overshoot
    expect(result.current.currentIndex).toBe(2); // UI updated
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1); // stat skipped

    // Next natural transition IS recorded (flag consumed)
    t = 15.5; await advanceFrames(2); // gap → -1
    t = 12.0; await advanceFrames(3); // back in seg2
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Test 2 — direct 2→1 flip: word transition excluded from stats
// ---------------------------------------------------------------------------

describe('direct paused(2)→playing(1) flip excludes word transition from stats', () => {
  it('skips word stat push but fires UI update', async () => {
    let t = 0.5, state = 1;
    renderHook(() => useSubtitleSync(makePlayer(() => t, () => state), SEGS));
    await advanceFrames(3); // init in seg0/word0
    resetStats();

    // Natural word transition within seg0
    t = 3.0; await advanceFrames(3);
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(1);

    // Pause then resume directly (2→1)
    state = 2; t = 4.8; await advanceFrames(2);
    state = 1; t = 5.3; await advanceFrames(3); // overshoot into seg1 word0
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(1); // skipped

    // Next natural word transition IS recorded
    t = 8.0; await advanceFrames(3);
    expect(window.__subtitleSyncStats?.wordTransitions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Test 3 — REAL IFrame sequence 1→2→3→1: skip IS armed
// ---------------------------------------------------------------------------

describe('real IFrame sequence 1→2→3→1 arms post-resume skip', () => {
  it('skips sentence stat after paused(2)→buffering(3)→playing(1)', async () => {
    let t = 1.0, state = 1;
    const { result } = renderHook(() => useSubtitleSync(makePlayer(() => t, () => state), SEGS));
    await advanceFrames(3);
    resetStats();

    // Auto-pause at seg0 end
    state = 2; t = 4.95; await advanceFrames(2);
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(0);

    // Buffering intervenes (real IFrame behaviour)
    state = 3; await advanceFrames(2);
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(0);

    // Resume: playing after buffering — flag was set at state 2, fires here
    state = 1; t = 5.2; await advanceFrames(3);
    expect(result.current.currentIndex).toBe(1); // UI updated
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(0); // stat skipped

    // Next natural transition IS recorded
    t = 10.1; await advanceFrames(3);
    expect(result.current.currentIndex).toBe(2);
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Test 4 — 1→3→1 (buffering without pause): skip NOT armed
// ---------------------------------------------------------------------------

describe('buffering-without-pause (1→3→1) does NOT arm skip', () => {
  it('records sentence transition after playing→buffering→playing', async () => {
    let t = 1.0, state = 1;
    renderHook(() => useSubtitleSync(makePlayer(() => t, () => state), SEGS));
    await advanceFrames(3);
    resetStats();

    // Buffering without prior pause
    state = 3; await advanceFrames(2);
    state = 1; t = 5.2; await advanceFrames(3); // crosses seg0→seg1

    // Transition IS recorded — no pause seen, flag was never set
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Test 5 — regression: continuous playback records ALL transitions
// ---------------------------------------------------------------------------

describe('continuous playback records all transitions (no false skips)', () => {
  it('records 3 transitions across 3 segments in pure playing state', async () => {
    const times = [1.0, 2.0, 5.5, 7.0, 10.5, 12.0];
    let idx = 0;
    const player = makePlayer(() => times[Math.min(idx++, times.length - 1)], () => 1);
    renderHook(() => useSubtitleSync(player, SEGS));
    for (let i = 0; i < times.length; i++) { await advanceFrames(1); }
    expect(window.__subtitleSyncStats?.sentenceTransitions).toHaveLength(3);
  });
});
