# Capability — Subtitle Sync

## Responsibilities
- Map the player's current wall-clock time to the currently-active sentence and word indices.
- Drive the visual highlight of the current segment and current word on every meaningful change.
- Auto-pause at the end of a segment when that behavior is enabled.
- Achieve measured p95 alignment deltas of ≤ 100ms (sentence) and ≤ 150ms (word).

## Public interfaces

### Segmenter (backend-side input to sync)
```python
# backend/app/services/alignment/segmenter.py
def segment(words: list[Word]) -> list[Segment]: ...
```

A `Segment` produced here carries `start`, `end`, and a verbatim `words` list, all on a single time base.

### Frontend sync hook
```typescript
// frontend/src/features/player/hooks/useSubtitleSync.ts
function useSubtitleSync(
  player: YT.Player | null,
  segments: Segment[],
): {
  currentIndex: number;       // -1 when no segment is active
  currentWordIndex: number;   // -1 when between words or no segment active
};
```

### Auto-pause hook
```typescript
// frontend/src/features/player/hooks/useAutoPause.ts
function useAutoPause(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,
): void;
```

### Keyboard shortcuts hook
```typescript
// frontend/src/features/player/hooks/useKeyboardShortcuts.ts

export interface KeyboardShortcutsOptions {
  onTogglePlay: () => void;  // called when Space is pressed — caller toggles play/pause
  onPrev: () => void;        // called when ← is pressed — caller jumps to previous segment
  onNext: () => void;        // called when → is pressed — caller jumps to next segment
  onRepeat: () => void;      // called when R/r is pressed — caller replays current segment
}

function useKeyboardShortcuts(options: KeyboardShortcutsOptions): void;
//   space = onTogglePlay
//   ←     = onPrev
//   →     = onNext
//   R/r   = onRepeat
//
// Action logic lives in the caller (PlayerPage). This callback-based shape
// avoids direct coupling to YT.Player internals inside the hook and makes
// the hook trivially testable with vi.fn() callbacks.
// Note: shortcuts are suppressed when the event target is an input/textarea/contentEditable.
```

## Invariants
- **Single time base.** All sync decisions derive from `player.getCurrentTime()` compared against segment/word boundaries that originated from the same Whisper word stream.
- **Sampled at display refresh rate.** Time is read on every `requestAnimationFrame` tick (~16ms), never via `setInterval`.
- **State changes only on transitions.** `setState` is called only when at least one of `currentIndex` or `currentWordIndex` actually changes. Identical-index ticks do not cause rerenders.
- **Lookup is O(log n).** Both segment-find and word-find use binary search over arrays sorted by `start`.
- **Auto-pause fires at most once per segment.** Guard by tracking the last segment index that triggered a pause.
- **Epsilon for end-of-segment.** Auto-pause trigger band is `segment.end ± 0.08s`, matching existing behavior.

## Observable acceptance (ui-verifier)
- Sentence-level alignment delta p95 ≤ 100ms over a representative 3-minute video.
- Word-level alignment delta p95 ≤ 150ms over the same video.
- No dropped highlights (every played segment gets a highlight state at some tick).
- No rerender storms: `useSubtitleSync` does not trigger a React rerender on ticks where both indices are unchanged (verified in Vitest).

## Non-goals
- Predictive scrubbing / look-ahead highlighting before a word starts.
- Word-level highlight during playback speed changes outside of 0.5×–2× (out of scope for Phase 0).
- Cross-tab sync.
