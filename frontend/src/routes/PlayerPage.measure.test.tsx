/**
 * Tests for PlayerPage ?measure=1 query flag.
 *
 * Asserts that:
 * 1. Without ?measure=1, useAutoPause is called with enabled=true
 * 2. With ?measure=1, useAutoPause is called with enabled=false
 *
 * Strategy: vi.mock() useAutoPause to spy on the enabled argument;
 * mock useSubtitleStream to return a completed SubtitleResponse so that
 * CompletedLayout renders and calls useAutoPause;
 * render PlayerPage via MemoryRouter with appropriate initialEntries.
 */

import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { SubtitleResponse } from '../types/subtitle';

// --- module mocks (must be at top level, before imports) ---

vi.mock('../features/player/hooks/useSubtitleStream', () => ({
  useSubtitleStream: vi.fn(),
}));

vi.mock('../features/player/hooks/useAutoPause', () => ({
  useAutoPause: vi.fn(),
}));

vi.mock('../features/player/hooks/useLoopSegment', () => ({
  useLoopSegment: vi.fn(),
}));

vi.mock('../features/player/hooks/useYouTubePlayer', () => ({
  useYouTubePlayer: vi.fn(() => ({
    player: null,
    isReady: false,
    playerState: -1,
    seekTo: vi.fn(),
    playVideo: vi.fn(),
    pauseVideo: vi.fn(),
  })),
}));

vi.mock('../features/player/hooks/useSubtitleSync', () => ({
  useSubtitleSync: vi.fn(() => ({ currentIndex: -1, currentWordIndex: -1 })),
}));

vi.mock('../features/player/hooks/useKeyboardShortcuts', () => ({
  useKeyboardShortcuts: vi.fn(),
}));

vi.mock('../features/player/hooks/usePlaybackRate', () => ({
  usePlaybackRate: vi.fn(() => ({ rate: 1, setRate: vi.fn(), stepUp: vi.fn(), stepDown: vi.fn() })),
  ALLOWED_RATES: [0.5, 0.75, 1, 1.25, 1.5],
}));

// Import after mocks
import { useSubtitleStream } from '../features/player/hooks/useSubtitleStream';
import { useAutoPause } from '../features/player/hooks/useAutoPause';
import { PlayerPage } from './PlayerPage';

// ---

const COMPLETED_DATA: SubtitleResponse = {
  video_id: 'abc',
  status: 'completed',
  progress: 100,
  title: 'Test Video',
  duration_sec: 60,
  segments: [
    {
      idx: 0,
      start: 0,
      end: 5,
      text_en: 'Hello',
      text_zh: '你好',
      words: [{ text: 'Hello', start: 0, end: 2 }],
    },
  ],
  error_code: null,
  error_message: null,
};

function renderPlayerPage(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/watch/:videoId" element={<PlayerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PlayerPage ?measure=1 flag', () => {
  beforeEach(() => {
    vi.mocked(useAutoPause).mockClear();
    // Return completed data so CompletedLayout renders and useAutoPause is called
    vi.mocked(useSubtitleStream).mockReturnValue({ data: COMPLETED_DATA, error: null });
  });

  it('passes enabled=true to useAutoPause when ?measure=1 is absent', () => {
    renderPlayerPage('/watch/abc');

    const calls = vi.mocked(useAutoPause).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    // enabled is the 4th argument (index 3)
    const enabledValues = calls.map((c) => c[3]);
    expect(enabledValues.every((v) => v === true)).toBe(true);
  });

  it('passes enabled=false to useAutoPause when ?measure=1 is present', () => {
    renderPlayerPage('/watch/abc?measure=1');

    const calls = vi.mocked(useAutoPause).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    // enabled is the 4th argument (index 3)
    const enabledValues = calls.map((c) => c[3]);
    expect(enabledValues.every((v) => v === false)).toBe(true);
  });
});
