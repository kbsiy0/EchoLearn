/**
 * Tests for useKeyboardShortcuts — Space, ←, →, R bindings.
 *
 * Strategy: render the hook, fire synthetic KeyboardEvent on window,
 * assert the corresponding callback was called. Verify input/textarea
 * focus suppresses shortcuts.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useKeyboardShortcuts } from './useKeyboardShortcuts';

function fireKey(key: string, target: EventTarget = window): void {
  const event = new KeyboardEvent('keydown', { key, bubbles: true });
  Object.defineProperty(event, 'target', { value: target, configurable: true });
  window.dispatchEvent(event);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useKeyboardShortcuts', () => {
  it('Space calls onTogglePlay', () => {
    const onTogglePlay = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay, onPrev: vi.fn(), onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    fireKey(' ');
    expect(onTogglePlay).toHaveBeenCalledTimes(1);
  });

  it('ArrowLeft calls onPrev', () => {
    const onPrev = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay: vi.fn(), onPrev, onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    fireKey('ArrowLeft');
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it('ArrowRight calls onNext', () => {
    const onNext = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay: vi.fn(), onPrev: vi.fn(), onNext, onRepeat: vi.fn() }),
    );
    fireKey('ArrowRight');
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it('r calls onRepeat', () => {
    const onRepeat = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay: vi.fn(), onPrev: vi.fn(), onNext: vi.fn(), onRepeat }),
    );
    fireKey('r');
    expect(onRepeat).toHaveBeenCalledTimes(1);
  });

  it('R (uppercase) calls onRepeat', () => {
    const onRepeat = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay: vi.fn(), onPrev: vi.fn(), onNext: vi.fn(), onRepeat }),
    );
    fireKey('R');
    expect(onRepeat).toHaveBeenCalledTimes(1);
  });

  it('ignores Space when target is an input element', () => {
    const onTogglePlay = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay, onPrev: vi.fn(), onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    const input = document.createElement('input');
    fireKey(' ', input);
    expect(onTogglePlay).not.toHaveBeenCalled();
  });

  it('ignores ArrowLeft when target is a textarea element', () => {
    const onPrev = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay: vi.fn(), onPrev, onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    const textarea = document.createElement('textarea');
    fireKey('ArrowLeft', textarea);
    expect(onPrev).not.toHaveBeenCalled();
  });

  it('removes listener on unmount', () => {
    const onTogglePlay = vi.fn();
    const { unmount } = renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay, onPrev: vi.fn(), onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    unmount();
    fireKey(' ');
    expect(onTogglePlay).not.toHaveBeenCalled();
  });

  it('ignores unrecognised keys', () => {
    const onTogglePlay = vi.fn();
    const onPrev = vi.fn();
    renderHook(() =>
      useKeyboardShortcuts({ onTogglePlay, onPrev, onNext: vi.fn(), onRepeat: vi.fn() }),
    );
    fireKey('a');
    expect(onTogglePlay).not.toHaveBeenCalled();
    expect(onPrev).not.toHaveBeenCalled();
  });
});
