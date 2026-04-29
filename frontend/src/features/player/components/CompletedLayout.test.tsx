/**
 * T11 — CompletedLayout integration tests.
 *
 * Strategy:
 * - Mock all heavy hooks: useYouTubePlayer, useSubtitleSync, useAutoPause,
 *   useLoopSegment, usePlaybackRate, useKeyboardShortcuts, useVideoProgress
 * - Tests are hermetic: each test scripts the state-arrival ordering
 * - MSW is NOT needed here because useVideoProgress is fully mocked
 */

import { render, screen, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { SubtitleResponse } from '../../../types/subtitle';

// --- module mocks (must be at top level, before imports) ---

vi.mock('../hooks/useYouTubePlayer', () => ({
  useYouTubePlayer: vi.fn(),
}));

vi.mock('../hooks/useSubtitleSync', () => ({
  useSubtitleSync: vi.fn(() => ({ currentIndex: 0, currentWordIndex: -1 })),
}));

vi.mock('../hooks/useAutoPause', () => ({
  useAutoPause: vi.fn(),
}));

vi.mock('../hooks/useLoopSegment', () => ({
  useLoopSegment: vi.fn(),
}));

vi.mock('../hooks/usePlaybackRate', () => ({
  usePlaybackRate: vi.fn(),
  ALLOWED_RATES: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
}));

vi.mock('../hooks/useKeyboardShortcuts', () => ({
  useKeyboardShortcuts: vi.fn(),
}));

vi.mock('../hooks/useVideoProgress', () => ({
  useVideoProgress: vi.fn(),
}));

// Import after mocks
import { useYouTubePlayer } from '../hooks/useYouTubePlayer';
import { usePlaybackRate } from '../hooks/usePlaybackRate';
import { useVideoProgress } from '../hooks/useVideoProgress';
import { CompletedLayout } from './CompletedLayout';

// jsdom doesn't implement scrollTo — stub it so SubtitlePanel doesn't throw
Element.prototype.scrollTo = () => {};

// --- typed mocks ---
const mockUseYouTubePlayer = vi.mocked(useYouTubePlayer);
const mockUsePlaybackRate = vi.mocked(usePlaybackRate);
const mockUseVideoProgress = vi.mocked(useVideoProgress);

// --- helpers ---

function makeSegment(idx: number) {
  return {
    idx,
    start: idx * 10,
    end: idx * 10 + 9,
    text_en: `Segment ${idx} EN`,
    text_zh: `Segment ${idx} ZH`,
    words: [{ text: 'word', start: idx * 10, end: idx * 10 + 4 }],
  };
}

function makeData(overrides: Partial<SubtitleResponse> = {}): SubtitleResponse {
  return {
    video_id: 'abc123',
    title: 'Test Video',
    status: 'completed',
    progress: 100,
    error: null,
    duration_sec: 180,
    segments: [makeSegment(0), makeSegment(1), makeSegment(2)],
    ...overrides,
  };
}

const mockSeekTo = vi.fn();
const mockPlayVideo = vi.fn();
const mockPauseVideo = vi.fn();
const mockSetRate = vi.fn();
const mockStepUp = vi.fn();
const mockStepDown = vi.fn();
const mockSave = vi.fn();
const mockReset = vi.fn();

function setupDefaultMocks({
  isReady = false,
  playerState = -1,
  progressValue = null as null | object,
  progressLoaded = false,
  rate = 1.0,
  currentTime = 0,
} = {}) {
  const mockPlayer = {
    getCurrentTime: vi.fn(() => currentTime),
  };

  mockUseYouTubePlayer.mockReturnValue({
    player: mockPlayer as unknown as ReturnType<typeof useYouTubePlayer>['player'],
    isReady,
    playerState,
    seekTo: mockSeekTo,
    playVideo: mockPlayVideo,
    pauseVideo: mockPauseVideo,
  });

  mockUsePlaybackRate.mockReturnValue({
    rate,
    setRate: mockSetRate,
    stepUp: mockStepUp,
    stepDown: mockStepDown,
  });

  mockUseVideoProgress.mockReturnValue({
    value: progressValue as ReturnType<typeof useVideoProgress>['value'],
    loaded: progressLoaded,
    save: mockSave,
    reset: mockReset,
  });
}

function renderLayout(data?: SubtitleResponse, videoId = 'abc123') {
  const d = data ?? makeData();
  return render(
    <MemoryRouter>
      <CompletedLayout data={d} videoId={videoId} />
    </MemoryRouter>,
  );
}

// --- tests ---

describe('CompletedLayout — T11 integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSeekTo.mockReset();
    mockPlayVideo.mockReset();
    mockPauseVideo.mockReset();
    mockSetRate.mockReset();
    mockSave.mockReset();
    mockReset.mockReset();
  });

  // ── Hook wiring ──────────────────────────────────────────────────────────

  it('test_calls_useVideoProgress_with_videoId', () => {
    setupDefaultMocks();
    renderLayout(makeData(), 'my-video-id');
    expect(mockUseVideoProgress).toHaveBeenCalledWith('my-video-id');
  });

  // ── Resume guard: null / not-loaded / not-ready ──────────────────────────

  it('test_no_resume_when_value_is_null', () => {
    setupDefaultMocks({ isReady: true, progressLoaded: true, progressValue: null });
    renderLayout();
    expect(mockSeekTo).not.toHaveBeenCalled();
    expect(screen.queryByText(/已恢復到/)).toBeNull();
  });

  it('test_no_resume_until_loaded_true', () => {
    setupDefaultMocks({
      isReady: true,
      progressLoaded: false,
      progressValue: { last_played_sec: 67, last_segment_idx: 6, playback_rate: 1.5, loop_enabled: false },
    });
    renderLayout();
    expect(mockSeekTo).not.toHaveBeenCalled();
    expect(screen.queryByText(/已恢復到/)).toBeNull();
  });

  it('test_no_resume_until_isReady_true', () => {
    setupDefaultMocks({
      isReady: false,
      progressLoaded: true,
      progressValue: { last_played_sec: 67, last_segment_idx: 6, playback_rate: 1.5, loop_enabled: false },
    });
    renderLayout();
    expect(mockSeekTo).not.toHaveBeenCalled();
  });

  // ── Resume: normal path ───────────────────────────────────────────────────

  it('test_resume_runs_when_loaded_and_isReady', () => {
    // segments: idx 0→start=0, idx 1→start=10, idx 2→start=20; last_played_sec=67 > 20 → clamps to 180
    // use segments with start times spanning 67
    const segments = [
      makeSegment(0), // start=0
      makeSegment(1), // start=10
      makeSegment(2), // start=20
      { idx: 3, start: 60, end: 69, text_en: 'S3 EN', text_zh: 'S3 ZH', words: [] },
      { idx: 4, start: 70, end: 79, text_en: 'S4 EN', text_zh: 'S4 ZH', words: [] },
    ];
    const data = makeData({ segments, duration_sec: 180 });

    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 67, last_segment_idx: 3, playback_rate: 1.5, loop_enabled: true },
    });

    renderLayout(data);

    expect(mockSeekTo).toHaveBeenCalledWith(67);
    expect(mockSetRate).toHaveBeenCalledWith(1.5);
    expect(screen.getByText(/已恢復到/)).toBeTruthy();
  });

  it('test_resume_runs_exactly_once_via_restoredRef', async () => {
    const progressValue = { last_played_sec: 30, last_segment_idx: 0, playback_rate: 1.0, loop_enabled: false };

    // Start with isReady=false
    mockUseYouTubePlayer.mockReturnValue({
      player: { getCurrentTime: vi.fn(() => 0) } as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: false,
      playerState: -1,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });
    mockUsePlaybackRate.mockReturnValue({ rate: 1, setRate: mockSetRate, stepUp: mockStepUp, stepDown: mockStepDown });
    mockUseVideoProgress.mockReturnValue({ value: progressValue as ReturnType<typeof useVideoProgress>['value'], loaded: true, save: mockSave, reset: mockReset });

    const { rerender } = render(
      <MemoryRouter>
        <CompletedLayout data={makeData()} videoId="abc123" />
      </MemoryRouter>,
    );

    // isReady → true (resume should fire)
    mockUseYouTubePlayer.mockReturnValue({
      player: { getCurrentTime: vi.fn(() => 0) } as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: true,
      playerState: -1,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });
    await act(async () => {
      rerender(
        <MemoryRouter>
          <CompletedLayout data={makeData()} videoId="abc123" />
        </MemoryRouter>,
      );
    });

    // isReady → false → true again (simulating IFrame disconnect)
    mockUseYouTubePlayer.mockReturnValue({
      player: { getCurrentTime: vi.fn(() => 0) } as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: false,
      playerState: -1,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });
    await act(async () => {
      rerender(
        <MemoryRouter>
          <CompletedLayout data={makeData()} videoId="abc123" />
        </MemoryRouter>,
      );
    });

    mockUseYouTubePlayer.mockReturnValue({
      player: { getCurrentTime: vi.fn(() => 0) } as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: true,
      playerState: -1,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });
    await act(async () => {
      rerender(
        <MemoryRouter>
          <CompletedLayout data={makeData()} videoId="abc123" />
        </MemoryRouter>,
      );
    });

    expect(mockSeekTo).toHaveBeenCalledTimes(1);
  });

  // ── Resume: clamping ──────────────────────────────────────────────────────

  it('test_resume_clamps_last_played_sec_to_duration', () => {
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 200, last_segment_idx: 0, playback_rate: 1.0, loop_enabled: false },
    });
    renderLayout(makeData({ duration_sec: 180 }));
    expect(mockSeekTo).toHaveBeenCalledWith(180);
  });

  it('test_resume_recomputes_segment_idx_when_out_of_range', () => {
    // segments.length=5; stored idx=99 (out of range)
    // last_played_sec=25 → should find segment with start ≤ 25
    const segments = [
      { idx: 0, start: 0, end: 9, text_en: 'S0', text_zh: 'S0', words: [] },
      { idx: 1, start: 10, end: 19, text_en: 'S1', text_zh: 'S1', words: [] },
      { idx: 2, start: 20, end: 29, text_en: 'S2', text_zh: 'S2', words: [] },
      { idx: 3, start: 30, end: 39, text_en: 'S3', text_zh: 'S3', words: [] },
      { idx: 4, start: 40, end: 49, text_en: 'S4', text_zh: 'S4', words: [] },
    ];
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 25, last_segment_idx: 99, playback_rate: 1.0, loop_enabled: false },
    });
    renderLayout(makeData({ segments, duration_sec: 60 }));
    // seekTo uses last_played_sec (clamped), not segments[99].start
    expect(mockSeekTo).toHaveBeenCalledWith(25);
    // Toast should show the recomputed idx (idx=2, display "第 3 句")
    expect(screen.getByText(/第 3 句/)).toBeTruthy();
  });

  it('test_resume_clamps_playback_rate_below_0_5', () => {
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 30, last_segment_idx: 0, playback_rate: 0.1, loop_enabled: false },
    });
    renderLayout();
    expect(mockSetRate).toHaveBeenCalledWith(0.5);
  });

  it('test_resume_clamps_playback_rate_above_2_0', () => {
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 30, last_segment_idx: 0, playback_rate: 3.0, loop_enabled: false },
    });
    renderLayout();
    expect(mockSetRate).toHaveBeenCalledWith(2.0);
  });

  it('test_resume_recompute_segment_falls_back_to_zero_if_no_segment_matches', () => {
    // last_played_sec=-5 → clamps to 0 → segment idx=0 → design.md §13 says no toast at sec=0
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: -5, last_segment_idx: 0, playback_rate: 1.0, loop_enabled: false },
    });
    renderLayout();
    // seekTo(0) (clamped)
    expect(mockSeekTo).toHaveBeenCalledWith(0);
    // Toast suppressed at position 0
    expect(screen.queryByText(/已恢復到/)).toBeNull();
  });

  // ── INV-OOB: never index segments with unvalidated idx ───────────────────

  it('test_resume_does_not_index_segments_with_unvalidated_idx', () => {
    const segments = Array.from({ length: 12 }, (_, i) => makeSegment(i));
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 50, last_segment_idx: 999999, playback_rate: 1.0, loop_enabled: false },
    });
    // Should NOT throw; seekTo must use clamped last_played_sec
    expect(() => renderLayout(makeData({ segments, duration_sec: 200 }))).not.toThrow();
    expect(mockSeekTo).toHaveBeenCalledWith(50);
    // seekTo must NOT be called with segments[999999].start (undefined/NaN)
    expect(mockSeekTo).not.toHaveBeenCalledWith(undefined);
    expect(mockSeekTo).not.toHaveBeenCalledWith(NaN);
  });

  it('test_resume_negative_segment_idx_is_treated_as_invalid', () => {
    const segments = Array.from({ length: 5 }, (_, i) => makeSegment(i));
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 25, last_segment_idx: -1, playback_rate: 1.0, loop_enabled: false },
    });
    expect(() => renderLayout(makeData({ segments, duration_sec: 60 }))).not.toThrow();
    // seekTo uses clamped last_played_sec, not segments[-1]
    expect(mockSeekTo).toHaveBeenCalledWith(25);
  });

  // ── M6: segments grow after resume — re-fire suppressed ──────────────────

  it('test_resume_does_not_re_fire_when_segments_grow_after_resume', async () => {
    const progressValue = { last_played_sec: 30, last_segment_idx: 0, playback_rate: 1.0, loop_enabled: false };
    const initialSegments = Array.from({ length: 6 }, (_, i) => makeSegment(i));
    const grownSegments = Array.from({ length: 10 }, (_, i) => makeSegment(i));

    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue,
    });

    const { rerender } = render(
      <MemoryRouter>
        <CompletedLayout data={makeData({ segments: initialSegments, duration_sec: 180 })} videoId="abc123" />
      </MemoryRouter>,
    );

    // Resume ran once with initial segments
    expect(mockSeekTo).toHaveBeenCalledTimes(1);

    // Segments grow (Phase 1b chunk-streaming append)
    await act(async () => {
      rerender(
        <MemoryRouter>
          <CompletedLayout data={makeData({ segments: grownSegments, duration_sec: 180 })} videoId="abc123" />
        </MemoryRouter>,
      );
    });

    // seekTo still called only once (restoredRef guard)
    expect(mockSeekTo).toHaveBeenCalledTimes(1);
  });

  // ── Toast: null progress ──────────────────────────────────────────────────

  it('test_toast_does_not_show_when_progress_is_null', () => {
    setupDefaultMocks({ isReady: true, progressLoaded: true, progressValue: null });
    renderLayout();
    expect(screen.queryByText(/已恢復到/)).toBeNull();
  });

  // ── Toast: dismiss ────────────────────────────────────────────────────────

  it('test_toast_dismiss_clears_state', async () => {
    const segments = [
      { idx: 0, start: 0, end: 9, text_en: 'S0', text_zh: 'S0', words: [] },
      { idx: 1, start: 10, end: 19, text_en: 'S1', text_zh: 'S1', words: [] },
      { idx: 2, start: 20, end: 29, text_en: 'S2', text_zh: 'S2', words: [] },
    ];
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 15, last_segment_idx: 1, playback_rate: 1.0, loop_enabled: false },
    });
    renderLayout(makeData({ segments, duration_sec: 60 }));

    expect(screen.getByText(/已恢復到/)).toBeTruthy();

    // Click dismiss (✕ button)
    await act(async () => {
      fireEvent.click(screen.getByLabelText('✕'));
    });

    expect(screen.queryByText(/已恢復到/)).toBeNull();
    // Player unaffected: seekTo not called again
    expect(mockSeekTo).toHaveBeenCalledTimes(1);
  });

  // ── Toast: restart ────────────────────────────────────────────────────────

  it('test_toast_restart_button_calls_seek_zero_and_dismisses', async () => {
    const segments = [
      { idx: 0, start: 0, end: 9, text_en: 'S0', text_zh: 'S0', words: [] },
      { idx: 1, start: 10, end: 19, text_en: 'S1', text_zh: 'S1', words: [] },
    ];
    setupDefaultMocks({
      isReady: true,
      progressLoaded: true,
      progressValue: { last_played_sec: 15, last_segment_idx: 1, playback_rate: 1.0, loop_enabled: false },
    });
    renderLayout(makeData({ segments, duration_sec: 60 }));

    const calls1 = mockSeekTo.mock.calls.length; // 1 (resume)

    await act(async () => {
      fireEvent.click(screen.getByText('從頭播'));
    });

    // seekTo(0) called
    expect(mockSeekTo).toHaveBeenCalledWith(0);
    expect(mockSeekTo.mock.calls.length).toBe(calls1 + 1);
    // Toast dismissed
    expect(screen.queryByText(/已恢復到/)).toBeNull();
  });

  // ── Save propagation ──────────────────────────────────────────────────────

  it('test_pause_event_calls_save_with_position_and_segment_idx', async () => {
    const segments = Array.from({ length: 12 }, (_, i) => makeSegment(i));
    const mockPlayer = { getCurrentTime: vi.fn(() => 42) };

    // Start with isReady=true, playerState playing (1)
    mockUseYouTubePlayer.mockReturnValue({
      player: mockPlayer as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: true,
      playerState: 1,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });
    mockUsePlaybackRate.mockReturnValue({ rate: 1, setRate: mockSetRate, stepUp: mockStepUp, stepDown: mockStepDown });
    mockUseVideoProgress.mockReturnValue({ value: null, loaded: true, save: mockSave, reset: mockReset });

    // useSubtitleSync returns currentIndex=10
    const { useSubtitleSync } = await import('../hooks/useSubtitleSync');
    vi.mocked(useSubtitleSync).mockReturnValue({ currentIndex: 10, currentWordIndex: -1 });

    const { rerender } = render(
      <MemoryRouter>
        <CompletedLayout data={makeData({ segments, duration_sec: 200 })} videoId="abc123" />
      </MemoryRouter>,
    );

    // Transition to PAUSED (playerState=2)
    mockUseYouTubePlayer.mockReturnValue({
      player: mockPlayer as unknown as ReturnType<typeof useYouTubePlayer>['player'],
      isReady: true,
      playerState: 2,
      seekTo: mockSeekTo,
      playVideo: mockPlayVideo,
      pauseVideo: mockPauseVideo,
    });

    await act(async () => {
      rerender(
        <MemoryRouter>
          <CompletedLayout data={makeData({ segments, duration_sec: 200 })} videoId="abc123" />
        </MemoryRouter>,
      );
    });

    expect(mockSave).toHaveBeenCalledWith(
      expect.objectContaining({
        last_played_sec: 42,
        last_segment_idx: 10,
      }),
    );
  });
});
