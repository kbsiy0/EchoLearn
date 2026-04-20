/**
 * Tests for PlayerPage ?measure=1 query flag.
 *
 * Asserts that:
 * 1. Without ?measure=1, useAutoPause is called with enabled=true
 * 2. With ?measure=1, useAutoPause is called with enabled=false
 *
 * Strategy: vi.mock() useAutoPause to spy on the enabled argument;
 * render PlayerPage via MemoryRouter with appropriate initialEntries.
 * Also mock all other hooks that make network/DOM calls to keep tests hermetic.
 */

import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

// --- module mocks (must be at top level, before imports) ---

vi.mock('../features/player/hooks/useAutoPause', () => ({
  useAutoPause: vi.fn(),
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

vi.mock('../api/subtitles', () => ({
  getSubtitles: vi.fn(() => new Promise(() => {})), // never resolves → stays in loading state
}));

// Import after mocks
import { useAutoPause } from '../features/player/hooks/useAutoPause';
import { PlayerPage } from './PlayerPage';

// ---

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
