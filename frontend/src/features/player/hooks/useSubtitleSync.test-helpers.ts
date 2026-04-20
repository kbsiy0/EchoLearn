/**
 * Shared test helpers for useSubtitleSync test suite.
 * Imported by each split test file to avoid duplication.
 */

import { act } from '@testing-library/react';
import { vi } from 'vitest';
import { type Segment } from './useSubtitleSync';

export function makePlayer(getCurrentTime: () => number): YT.Player {
  return { getCurrentTime } as unknown as YT.Player;
}

export function makeSegment(
  overrides: Partial<Segment> & Pick<Segment, 'idx' | 'start' | 'end'>,
): Segment {
  return {
    text_en: 'Hello world.',
    text_zh: '你好世界。',
    words: [],
    ...overrides,
  };
}

export const THREE_SEGMENTS: Segment[] = [
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
export async function tickOnce(): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(16);
  });
}
