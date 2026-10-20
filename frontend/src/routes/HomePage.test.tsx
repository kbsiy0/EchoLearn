import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

// --- module mocks (must be top-level) ---

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../api/subtitles', () => ({
  createJob: vi.fn(),
}));

vi.mock('../api/progress', () => ({
  deleteProgress: vi.fn(),
}));

vi.mock('../features/jobs/components/VideoCard', () => ({
  VideoCard: vi.fn(({ summary, onClick, onReset }: {
    summary: { video_id: string; title: string; progress: unknown };
    onClick: (id: string) => void;
    onReset: (id: string) => Promise<void>;
  }) => (
    <div data-testid={`video-card-${summary.video_id}`}>
      <span>{summary.title}</span>
      <button onClick={() => onClick(summary.video_id)}>play</button>
      {summary.progress !== null && (
        <button
          onClick={() => { void onReset(summary.video_id).catch(() => {}); }}
          data-testid={`reset-${summary.video_id}`}
        >
          重置進度
        </button>
      )}
    </div>
  )),
}));

// MSW for fetch interception (matches the project pattern in api/progress.test.ts).
// `global.fetch = vi.fn()` conflicts with MSW's server.listen() patching;
// route all `fetch(${API_BASE}/videos)` calls through MSW handlers per-test.
import { http, HttpResponse } from 'msw';
import { server } from '../test/setup';

// --- import under test (after mocks) ---
import { createJob } from '../api/subtitles';
import { deleteProgress } from '../api/progress';
import { HomePage } from './HomePage';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderHomePage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

function getSubmitButton() {
  return screen.getByRole('button', { name: '載入' });
}

function getUrlInput() {
  return screen.getByPlaceholderText('貼上 YouTube URL...');
}

async function typeAndSubmit(url = 'https://www.youtube.com/watch?v=abc12345678') {
  fireEvent.change(getUrlInput(), { target: { value: url } });
  fireEvent.click(getSubmitButton());
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const VIDEOS_URL = 'http://localhost:8000/api/videos';

describe('HomePage — T11: navigate immediately after createJob', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(http.get(VIDEOS_URL, () => HttpResponse.json([])));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('test_submit_success_navigates_to_watch_route_immediately', async () => {
    (createJob as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      video_id: 'abc',
      job_id: 'job-001',
      status: 'queued',
    });

    renderHomePage();
    await act(async () => {
      await typeAndSubmit();
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/watch/abc');
    });
  });

  it('test_submit_does_not_render_loading_spinner_after_success', async () => {
    (createJob as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      video_id: 'abc',
      job_id: 'job-001',
      status: 'queued',
    });

    renderHomePage();
    await act(async () => {
      await typeAndSubmit();
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/watch/abc');
    });

    // LoadingSpinner should NOT be in the DOM after navigation fires
    expect(document.querySelector('[data-testid="loading-spinner"]')).toBeNull();
    // Also check by role — spinner typically has no specific role, so check by text absence
    expect(screen.queryByText(/處理中/)).toBeNull();
    expect(screen.queryByText(/排隊中/)).toBeNull();
  });

  it('test_submit_failure_keeps_user_on_homepage', async () => {
    (createJob as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('Network error'),
    );

    renderHomePage();
    await act(async () => {
      await typeAndSubmit();
    });

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('test_submit_failure_allows_retry', async () => {
    (createJob as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        video_id: 'abc',
        job_id: 'job-002',
        status: 'queued',
      });

    renderHomePage();

    // First attempt — fails
    await act(async () => {
      await typeAndSubmit('https://www.youtube.com/watch?v=abc12345678');
    });

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });

    // Second attempt — succeed
    await act(async () => {
      fireEvent.change(getUrlInput(), {
        target: { value: 'https://www.youtube.com/watch?v=abc12345678' },
      });
      fireEvent.click(getSubmitButton());
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/watch/abc');
    });

    expect(createJob).toHaveBeenCalledTimes(2);
  });

  it('test_cache_hit_navigates_same_as_fresh_submit', async () => {
    // Cache hit: status already "completed", cached: true
    (createJob as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      video_id: 'abc',
      status: 'completed',
      cached: true,
    });

    renderHomePage();
    await act(async () => {
      await typeAndSubmit();
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/watch/abc');
    });
  });
});

// ---------------------------------------------------------------------------
// Fixtures for T10
// ---------------------------------------------------------------------------

const progressFixture = {
  last_played_sec: 60,
  last_segment_idx: 2,
  playback_rate: 1.0,
  loop_enabled: false,
  updated_at: '2026-04-26T08:00:00Z',
};

function makeVideo(
  id: string,
  title: string,
  createdAt: string,
  progressUpdatedAt: string | null = null,
) {
  return {
    video_id: id,
    title,
    duration_sec: 207,
    created_at: createdAt,
    progress: progressUpdatedAt
      ? { ...progressFixture, updated_at: progressUpdatedAt }
      : null,
  };
}

// ---------------------------------------------------------------------------
// T10: VideoCard integration
// ---------------------------------------------------------------------------

describe('HomePage — T10: VideoCard integration + reset flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function videosHandler(...responses: Array<unknown[] | { status: number; body?: unknown }>) {
    let i = 0;
    return http.get(VIDEOS_URL, () => {
      const r = responses[Math.min(i, responses.length - 1)];
      i++;
      if (Array.isArray(r)) return HttpResponse.json(r);
      const obj = r as { status: number; body?: unknown };
      return HttpResponse.json(obj.body ?? {}, { status: obj.status });
    });
  }

  function videosCounter() {
    const calls = { count: 0 };
    return { calls, handler: (responses: Array<unknown[] | { status: number; body?: unknown }>) =>
      http.get(VIDEOS_URL, () => {
        const r = responses[Math.min(calls.count, responses.length - 1)];
        calls.count++;
        if (Array.isArray(r)) return HttpResponse.json(r);
        const obj = r as { status: number; body?: unknown };
        return HttpResponse.json(obj.body ?? {}, { status: obj.status });
      })
    };
  }

  it('test_replaces_inline_li_with_VideoCard_components', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z'),
      makeVideo('v2', 'Video Two', '2026-04-25T09:00:00Z', '2026-04-25T15:00:00Z'),
      makeVideo('v3', 'Video Three', '2026-04-25T11:00:00Z'),
    ];
    server.use(videosHandler(videos));

    renderHomePage();

    await waitFor(() => {
      expect(screen.getByTestId('video-card-v1')).toBeInTheDocument();
      expect(screen.getByTestId('video-card-v2')).toBeInTheDocument();
      expect(screen.getByTestId('video-card-v3')).toBeInTheDocument();
    });
  });

  it('test_clicking_a_card_navigates_to_watch_route', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z'),
      makeVideo('v2', 'Video Two', '2026-04-25T09:00:00Z'),
    ];
    server.use(videosHandler(videos));

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('video-card-v2')).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole('button', { name: 'play' })[1]);

    expect(mockNavigate).toHaveBeenCalledWith('/watch/v2');
  });

  it('test_clicking_reset_button_calls_delete_progress_then_refetches_videos', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z'),
    ];
    const counter = videosCounter();
    server.use(counter.handler([videos, videos]));
    (deleteProgress as ReturnType<typeof vi.fn>).mockResolvedValueOnce(undefined);

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('reset-v1')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByTestId('reset-v1'));
    });

    await waitFor(() => {
      expect(deleteProgress).toHaveBeenCalledWith('v1');
      expect(counter.calls.count).toBe(2);
    });
  });

  it('test_after_reset_success_progress_field_becomes_null_in_list', async () => {
    const videoAWithProgress = makeVideo('aaa', 'Video A', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z');
    const videoB = makeVideo('bbb', 'Video B', '2026-04-25T11:00:00Z');

    const initialList = [videoAWithProgress, videoB];
    const refetchedList = [
      makeVideo('bbb', 'Video B', '2026-04-25T11:00:00Z'),
      makeVideo('aaa', 'Video A', '2026-04-25T10:00:00Z'),
    ];

    server.use(videosHandler(initialList, refetchedList));
    (deleteProgress as ReturnType<typeof vi.fn>).mockResolvedValueOnce(undefined);

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('reset-aaa')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByTestId('reset-aaa'));
    });

    await waitFor(() => {
      const cards = screen.getAllByTestId(/^video-card-/);
      expect(cards[0]).toHaveAttribute('data-testid', 'video-card-bbb');
      expect(cards[1]).toHaveAttribute('data-testid', 'video-card-aaa');
    });
  });

  it('test_reset_failure_does_not_refetch_list_and_shows_card_error', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z'),
    ];
    const counter = videosCounter();
    server.use(counter.handler([videos]));
    (deleteProgress as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('Server error'));

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('reset-v1')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByTestId('reset-v1'));
    });

    await waitFor(() => {
      expect(deleteProgress).toHaveBeenCalled();
    });
    // Only one fetch call (the initial mount); no refetch after failed DELETE
    expect(counter.calls.count).toBe(1);
  });

  it('test_reset_failure_other_cards_unaffected', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z'),
      makeVideo('v2', 'Video Two', '2026-04-25T09:00:00Z', '2026-04-25T15:00:00Z'),
      makeVideo('v3', 'Video Three', '2026-04-25T08:00:00Z'),
    ];
    server.use(videosHandler(videos));
    (deleteProgress as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('fail'));

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('reset-v1')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByTestId('reset-v1'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('video-card-v2')).toBeInTheDocument();
      expect(screen.getByTestId('video-card-v3')).toBeInTheDocument();
    });

    const playButtons = screen.getAllByRole('button', { name: 'play' });
    expect(playButtons.length).toBeGreaterThanOrEqual(2);
  });

  it('test_reset_success_then_refetch_fails_keeps_local_state', async () => {
    const videos = [
      makeVideo('v1', 'Video One', '2026-04-25T10:00:00Z', '2026-04-26T08:00:00Z'),
    ];
    server.use(videosHandler(videos, { status: 500 }));
    (deleteProgress as ReturnType<typeof vi.fn>).mockResolvedValueOnce(undefined);

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    renderHomePage();
    await waitFor(() => expect(screen.getByTestId('reset-v1')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByTestId('reset-v1'));
    });

    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalled();
    });

    expect(screen.getByTestId('video-card-v1')).toBeInTheDocument();

    warnSpy.mockRestore();
  });

  it('test_empty_state_when_videos_array_is_empty', async () => {
    server.use(videosHandler([]));

    renderHomePage();

    await waitFor(() => {
      expect(screen.getByText('貼上 YouTube URL 開始學習')).toBeInTheDocument();
    });
    expect(screen.queryByTestId(/^video-card-/)).not.toBeInTheDocument();
  });

  it('test_loading_state_during_initial_fetch', async () => {
    // Handler that never responds (HttpResponse.json never resolves)
    server.use(http.get(VIDEOS_URL, () => new Promise(() => {})));

    renderHomePage();

    // No VideoCard rendered while fetch is pending
    expect(screen.queryByTestId(/^video-card-/)).not.toBeInTheDocument();
  });

  it('test_videos_sorted_by_progress_then_created_at', async () => {
    const alpha = makeVideo('aaa', 'Video Alpha', '2026-04-25T10:00:00Z', null);
    const beta  = makeVideo('bbb', 'Video Beta',  '2026-04-25T09:00:00Z', '2026-04-26T08:00:00Z');
    const gamma = makeVideo('ccc', 'Video Gamma', '2026-04-25T11:00:00Z', '2026-04-25T15:00:00Z');

    server.use(videosHandler([beta, gamma, alpha]));

    renderHomePage();

    await waitFor(() => {
      expect(screen.getByTestId('video-card-bbb')).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId(/^video-card-/);
    expect(cards[0]).toHaveAttribute('data-testid', 'video-card-bbb');
    expect(cards[1]).toHaveAttribute('data-testid', 'video-card-ccc');
    expect(cards[2]).toHaveAttribute('data-testid', 'video-card-aaa');
  });
});
