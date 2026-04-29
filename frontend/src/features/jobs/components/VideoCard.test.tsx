import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VideoCard } from './VideoCard';
import type { VideoSummary } from '../../../types/subtitle';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeSummary(overrides: Partial<VideoSummary> = {}): VideoSummary {
  return {
    video_id: 'abc123',
    title: 'Test Video Title',
    duration_sec: 207,
    created_at: '2026-04-25T12:00:00Z',
    progress: null,
    ...overrides,
  };
}

const progressFixture = {
  last_played_sec: 60,
  last_segment_idx: 2,
  playback_rate: 1.0,
  loop_enabled: false,
  updated_at: '2026-04-25T13:00:00Z',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('VideoCard', () => {
  it('test_renders_title_and_duration_when_no_progress', () => {
    const summary = makeSummary({ duration_sec: 207, progress: null });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    expect(screen.getByText('Test Video Title')).toBeInTheDocument();
    expect(screen.getByText(/3分27秒/)).toBeInTheDocument();
  });

  it('test_does_not_render_progress_bar_when_progress_null', () => {
    const summary = makeSummary({ progress: null });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    // progress bar is a div with bg-blue-500 — should not exist
    const bars = document.querySelectorAll('.bg-blue-500');
    expect(bars.length).toBe(0);
  });

  it('test_does_not_render_reset_button_when_progress_null', () => {
    const summary = makeSummary({ progress: null });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    expect(screen.queryByText('重置進度')).not.toBeInTheDocument();
  });

  it('test_renders_progress_bar_when_progress_set', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: { ...progressFixture, last_played_sec: 60 },
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    // The bar element should have style width ~33.3%
    const bar = document.querySelector('.bg-blue-500') as HTMLElement;
    expect(bar).toBeInTheDocument();
    expect(bar.style.width).toBe('33.3%');
  });

  it('test_renders_progress_percentage_label', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: { ...progressFixture, last_played_sec: 60 },
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    expect(screen.getByText(/33%/)).toBeInTheDocument();
  });

  it('test_renders_reset_button_when_progress_set', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    expect(screen.getByText('重置進度')).toBeInTheDocument();
  });

  it('test_clamps_progress_bar_when_last_played_sec_exceeds_duration', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: { ...progressFixture, last_played_sec: 300 },
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    const bar = document.querySelector('.bg-blue-500') as HTMLElement;
    // jsdom normalises "100.0%" → "100%" in style.width
    expect(bar.style.width).toMatch(/^100(\.0)?%$/);
  });

  it('test_clamps_progress_bar_when_last_played_sec_negative', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: { ...progressFixture, last_played_sec: -5 },
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    const bar = document.querySelector('.bg-blue-500') as HTMLElement;
    // jsdom normalises "0.0%" → "0%" in style.width
    expect(bar.style.width).toMatch(/^0(\.0)?%$/);
  });

  it('test_click_on_card_invokes_onClick_with_video_id', () => {
    const onClick = vi.fn();
    const summary = makeSummary({ video_id: 'abc123' });
    render(<VideoCard summary={summary} onClick={onClick} onReset={vi.fn()} />);
    const card = screen.getByRole('button', { name: /Test Video Title/ });
    fireEvent.click(card);
    expect(onClick).toHaveBeenCalledWith('abc123');
  });

  it('test_click_on_reset_button_invokes_onReset_with_video_id', async () => {
    const onReset = vi.fn().mockResolvedValue(undefined);
    const summary = makeSummary({
      video_id: 'abc123',
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={onReset} />);
    fireEvent.click(screen.getByText('重置進度'));
    expect(onReset).toHaveBeenCalledWith('abc123');
  });

  it('test_click_on_reset_button_does_NOT_invoke_onClick', () => {
    const onClick = vi.fn();
    const onReset = vi.fn().mockResolvedValue(undefined);
    const summary = makeSummary({
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={onClick} onReset={onReset} />);
    fireEvent.click(screen.getByText('重置進度'));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('test_reset_button_has_type_button', () => {
    const summary = makeSummary({
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    const btn = screen.getByText('重置進度');
    expect(btn).toHaveAttribute('type', 'button');
  });

  it('test_renders_inline_error_when_onReset_rejects', async () => {
    const onReset = vi.fn().mockRejectedValue(new Error('server error'));
    const summary = makeSummary({
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={onReset} />);
    fireEvent.click(screen.getByText('重置進度'));
    await waitFor(() =>
      expect(screen.getByText('重置失敗，請稍後再試')).toBeInTheDocument(),
    );
  });

  it('test_clears_inline_error_after_successful_retry', async () => {
    const onReset = vi.fn()
      .mockRejectedValueOnce(new Error('first fail'))
      .mockResolvedValueOnce(undefined);
    const summary = makeSummary({
      duration_sec: 180,
      progress: progressFixture,
    });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={onReset} />);

    // First click → error appears
    fireEvent.click(screen.getByText('重置進度'));
    await waitFor(() =>
      expect(screen.getByText('重置失敗，請稍後再試')).toBeInTheDocument(),
    );

    // Second click → success → error disappears
    fireEvent.click(screen.getByText('重置進度'));
    await waitFor(() =>
      expect(screen.queryByText('重置失敗，請稍後再試')).not.toBeInTheDocument(),
    );
  });

  it('test_renders_created_at_in_zh_tw_locale', () => {
    const summary = makeSummary({ created_at: '2026-04-25T12:00:00Z' });
    render(<VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />);
    const expected = new Date('2026-04-25T12:00:00Z').toLocaleDateString('zh-TW');
    expect(screen.getByText(new RegExp(expected.replace('/', '\\/')))).toBeInTheDocument();
  });

  it('test_card_uses_div_role_button_to_allow_nested_button', () => {
    const summary = makeSummary({ duration_sec: 180, progress: progressFixture });
    const { container } = render(
      <VideoCard summary={summary} onClick={vi.fn()} onReset={vi.fn()} />,
    );
    const outer = container.firstChild as HTMLElement;
    expect(outer.tagName).toBe('DIV');
    expect(outer).toHaveAttribute('role', 'button');
    expect(outer).toHaveAttribute('tabindex', '0');
  });

  it('test_outer_div_responds_to_keyboard_enter_and_space', () => {
    const onClick = vi.fn();
    const summary = makeSummary({ video_id: 'abc123' });
    render(<VideoCard summary={summary} onClick={onClick} onReset={vi.fn()} />);
    const card = screen.getByRole('button', { name: /Test Video Title/ });

    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith('abc123');

    fireEvent.keyDown(card, { key: ' ' });
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});
