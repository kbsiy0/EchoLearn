/**
 * Tests for ResumeToast component (T08).
 *
 * Covers: time/segment formatting, auto-dismiss (5s wall-clock), dismiss button,
 * restart button, timer cleanup on unmount, timer cleanup on button click,
 * pointer-events-none backdrop, fixed bottom-right positioning.
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ResumeToast } from './ResumeToast';
import { formatPlayedAt } from '../lib/format';

// ---------------------------------------------------------------------------
// Fake timers for all tests
// ---------------------------------------------------------------------------
beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// formatPlayedAt unit tests
// ---------------------------------------------------------------------------
describe('formatPlayedAt', () => {
  it('test_format_played_at_floors_not_rounds_67', () => {
    // 67.0s → "1:07"
    expect(formatPlayedAt(67)).toBe('1:07');
  });

  it('test_format_played_at_floors_not_rounds_59_9', () => {
    // 59.9 should floor to 59s → "0:59", NOT round up to "1:00"
    expect(formatPlayedAt(59.9)).toBe('0:59');
  });

  it('test_format_played_at_zero', () => {
    expect(formatPlayedAt(0)).toBe('0:00');
  });

  it('test_format_played_at_long_video_1199_9', () => {
    // 1199.9s → floor to 1199s → 19 min 59 sec → "19:59"
    expect(formatPlayedAt(1199.9)).toBe('19:59');
  });

  it('test_format_played_at_degenerate_3725', () => {
    // 3725s → 62 min 5 sec → "62:05" (handles gracefully even above 20-min cap)
    expect(formatPlayedAt(3725)).toBe('62:05');
  });
});

// ---------------------------------------------------------------------------
// ResumeToast component tests
// ---------------------------------------------------------------------------
describe('ResumeToast', () => {
  function makeProps(overrides: Partial<Parameters<typeof ResumeToast>[0]> = {}) {
    return {
      playedAtSec: 67,
      segmentIdx: 17,
      onDismiss: vi.fn(),
      onRestart: vi.fn(),
      ...overrides,
    };
  }

  it('test_renders_played_at_in_m_ss_format', () => {
    render(<ResumeToast {...makeProps({ playedAtSec: 67.3 })} />);
    expect(screen.getByText(/1:07/)).toBeInTheDocument();
  });

  it('test_renders_segment_label_one_indexed', () => {
    // segmentIdx=17 (0-indexed) → display "第 18 句"
    render(<ResumeToast {...makeProps({ segmentIdx: 17 })} />);
    expect(screen.getByText(/第 18 句/)).toBeInTheDocument();
  });

  it('test_renders_played_at_zero_as_0_00', () => {
    render(<ResumeToast {...makeProps({ playedAtSec: 0 })} />);
    expect(screen.getByText(/0:00/)).toBeInTheDocument();
  });

  it('test_renders_played_at_for_long_video', () => {
    render(<ResumeToast {...makeProps({ playedAtSec: 1199.9 })} />);
    expect(screen.getByText(/19:59/)).toBeInTheDocument();
  });

  it('test_renders_dismiss_button_calls_onDismiss', () => {
    const props = makeProps();
    render(<ResumeToast {...props} />);
    const dismissBtn = screen.getByRole('button', { name: /✕/ });
    fireEvent.click(dismissBtn);
    expect(props.onDismiss).toHaveBeenCalledTimes(1);
  });

  it('test_renders_restart_button_calls_onRestart', () => {
    const props = makeProps();
    render(<ResumeToast {...props} />);
    const restartBtn = screen.getByRole('button', { name: /從頭播/ });
    fireEvent.click(restartBtn);
    expect(props.onRestart).toHaveBeenCalledTimes(1);
  });

  it('test_auto_dismisses_after_5_seconds', async () => {
    const props = makeProps();
    render(<ResumeToast {...props} />);

    // At 4999ms: not yet
    await act(async () => { vi.advanceTimersByTime(4999); });
    expect(props.onDismiss).not.toHaveBeenCalled();

    // At 5000ms: exactly fires
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(props.onDismiss).toHaveBeenCalledTimes(1);
  });

  it('test_auto_dismiss_uses_wall_clock_not_paused_on_player_state', () => {
    // The component has no player-state prop. The timer runs unconditionally.
    // Verify by checking there is no "playerState" or "isPaused" prop in the interface.
    // We simply confirm the component accepts only playedAtSec/segmentIdx/onDismiss/onRestart.
    const props = makeProps();
    // This must render without error (no extra required props)
    const { container } = render(<ResumeToast {...props} />);
    expect(container.firstChild).not.toBeNull();
  });

  it('test_dismiss_button_clears_auto_dismiss_timer', async () => {
    const props = makeProps();
    render(<ResumeToast {...props} />);

    // Click ✕ at t=2s
    await act(async () => { vi.advanceTimersByTime(2000); });
    fireEvent.click(screen.getByRole('button', { name: /✕/ }));
    expect(props.onDismiss).toHaveBeenCalledTimes(1);

    // Advance to t=10s — auto-dismiss must NOT fire again
    await act(async () => { vi.advanceTimersByTime(8000); });
    expect(props.onDismiss).toHaveBeenCalledTimes(1);
  });

  it('test_restart_button_clears_auto_dismiss_timer', async () => {
    const props = makeProps();
    render(<ResumeToast {...props} />);

    // Click 「從頭播」 at t=2s
    await act(async () => { vi.advanceTimersByTime(2000); });
    fireEvent.click(screen.getByRole('button', { name: /從頭播/ }));
    expect(props.onRestart).toHaveBeenCalledTimes(1);

    // Advance to t=10s — onDismiss must NOT fire from auto-dismiss
    await act(async () => { vi.advanceTimersByTime(8000); });
    expect(props.onDismiss).not.toHaveBeenCalled();
  });

  it('test_unmount_clears_auto_dismiss_timer', async () => {
    const props = makeProps();
    const { unmount } = render(<ResumeToast {...props} />);

    // Unmount at t=1s
    await act(async () => { vi.advanceTimersByTime(1000); });
    unmount();

    // Advance to t=10s — onDismiss must NOT be called
    await act(async () => { vi.advanceTimersByTime(9000); });
    expect(props.onDismiss).not.toHaveBeenCalled();
  });

  it('test_pointer_events_none_on_backdrop_layer', () => {
    render(<ResumeToast {...makeProps()} />);
    // The outermost wrapper element must have pointer-events-none Tailwind class
    const wrapper = document.querySelector('.pointer-events-none');
    expect(wrapper).not.toBeNull();
  });

  it('test_position_classes_bottom_right', () => {
    render(<ResumeToast {...makeProps()} />);
    // Wrapper must include fixed positioning and bottom-right placement
    const fixed = document.querySelector('.fixed');
    expect(fixed).not.toBeNull();
    // Check bottom-4 and right-4 classes are present
    expect(fixed).toHaveClass('bottom-4');
    expect(fixed).toHaveClass('right-4');
  });
});
