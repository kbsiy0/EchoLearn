/**
 * Tests for ProcessingPlaceholder component (T10).
 *
 * Covers: progress bar rendering, title truncation, error state,
 * progress bar hidden on error, home navigation, edge cases (0%, 100%).
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

// Mock react-router-dom's useNavigate before importing the component
const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

import { ProcessingPlaceholder } from './ProcessingPlaceholder';

describe('ProcessingPlaceholder', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
  });

  it('test_renders_progress_bar_and_percentage_text', () => {
    render(<ProcessingPlaceholder progress={32} />);
    // Progress bar element should have width 32%
    const bar = document.querySelector('[style*="width: 32%"]');
    expect(bar).not.toBeNull();
    // Label text
    expect(screen.getByText('處理字幕中 (32%)')).toBeInTheDocument();
  });

  it('test_renders_title_when_provided', () => {
    render(<ProcessingPlaceholder progress={50} title="How to build" />);
    const titleEl = screen.getByText('How to build');
    expect(titleEl).toBeInTheDocument();
    // Should have truncate class
    expect(titleEl).toHaveClass('truncate');
  });

  it('test_renders_error_state_with_button', () => {
    render(<ProcessingPlaceholder progress={0} error="Whisper transient timeout" />);
    expect(screen.getByText('處理失敗')).toBeInTheDocument();
    expect(screen.getByText('Whisper transient timeout')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '回首頁' })).toBeInTheDocument();
  });

  it('test_error_hides_progress_bar', () => {
    render(<ProcessingPlaceholder progress={50} error="some error" />);
    const bar = document.querySelector('[style*="width:"], [style*="width"]');
    expect(bar).toBeNull();
  });

  it('test_home_button_navigates_home', () => {
    render(<ProcessingPlaceholder progress={0} error="some error" />);
    const button = screen.getByRole('button', { name: '回首頁' });
    fireEvent.click(button);
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });

  it('test_progress_0_renders_a_zero_width_bar', () => {
    render(<ProcessingPlaceholder progress={0} />);
    const bar = document.querySelector('[style*="width: 0%"]');
    expect(bar).not.toBeNull();
  });

  it('test_progress_100_renders_a_full_bar', () => {
    render(<ProcessingPlaceholder progress={100} />);
    const bar = document.querySelector('[style*="width: 100%"]');
    expect(bar).not.toBeNull();
  });
});
