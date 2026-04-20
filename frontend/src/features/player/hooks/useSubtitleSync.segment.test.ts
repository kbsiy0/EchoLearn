/**
 * Tests for useSubtitleSync — segment-level binary search boundary invariants.
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
