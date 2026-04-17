/**
 * Tests for useAutoPause — fires pauseVideo once per segment within ±0.08s of segment.end.
 *
 * Strategy: pass a mock player with controllable getCurrentTime + pauseVideo,
 * advance RAF ticks via fake timers, verify fire-once semantics.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Segment } from './useSubtitleSync';
import { useAutoPause } from './useAutoPause';

const EPSILON = 0.08;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function makePlayer(
  getCurrentTime: () => number,
  pauseVideo = vi.fn(),
): YT.Player {
  return { getCurrentTime, pauseVideo } as unknown as YT.Player;
}

function makeSegment(overrides: Partial<Segment> & Pick<Segment, 'idx' | 'start' | 'end'>): Segment {
  return {
    text_en: 'Hello.',
    text_zh: '你好。',
    words: [],
    ...overrides,
  };
}

const SEG_A: Segment = makeSegment({ idx: 0, start: 0.0, end: 3.0 });
const SEG_B: Segment = makeSegment({ idx: 1, start: 4.0, end: 7.0 });
const SEGMENTS: Segment[] = [SEG_A, SEG_B];

async function tick(): Promise<void> {
  await vi.runAllTimersAsync();
}

describe('useAutoPause', () => {
  it('does not pause before segment end boundary', async () => {
    const pauseVideo = vi.fn();
    const player = makePlayer(() => 2.0, pauseVideo); // well before end=3.0
    renderHook(() => useAutoPause(player, SEGMENTS, 0, true));
    await tick();
    expect(pauseVideo).not.toHaveBeenCalled();
  });

  it('pauses when currentTime >= end - epsilon', async () => {
    const pauseVideo = vi.fn();
    // At end - epsilon exactly
    const player = makePlayer(() => SEG_A.end - EPSILON, pauseVideo);
    renderHook(() => useAutoPause(player, SEGMENTS, 0, true));
    await tick();
    expect(pauseVideo).toHaveBeenCalledTimes(1);
  });

  it('pauses when currentTime > end', async () => {
    const pauseVideo = vi.fn();
    const player = makePlayer(() => SEG_A.end + 0.01, pauseVideo);
    renderHook(() => useAutoPause(player, SEGMENTS, 0, true));
    await tick();
    expect(pauseVideo).toHaveBeenCalledTimes(1);
  });

  it('fires at most once per segment (no double-fire on multiple ticks)', async () => {
    const pauseVideo = vi.fn();
    const player = makePlayer(() => SEG_A.end - EPSILON, pauseVideo);
    const { rerender } = renderHook(() =>
      useAutoPause(player, SEGMENTS, 0, true),
    );
    await tick();
    rerender();
    await tick();
    expect(pauseVideo).toHaveBeenCalledTimes(1);
  });

  it('resets fire guard when segment index changes', async () => {
    const pauseVideo = vi.fn();
    let time = SEG_A.end - EPSILON;
    const player = makePlayer(() => time, pauseVideo);

    const { rerender } = renderHook(
      ({ idx }: { idx: number }) => useAutoPause(player, SEGMENTS, idx, true),
      { initialProps: { idx: 0 } },
    );

    // Fire once for segment 0
    await tick();
    expect(pauseVideo).toHaveBeenCalledTimes(1);

    // Move to segment 1 near its end
    time = SEG_B.end - EPSILON;
    rerender({ idx: 1 });
    await tick();
    // Should fire again for segment 1
    expect(pauseVideo).toHaveBeenCalledTimes(2);
  });

  it('does nothing when enabled=false', async () => {
    const pauseVideo = vi.fn();
    const player = makePlayer(() => SEG_A.end - EPSILON, pauseVideo);
    renderHook(() => useAutoPause(player, SEGMENTS, 0, false));
    await tick();
    expect(pauseVideo).not.toHaveBeenCalled();
  });

  it('does nothing when player is null', async () => {
    const pauseVideo = vi.fn();
    renderHook(() => useAutoPause(null, SEGMENTS, 0, true));
    await tick();
    expect(pauseVideo).not.toHaveBeenCalled();
  });

  it('does nothing when currentIndex is -1', async () => {
    const pauseVideo = vi.fn();
    const player = makePlayer(() => 99.0, pauseVideo);
    renderHook(() => useAutoPause(player, SEGMENTS, -1, true));
    await tick();
    expect(pauseVideo).not.toHaveBeenCalled();
  });
});
