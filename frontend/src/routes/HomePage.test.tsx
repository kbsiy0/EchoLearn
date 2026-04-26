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

// Mock fetch for video history to avoid unhandled requests
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => [],
} as Response);
global.fetch = mockFetch;

// --- import under test (after mocks) ---
import { createJob } from '../api/subtitles';
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

describe('HomePage — T11: navigate immediately after createJob', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => [],
    });
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
