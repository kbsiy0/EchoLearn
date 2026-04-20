# Capability — Playback Controls (Phase 1a)

## Responsibilities
- Expose a discrete, five-step playback-speed control to the user.
- Persist the user's speed preference across sessions.
- Apply the stored preference to the player as soon as the IFrame is ready.
- Keep speed changes effective without degrading sync-precision guarantees from `sync.md`.

## Public interfaces

### Playback-rate hook

```typescript
// frontend/src/features/player/hooks/usePlaybackRate.ts

export const ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5] as const;
export type PlaybackRate = typeof ALLOWED_RATES[number];

function usePlaybackRate(
  player: YT.Player | null,
): {
  rate: PlaybackRate;
  setRate: (r: PlaybackRate) => void;
  stepUp: () => void;
  stepDown: () => void;
};
```

### Storage wrapper

```typescript
// frontend/src/lib/storage.ts
export function readString(key: string): string | null;
export function writeString(key: string, value: string): void;
export function readValidated<T>(
  key: string,
  parse: (raw: string) => T | null,  // null when invalid
  fallback: T,
): T;
```

All methods wrap localStorage access in `try/catch`; errors never bubble. When localStorage is unavailable, reads return `null` / fall back, writes are no-ops.

**Silent-swallow policy for write errors (including `QuotaExceededError`).** `writeString` catches and discards any exception thrown by `localStorage.setItem`. Rationale: for playback rate specifically, the cost of a non-persisting value is one re-click the next session — acceptable for a low-value preference. Other features storing higher-value state (progress, favorites, etc.) should reconsider this policy rather than copy it.

**Parser contract (read path).** `usePlaybackRate` parses the stored string with `parseFloat(raw)` and then checks membership in `ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5]`. Non-matches — including `NaN`, `Infinity`, hand-edited values like `"2.0"`, `"0.6"`, `"banana"`, `""` — fall back to `1`. There is no error surface; fallback is silent.

**SSR assumption.** This storage wrapper assumes browser context. EchoLearn is a Vite SPA with no server-side rendering, so `typeof window` guards are not required. If a future phase introduces SSR, the wrapper must be revisited.

### Keyboard shortcuts extension

Added to `KeyboardShortcutsOptions` (see `openspec/archive/phase0-refactor/specs/sync.md` for the Phase 0 contract):

```typescript
onToggleLoop?: () => void;   // L / l
onSpeedDown?:  () => void;   // [
onSpeedUp?:    () => void;   // ]
```

The three callbacks are optional; omitted callbacks leave the corresponding key as a no-op. Event-target suppression (`input` / `textarea` / `contentEditable`) applies, matching Phase 0.

## Invariants

- **Allowed rates are exactly `[0.5, 0.75, 1, 1.25, 1.5]`.** A subset of YouTube's `getAvailablePlaybackRates()`. `setRate` called with any other value is a defensive no-op.
- **Clamping, not wrapping.** `stepUp` at `1.5` → `1.5`; `stepDown` at `0.5` → `0.5`. No wraparound.
- **Persistence key is `echolearn.playback_rate`.** Written synchronously on every `setRate` / `stepUp` / `stepDown`. No debounce.
- **Invalid stored value falls back to `1`.** Any string that does not parse to one of the five allowed rates is treated as "no preference" and the default rate `1` is used. No error surface.
- **Rate survives IFrame readiness.** If the user-stored / user-set rate exists before `player` becomes non-null, the hook applies it exactly once when `player` transitions from `null` to non-null. No manual re-set required.
- **Speed change is immediate.** The call to `player.setPlaybackRate(rate)` happens on the same tick the user triggers the change (button click or keypress). No deferred animation, no retry loop.
- **Speed does not contaminate sync precision.** After `setRate(r)` and ≥ 1 second of playback, sentence-level p95 ≤ 100ms and word-level p95 ≤ 150ms still hold (the Phase 0 bar). The sync engine reads `player.getCurrentTime()` regardless of rate; no additional logic is needed.

## Observable acceptance (ui-verifier, T07)

- **localStorage round-trip.** Change rate via the button group → reload page → button group active state and `player.getPlaybackRate()` both reflect the stored value.
- **Invalid persisted value.** Manually setting `localStorage['echolearn.playback_rate'] = '2'` and reloading results in `rate === 1`, button group "1×" active, no console error.
- **Speed-change precision.** After `setRate(0.75)` and ≥ 1s of playback, sentence p95 ≤ 100ms and word p95 ≤ 150ms over ≥ 20 IFrame transitions. Measured with `?measure=1` (auto-pause off) per Phase 0 methodology.
- **Clamp behavior.** At `0.5`, `[` keypresses do not move; at `1.5`, `]` keypresses do not move. Button group active state stays on the endpoint.
- **Keyboard shortcut.** `[` in the default body context fires `onSpeedDown`; `[` while focused in an input does nothing.

## Non-goals (Phase 1a)

- Custom / arbitrary rate input (the five fixed steps are the whole UX).
- Per-video default rate (persistence is global).
- Speed ramp / easing animation between steps (rate changes are instantaneous by design).
- Tying speed into loop semantics (loop preserves rate; rate changes do not re-enter the segment).
