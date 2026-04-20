import { useEffect } from 'react';

export interface KeyboardShortcutsOptions {
  onTogglePlay: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRepeat: () => void;
}

/**
 * Binds keyboard shortcuts for the player.
 *
 * Space  → onTogglePlay
 * ←      → onPrev
 * →      → onNext
 * r / R  → onRepeat
 *
 * Shortcuts are ignored when the event target is an input, textarea,
 * or contentEditable element (to avoid conflicts while typing).
 * Listener is cleaned up on unmount.
 */
export function useKeyboardShortcuts({
  onTogglePlay,
  onPrev,
  onNext,
  onRepeat,
}: KeyboardShortcutsOptions): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable
      ) {
        return;
      }

      switch (e.key) {
        case ' ':
          e.preventDefault();
          onTogglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          onPrev();
          break;
        case 'ArrowRight':
          e.preventDefault();
          onNext();
          break;
        case 'r':
        case 'R':
          e.preventDefault();
          onRepeat();
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onTogglePlay, onPrev, onNext, onRepeat]);
}
