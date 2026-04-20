# Capability Delta — Subtitle Sync (Phase 1a)

This file is a **delta** to `openspec/archive/phase0-refactor/specs/sync.md`. It adds loop behavior to the sync layer and narrows the meaning of `?measure=1`. Everything in the Phase 0 sync spec that is not contradicted here continues to hold.

## What changes

### New responsibility
- Optionally **loop** the current segment — when enabled, seek to `segment.start` at the end-of-segment boundary instead of pausing or continuing.

### New invariants

- **Loop and auto-pause are mutually exclusive at any moment.** At most one of `{auto-pause enabled, loop enabled}` is true for the current segment. The composition layer guarantees this.
- **Loop seek fires at most once per segment cycle, guard held across IFrame postMessage transient.** `seekTo` goes out via postMessage; `getCurrentTime()` keeps reporting the old end-of-segment time for ~190ms (~11 RAF ticks at 60fps). The fire-guard therefore uses a **watermark rule**, not an "immediate reset" rule: once the seek fires, the guard stays engaged until `t` is observed below the midpoint watermark `(segment.start + segment.end) / 2`; only then does the guard re-arm. Consequence: within a single segment cycle the seek call happens exactly once regardless of how many RAF ticks elapse before the IFrame's time readout catches up. The guard also resets unconditionally when `currentIndex` changes.
- **Loop toggle does not seek, pause, or re-enter the current segment.** Pressing the loop toggle mid-playback only affects behavior at the next end-of-segment boundary.
- **Loop toggle is orthogonal to `currentIndex`.** The `loop` bit and the current segment are independent pieces of state. Changing the current segment via ←/→, manual timeline seek, or natural playback progression does not flip the `loop` bit. The toggle persists until the user explicitly presses `L` again or the page reloads (loop state does not persist across reloads — see Non-goals).
- **Degenerate segments are no-ops for loop.** If `segment.end - segment.start <= 2 * AUTO_PAUSE_EPSILON`, `useLoopSegment` returns without firing or touching the guard on that tick. Whisper occasionally produces 0-duration or negative-duration segments; without this short-circuit, the loop would re-trigger before the watermark guard could re-arm, producing an infinite seek storm. The `2 * epsilon` threshold is the minimum playable room required (one epsilon before the trigger band, one after the seek lands).

### New public interface

```typescript
// frontend/src/features/player/hooks/useLoopSegment.ts
function useLoopSegment(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,
): void;
```

Behavior:
- On each `requestAnimationFrame` tick while `enabled && player && segments.length > 0 && currentIndex >= 0`:
  - If `segments[currentIndex].end - segments[currentIndex].start <= 2 * AUTO_PAUSE_EPSILON` (degenerate), return without side effects (no seek, no guard write).
  - Otherwise, if `player.getCurrentTime() >= segments[currentIndex].end - AUTO_PAUSE_EPSILON` and `lastFiredIndexRef.current !== currentIndex`, call `player.seekTo(segments[currentIndex].start, true)` and set `lastFiredIndexRef.current = currentIndex`.
  - On any tick where `lastFiredIndexRef.current === currentIndex` and `t < (segments[currentIndex].start + segments[currentIndex].end) / 2`, reset `lastFiredIndexRef.current = -1` (watermark guard-release; tolerates the IFrame postMessage transient).
- During the ~190ms transient between `seekTo(start)` and the IFrame's acknowledgement, `getCurrentTime()` may still report the old end-of-segment time. This is the same IFrame postMessage physics Phase 0 excludes from sync-precision measurement. Speed change during this window is accepted as-is — the DoD's 1-second grace window before the speed-change precision gate covers it.
- `enabled=false` → pure no-op (no RAF, no side effects).
- Shares `AUTO_PAUSE_EPSILON = 0.08` with `useAutoPause` via `frontend/src/features/player/lib/constants.ts`.
- Does not call `pauseVideo` under any condition.

### Modified public interface

`useAutoPause`'s `enabled` parameter becomes load-bearing: Phase 0 documented it but it was also used only for `?measure=1`. Phase 1a uses it to express the auto-pause / loop mutual exclusion. No signature change from Phase 0; only semantics.

### Measurement-mode semantics update

`/watch/:videoId?measure=1` now disables BOTH auto-pause AND loop for the session:
- Auto-pause OFF (Phase 0, unchanged).
- Loop OFF (new; forced regardless of toggle state).
- Playback-rate control still active.

Rationale: `?measure=1` exists to give the ui-verifier continuous playback for sync-precision measurement. Loop would teleport time across segment boundaries and corrupt the transition counter. The loop toggle itself is not reset — it is just ignored by `useLoopSegment` via `enabled=false` that the composition layer computes. Precision numbers (sentence p95 ≤ 100ms, word p95 ≤ 150ms) remain the algorithm property they were in Phase 0.

## Observable acceptance (ui-verifier, T07)

- With loop ON (no `?measure=1`): seek-to-start fires at `t >= end - AUTO_PAUSE_EPSILON`, no pause issued, at most once per segment cycle (regardless of how many RAF ticks elapse during the ~190ms IFrame postMessage transient). Seek→resume latency p95 ≤ 200ms over ≥ 20 end-of-segment cycles, measured via Playwright scripted timing (no new URL flag).
- With `?measure=1` AND loop toggle ON: `seekTo` is never called at a segment boundary over ≥ 20 transitions. Auto-pause is also not called (Phase 0 guarantee retained).
- With loop OFF: auto-pause behavior is bit-for-bit identical to Phase 0 — fires once per segment at `end ± 0.08s`.

## Non-goals (Phase 1a)

- A/B range loop, N-times repeat, variable loop counts.
- Persistence of loop toggle across sessions (page load always starts with loop OFF).
- Cross-segment look-ahead (loop only covers the current segment).
