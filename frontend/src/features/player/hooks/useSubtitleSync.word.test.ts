/**
 * Tests for useSubtitleSync — word-level binary search.
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
