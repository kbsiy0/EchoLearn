/**
 * Tests for useYouTubePlayer — IFrame API lifecycle via mock.
 *
 * These tests run against the placeholder in src/test/placeholders/useYouTubePlayer.ts.
 * When T07 rewrites the real hook, these tests will import from the real location
 * and the placeholder will be deleted.
 *
 * We mock the global YT.Player constructor to control onReady / onStateChange callbacks.
 */

import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useYouTubePlayer } from './useYouTubePlayer';

// ---------------------------------------------------------------------------
// YT.Player mock
// ---------------------------------------------------------------------------

type YTEventHandlers = {
  onReady?: () => void;
  onStateChange?: (e: { data: number }) => void;
};

let capturedHandlers: YTEventHandlers = {};
let destroyCalledCount = 0;
let mockPlayerInstance: {
  destroy: () => void;
  seekTo: ReturnType<typeof vi.fn>;
  playVideo: ReturnType<typeof vi.fn>;
  pauseVideo: ReturnType<typeof vi.fn>;
} | null = null;

// Must use function() constructor form so `new MockYTPlayer(...)` works
const MockYTPlayer = vi.fn().mockImplementation(function (
  _containerId: string,
  opts: { events: YTEventHandlers },
) {
  capturedHandlers = opts.events ?? {};
  mockPlayerInstance = {
    destroy: () => {
      destroyCalledCount++;
    },
    seekTo: vi.fn(),
    playVideo: vi.fn(),
    pauseVideo: vi.fn(),
  };
  return mockPlayerInstance;
});

beforeEach(() => {
  capturedHandlers = {};
  destroyCalledCount = 0;
  mockPlayerInstance = null;
  MockYTPlayer.mockClear();

  // Install mock on window.YT
  (window as unknown as Record<string, unknown>)['YT'] = {
    Player: MockYTPlayer,
  };
});

afterEach(() => {
  delete (window as unknown as Record<string, unknown>)['YT'];
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useYouTubePlayer', () => {
  it('isReady starts as false before onReady fires', () => {
    const { result } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );
    expect(result.current.isReady).toBe(false);
  });

  it('sets isReady to true when onReady fires', () => {
    const { result } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );

    act(() => {
      capturedHandlers.onReady?.();
    });

    expect(result.current.isReady).toBe(true);
  });

  it('updates playerState when onStateChange fires', () => {
    const { result } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );

    expect(result.current.playerState).toBe(-1);

    act(() => {
      capturedHandlers.onStateChange?.({ data: 1 }); // YT.PlayerState.PLAYING
    });

    expect(result.current.playerState).toBe(1);
  });

  it('playerState reflects paused state (2)', () => {
    const { result } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );

    act(() => {
      capturedHandlers.onStateChange?.({ data: 1 });
    });
    act(() => {
      capturedHandlers.onStateChange?.({ data: 2 });
    });

    expect(result.current.playerState).toBe(2);
  });

  it('calls player.destroy() on unmount', () => {
    const { unmount } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );

    unmount();
    expect(destroyCalledCount).toBe(1);
  });

  it('does not set isReady after unmount (destroyed flag)', () => {
    const { result, unmount } = renderHook(() =>
      useYouTubePlayer('dQw4w9WgXcQ', 'yt-container'),
    );

    unmount();

    // Simulate late onReady callback after unmount
    act(() => {
      capturedHandlers.onReady?.();
    });

    // isReady should NOT be true because the component was destroyed
    expect(result.current.isReady).toBe(false);
  });

  it('does not create player when videoId is null', () => {
    renderHook(() => useYouTubePlayer(null, 'yt-container'));
    expect(MockYTPlayer).not.toHaveBeenCalled();
  });
});
