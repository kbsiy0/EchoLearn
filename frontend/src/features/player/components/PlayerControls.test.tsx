/**
 * Thin render tests for PlayerControls speed button group.
 *
 * Asserts ARIA attributes, active state, and click handler for the five-button
 * speed selector added in T05. Does NOT duplicate hook-level tests.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ALLOWED_RATES } from '../hooks/usePlaybackRate';
import type { PlaybackRate } from '../hooks/usePlaybackRate';
import { PlayerControls } from './PlayerControls';

const defaultProps = {
  onPrev: vi.fn(),
  onNext: vi.fn(),
  onRepeat: vi.fn(),
  onTogglePlay: vi.fn(),
  onToggleLoop: vi.fn(),
  isPlaying: false,
  loop: false,
  currentIndex: 0,
  totalSegments: 5,
  rate: 1 as PlaybackRate,
  onSetRate: vi.fn(),
};

describe('PlayerControls speed button group', () => {
  it('renders all five speed buttons', () => {
    render(<PlayerControls {...defaultProps} />);
    for (const r of ALLOWED_RATES) {
      expect(screen.getByLabelText(`播放速度 ${r}×`)).toBeInTheDocument();
    }
  });

  it('marks the active rate button with aria-pressed=true', () => {
    render(<PlayerControls {...defaultProps} rate={0.75 as PlaybackRate} />);
    const active = screen.getByLabelText('播放速度 0.75×');
    expect(active).toHaveAttribute('aria-pressed', 'true');
    // all others should be false
    for (const r of ALLOWED_RATES.filter((x) => x !== 0.75)) {
      expect(screen.getByLabelText(`播放速度 ${r}×`)).toHaveAttribute('aria-pressed', 'false');
    }
  });

  it('calls onSetRate with the correct rate when a button is clicked', () => {
    const onSetRate = vi.fn();
    render(<PlayerControls {...defaultProps} onSetRate={onSetRate} />);
    fireEvent.click(screen.getByLabelText('播放速度 1.25×'));
    expect(onSetRate).toHaveBeenCalledOnce();
    expect(onSetRate).toHaveBeenCalledWith(1.25);
  });
});
