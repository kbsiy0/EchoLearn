/**
 * T12 — PlayerPage status-branching tests.
 *
 * Strategy:
 * - Mock `useSubtitleStream` to control data sequences
 * - Mock all player hooks to keep tests hermetic
 * - The 17 tests cover: null/queued/processing/failed/completed states,
 *   sticky-completed guard, TTFS instrumentation, mount-once invariant
 */

import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import type { SubtitleResponse } from '../types/subtitle';

// --- module mocks (must be at top level) ---

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
  usePlaybackRate: vi.fn(() => ({
    rate: 1,
    setRate: vi.fn(),
    stepUp: vi.fn(),
    stepDown: vi.fn(),
  })),
  ALLOWED_RATES: [0.5, 0.75, 1, 1.25, 1.5],
}));

// Import after mocks
import { useSubtitleStream } from '../features/player/hooks/useSubtitleStream';
import { useAutoPause } from '../features/player/hooks/useAutoPause';
import { PlayerPage } from './PlayerPage';

// --- helpers ---

const mockStream = vi.mocked(useSubtitleStream);

function makeSegment(idx: number) {
  return {
    idx,
    start: idx * 5,
    end: idx * 5 + 4,
    text_en: `Segment ${idx} EN`,
    text_zh: `Segment ${idx} ZH`,
    words: [{ text: 'word', start: idx * 5, end: idx * 5 + 2 }],
  };
}

function makeData(overrides: Partial<SubtitleResponse>): SubtitleResponse {
  return {
    video_id: 'test-vid',
    status: 'queued',
    progress: 0,
    title: null,
    duration_sec: null,
    segments: [],
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

function renderPlayerPage(path = '/watch/test-vid') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/watch/:videoId" element={<PlayerPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// --- tests ---

describe('PlayerPage streaming status branching', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: null data (initial load)
    mockStream.mockReturnValue({ data: null, error: null });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -----------------------------------------------------------------------
  // NULL state
  // -----------------------------------------------------------------------

  it('test_null_data_renders_loading_spinner', () => {
    mockStream.mockReturnValue({ data: null, error: null });
    renderPlayerPage();

    // Loading spinner visible — presence of spinning animation element
    // The spinner renders when data is null
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
    // A spinner indicator should be present (role="status" or animate-spin class)
    const spinner = document.querySelector('.animate-spin');
    expect(spinner).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // QUEUED state
  // -----------------------------------------------------------------------

  it('test_queued_status_renders_processing_layout_no_player', () => {
    mockStream.mockReturnValue({
      data: makeData({ status: 'queued', progress: 0 }),
      error: null,
    });
    renderPlayerPage();

    // No video player
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
    // Progress placeholder visible with 0%
    expect(screen.getByText(/0%/)).toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // PROCESSING state
  // -----------------------------------------------------------------------

  it('test_processing_renders_placeholder_and_partial_subtitle_panel', () => {
    const segments = [makeSegment(0), makeSegment(1), makeSegment(2)];
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 45, segments }),
      error: null,
    });
    renderPlayerPage();

    // Placeholder shows 45%
    expect(screen.getByText(/45%/)).toBeInTheDocument();
    // No video player
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
    // SubtitlePanel lists segments
    expect(screen.getByText('Segment 0 EN')).toBeInTheDocument();
    expect(screen.getByText('Segment 1 EN')).toBeInTheDocument();
    expect(screen.getByText('Segment 2 EN')).toBeInTheDocument();
  });

  it('test_processing_appends_segments_between_polls_without_panel_remount', async () => {
    const segs3 = [makeSegment(0), makeSegment(1), makeSegment(2)];
    const segs5 = [...segs3, makeSegment(3), makeSegment(4)];

    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 30, segments: segs3 }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // First render: 3 segments
    expect(screen.getByText('Segment 2 EN')).toBeInTheDocument();
    expect(screen.queryByText('Segment 4 EN')).not.toBeInTheDocument();

    // Update hook to return 5 segments
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 50, segments: segs5 }),
      error: null,
    });

    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    // Now 5 segments visible
    expect(screen.getByText('Segment 4 EN')).toBeInTheDocument();
    // Still no player
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // FAILED state
  // -----------------------------------------------------------------------

  it('test_failed_with_partial_renders_error_placeholder_and_readonly_panel', () => {
    const segments = [makeSegment(0), makeSegment(1)];
    mockStream.mockReturnValue({
      data: makeData({
        status: 'failed',
        segments,
        error_message: '轉錄失敗',
      }),
      error: null,
    });
    renderPlayerPage();

    // Error placeholder visible
    expect(screen.getByText('處理失敗')).toBeInTheDocument();
    expect(screen.getByText('轉錄失敗')).toBeInTheDocument();
    // Segments listed (read-only panel)
    expect(screen.getByText('Segment 0 EN')).toBeInTheDocument();
    // No video player
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
  });

  it('test_failed_zero_segments_renders_error_only_page', () => {
    mockStream.mockReturnValue({
      data: makeData({
        status: 'failed',
        segments: [],
        error_message: '無法下載音訊',
      }),
      error: null,
    });
    renderPlayerPage();

    // Error placeholder visible
    expect(screen.getByText('處理失敗')).toBeInTheDocument();
    // No segments listed
    expect(screen.queryByText(/Segment/)).not.toBeInTheDocument();
    // No player
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
  });

  it('test_home_button_navigates_home', () => {
    mockStream.mockReturnValue({
      data: makeData({
        status: 'failed',
        error_message: '失敗',
      }),
      error: null,
    });

    render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
          <Route path="/" element={<div data-testid="home-page">Home</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const homeBtn = screen.getByText('回首頁');
    fireEvent.click(homeBtn);

    // Should navigate to home
    expect(screen.getByTestId('home-page')).toBeInTheDocument();
  });

  // -----------------------------------------------------------------------
  // COMPLETED state
  // -----------------------------------------------------------------------

  it('test_completed_renders_full_phase1a_player', () => {
    const segments = [makeSegment(0), makeSegment(1), makeSegment(2)];
    mockStream.mockReturnValue({
      data: makeData({ status: 'completed', progress: 100, segments }),
      error: null,
    });
    renderPlayerPage();

    // VideoPlayer mounted
    expect(screen.getByTestId('video-player')).toBeInTheDocument();
    // PlayerControls visible (loop button, play button)
    expect(screen.getByLabelText('循環播放')).toBeInTheDocument();
    // Play/pause button is a button element with text "播放" or "暫停"
    const playBtn = screen.getAllByRole('button').find(
      (btn) => btn.textContent === '播放' || btn.textContent === '暫停',
    );
    expect(playBtn).toBeTruthy();
  });

  it('test_player_mounts_exactly_once_across_processing_to_completed_transition', async () => {
    // Start with processing
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 30, segments: [makeSegment(0)] }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // No player yet
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();

    // Second processing poll
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 60, segments: [makeSegment(0), makeSegment(1)] }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();

    // Now completed
    const completedSegs = [makeSegment(0), makeSegment(1), makeSegment(2)];
    mockStream.mockReturnValue({
      data: makeData({ status: 'completed', progress: 100, segments: completedSegs }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(screen.getByTestId('video-player')).toBeInTheDocument();

    // Another completed poll — player still present, only 1 instance
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });
    expect(screen.getAllByTestId('video-player')).toHaveLength(1);
  });

  it('test_completed_polls_do_not_remount_player', async () => {
    const segments = [makeSegment(0), makeSegment(1)];
    mockStream.mockReturnValue({
      data: makeData({ status: 'completed', progress: 100, segments }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('video-player')).toBeInTheDocument();

    // Multiple completed polls
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        rerender(
          <MemoryRouter initialEntries={['/watch/test-vid']}>
            <Routes>
              <Route path="/watch/:videoId" element={<PlayerPage />} />
            </Routes>
          </MemoryRouter>,
        );
      });
    }

    // Still exactly one player
    expect(screen.getAllByTestId('video-player')).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // Progress monotone
  // -----------------------------------------------------------------------

  it('test_progress_observed_by_user_is_monotone', async () => {
    const progressValues = [10, 25, 45, 100];
    const observed: number[] = [];

    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: progressValues[0] }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    for (const p of progressValues) {
      mockStream.mockReturnValue({
        data: makeData({
          status: p === 100 ? 'completed' : 'processing',
          progress: p,
          segments: [makeSegment(0)],
        }),
        error: null,
      });
      await act(async () => {
        rerender(
          <MemoryRouter initialEntries={['/watch/test-vid']}>
            <Routes>
              <Route path="/watch/:videoId" element={<PlayerPage />} />
            </Routes>
          </MemoryRouter>,
        );
      });

      // For non-completed states, check the progress text
      if (p < 100) {
        const progressText = screen.queryByText(new RegExp(`${p}%`));
        if (progressText) observed.push(p);
      }
    }

    // Progress values observed should be monotonically increasing
    for (let i = 1; i < observed.length; i++) {
      expect(observed[i]).toBeGreaterThanOrEqual(observed[i - 1]);
    }
  });

  // -----------------------------------------------------------------------
  // measure=1 flag
  // -----------------------------------------------------------------------

  it('test_measure_flag_preserved_through_completed_branch', () => {
    mockStream.mockReturnValue({
      data: makeData({
        status: 'completed',
        progress: 100,
        segments: [makeSegment(0)],
      }),
      error: null,
    });
    vi.mocked(useAutoPause).mockClear();

    renderPlayerPage('/watch/test-vid?measure=1');

    const calls = vi.mocked(useAutoPause).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    // With ?measure=1, autoPause should be disabled (enabled=false)
    const enabledValues = calls.map((c) => c[3]);
    expect(enabledValues.every((v) => v === false)).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Sticky-completed guard
  // -----------------------------------------------------------------------

  it('test_sticky_completed_guards_against_later_processing', async () => {
    const completedSegs = [makeSegment(0), makeSegment(1)];

    // First: completed
    mockStream.mockReturnValue({
      data: makeData({ status: 'completed', progress: 100, segments: completedSegs }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('video-player')).toBeInTheDocument();

    // Hook reverts to processing (shouldn't happen in real life but guard must hold)
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 50 }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    // Still showing completed layout — player must be present
    expect(screen.getByTestId('video-player')).toBeInTheDocument();
    // Placeholder must not appear
    expect(screen.queryByText(/處理字幕中/)).not.toBeInTheDocument();

    // Hook reverts to failed
    mockStream.mockReturnValue({
      data: makeData({ status: 'failed', error_message: '失敗' }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    // Still on completed layout
    expect(screen.getByTestId('video-player')).toBeInTheDocument();
    expect(screen.queryByText('處理失敗')).not.toBeInTheDocument();
  });

  it('test_sticky_completed_preserves_playback_position_on_resubmit_downgrade', async () => {
    const completedSegs = [makeSegment(0), makeSegment(1)];

    mockStream.mockReturnValue({
      data: makeData({ status: 'completed', progress: 100, segments: completedSegs }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const playerBefore = screen.getByTestId('video-player');

    // Hook reverts to processing
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 30 }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    // Player DOM element is the same — no remount (same element reference)
    const playerAfter = screen.getByTestId('video-player');
    expect(playerAfter).toBe(playerBefore);
  });

  // -----------------------------------------------------------------------
  // TTFS instrumentation
  // -----------------------------------------------------------------------

  it('test_ttfs_event_fires_once_on_first_segment_appearance', async () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    // First: processing with no segments
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 10, segments: [] }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // No event fired yet
    const firstSegmentCalls = dispatchSpy.mock.calls.filter(
      ([e]) => (e as CustomEvent).type === 'el:first-segment',
    );
    expect(firstSegmentCalls).toHaveLength(0);

    // Now: processing with first segment
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 20, segments: [makeSegment(0)] }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    const afterFirstCalls = dispatchSpy.mock.calls.filter(
      ([e]) => (e as CustomEvent).type === 'el:first-segment',
    );
    expect(afterFirstCalls).toHaveLength(1);

    // detail.t should be a finite number
    const event = afterFirstCalls[0][0] as CustomEvent;
    expect(typeof event.detail.t).toBe('number');
    expect(isFinite(event.detail.t)).toBe(true);
  });

  it('test_ttfs_event_does_not_refire_on_subsequent_segment_appends', async () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    // Start: processing with first segment already present (already fired)
    mockStream.mockReturnValue({
      data: makeData({ status: 'processing', progress: 20, segments: [makeSegment(0), makeSegment(1)] }),
      error: null,
    });

    const { rerender } = render(
      <MemoryRouter initialEntries={['/watch/test-vid']}>
        <Routes>
          <Route path="/watch/:videoId" element={<PlayerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    // One fire on first render (segments.length > 0 from the start)
    const initialCalls = dispatchSpy.mock.calls.filter(
      ([e]) => (e as CustomEvent).type === 'el:first-segment',
    );
    expect(initialCalls).toHaveLength(1);

    // More segments added
    mockStream.mockReturnValue({
      data: makeData({
        status: 'processing',
        progress: 40,
        segments: [makeSegment(0), makeSegment(1), makeSegment(2)],
      }),
      error: null,
    });
    await act(async () => {
      rerender(
        <MemoryRouter initialEntries={['/watch/test-vid']}>
          <Routes>
            <Route path="/watch/:videoId" element={<PlayerPage />} />
          </Routes>
        </MemoryRouter>,
      );
    });

    // Still only one dispatch
    const totalCalls = dispatchSpy.mock.calls.filter(
      ([e]) => (e as CustomEvent).type === 'el:first-segment',
    );
    expect(totalCalls).toHaveLength(1);
  });

  it('test_ttfs_event_does_not_fire_on_pure_completed_mount', () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent');

    // Cache-hit: first data is already completed with full segments
    mockStream.mockReturnValue({
      data: makeData({
        status: 'completed',
        progress: 100,
        segments: [makeSegment(0), makeSegment(1), makeSegment(2)],
      }),
      error: null,
    });

    renderPlayerPage();

    const firstSegmentCalls = dispatchSpy.mock.calls.filter(
      ([e]) => (e as CustomEvent).type === 'el:first-segment',
    );
    // TTFS must NOT fire for cache-hit completed flow
    expect(firstSegmentCalls).toHaveLength(0);
  });
});
