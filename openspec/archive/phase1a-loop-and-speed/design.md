# Phase 1a: Loop & Speed — Design

Readers should be able to implement from this document alone.

---

## Section 1 — Architecture

```
frontend/src/
  lib/
    storage.ts                    (NEW — localStorage wrapper)
    storage.test.ts               (NEW — smoke + QuotaExceeded swallow)
  features/player/
    lib/
      constants.ts                (NEW — AUTO_PAUSE_EPSILON shared export)
      flags.ts                    (NEW — computePlaybackFlags pure helper)
      flags.test.ts               (NEW — mutual-exclusion matrix)
    hooks/
      useLoopSegment.ts           (NEW)
      useLoopSegment.test.ts      (NEW)
      usePlaybackRate.ts          (NEW)
      usePlaybackRate.test.ts     (NEW)
      useAutoPause.ts             (MODIFIED — add `enabled` prop, import epsilon from lib/constants)
      useAutoPause.test.ts        (MODIFIED — add enabled=false test case)
      useKeyboardShortcuts.ts     (MODIFIED — add L / [ / ] handlers)
      useKeyboardShortcuts.test.ts (MODIFIED — new shortcut cases)
    components/
      PlayerControls.tsx          (MODIFIED — loop button + five-step speed group)
  routes/
    PlayerPage.tsx                (MODIFIED — owns `loop` state, wires new hooks)
```

### Hook / state boundaries

| Concern | Owner | Why |
|---|---|---|
| `loop` boolean toggle | `PlayerPage` | UI button + keyboard + URL flag all toggle the same bit; single source of truth. |
| Computed `loopEnabled` / `autoPauseEnabled` flags | `PlayerPage` | Depends on `loop` + `measure`; composition belongs where both are known. |
| Loop seek execution (RAF + boundary check + `seekTo`) | `useLoopSegment` | Mirror-image of `useAutoPause`; self-contained. |
| Playback rate (current value + clamp + persist) | `usePlaybackRate` | Stateful wrapper around `player.setPlaybackRate` + storage. |
| localStorage read/write/fallback | `lib/storage.ts` | Reusable utility, keeps hook code focused. |
| Keyboard dispatch | `useKeyboardShortcuts` | Already the project-wide convention (Phase 0). |

`PlayerPage` is the only component that knows about the `?measure=1` flag; it is also the only component that composes `loop` + `measure` into the two enabled flags.

---

## Section 2 — Invariants

Six invariants govern the behavior of this change. Every test and every review should be checkable against this list.

### 1. Loop and auto-pause are mutually exclusive at any moment.
`useAutoPause` pauses at `segment.end - AUTO_PAUSE_EPSILON`. `useLoopSegment` seeks to `segment.start` at the same boundary. They share `AUTO_PAUSE_EPSILON = 0.08` exported from `frontend/src/features/player/lib/constants.ts` (NEW — tiny sibling module; both hooks import from it). The composition layer uses a pure helper `computePlaybackFlags(measure, loop)` exported from `frontend/src/features/player/lib/flags.ts` (or colocated with `constants.ts` if small enough):

```typescript
// lib/flags.ts
export function computePlaybackFlags(
  measure: boolean,
  loop: boolean,
): { autoPauseEnabled: boolean; loopEnabled: boolean } {
  return {
    autoPauseEnabled: !measure && !loop,
    loopEnabled:      !measure && loop,
  };
}
```

A Vitest test on `computePlaybackFlags` asserts that for all four combinations of `(measure, loop)`, at most one of the two flags is true.

### 2. Toggle does not reset the current segment.
Pressing `L` mid-playback only changes what happens at the **next** end-of-segment boundary. It does not seek, pause, resume, or re-enter the segment. Rationale: a mid-sentence toggle should feel like setting a switch, not like pressing rewind.

### 3. Loop seek fires at most once per segment cycle — guard held across IFrame postMessage transient.
Pattern differs from `useAutoPause.lastFiredIndexRef` because the loop spec needs a **sustained** RAF (auto-pause terminates its RAF after firing; loop cannot). The difference matters: `seekTo` goes out via postMessage, and `getCurrentTime()` keeps reporting the old end-of-segment value for ~190ms (~11 RAF ticks at 60fps). A guard that resets immediately on seek would fire `seekTo` every frame during that transient.

Concrete rule:

- `useLoopSegment` keeps a ref `lastFiredIndex: number` (init `-1`).
- On each RAF tick while `enabled && currentIndex >= 0`: if `t >= segment.end - epsilon` AND `lastFiredIndex !== currentIndex`, call `player.seekTo(segment.start, true)` and set `lastFiredIndex = currentIndex`.
- **Guard-release rule (watermark, not immediate):** the guard stays engaged until `t` is observed below the midpoint watermark `(segment.start + segment.end) / 2`. On the tick that first sees `t < watermark` while `lastFiredIndex === currentIndex`, reset `lastFiredIndex = -1`. This tolerates the ~190ms transient during which `getCurrentTime()` still reports the old end-of-segment value: additional fires are blocked until the IFrame time readout genuinely reflects the seek.
- Reset rule on segment change: when `currentIndex` changes (user jumps segment, or sync naturally re-enters a different index), reset `lastFiredIndex = -1` unconditionally.

Consequence: within a single segment cycle, `seekTo` is called exactly once per end-of-segment crossing, regardless of how many RAF ticks elapse before `getCurrentTime()` catches up.

### 4. Speed control uses exactly the five YouTube-supported steps.
Allowed rates: `[0.5, 0.75, 1, 1.25, 1.5]`, exported as a `const` tuple. `setRate(value)` clamps to the nearest allowed value if passed something else (defensive; the UI never produces an invalid value). `stepUp` / `stepDown` move the cursor in the array; clamped at both ends (no wraparound). The UI's active-button highlight binds to `rate === step`.

### 5. `echolearn.playback_rate` is the single source of persistence.
- Key: `echolearn.playback_rate` (namespaced by product prefix).
- Written synchronously on every `setRate` / `stepUp` / `stepDown`. No debounce — five legal values, write is effectively free.
- On mount, `usePlaybackRate` reads the key; if the value parses to one of the five allowed rates, initialize state with it; otherwise initialize to `1`.
- If `localStorage` is unavailable (Safari private mode, tests without jsdom storage), reads return `null` and the default `1` is used; writes are no-ops. `lib/storage.ts` encapsulates the try/catch.
- **Silent-swallow policy for write errors (including `QuotaExceededError`):** `writeString` catches and discards. The cost of a non-persisting rate is one re-click — acceptable for this low-value preference. Other features storing higher-value state should reconsider this policy rather than copy it.

### 6. `?measure=1` preserves Phase 0 semantics and extends them minimally.
- `?measure=1` → `autoPause = false` (Phase 0, unchanged).
- `?measure=1` → `loop = false` (new; forced regardless of user toggle state — the toggle itself is not reset, it is just ignored by `useLoopSegment` via `enabled=false`).
- `?measure=1` has no effect on speed (user can still change rate; stored preference still applies).
- Rationale: measurement mode exists to feed the ui-verifier continuous samples. Loop would teleport time across boundaries and corrupt the transition counter. Speed does not corrupt anything — it merely changes sample density, and ui-verifier already handles variable sample counts.

---

## Section 3 — Public interfaces

### `lib/storage.ts`

```typescript
// Thin, typed wrapper. Keeps localStorage access out of hook bodies.

export function readString(key: string): string | null;

export function writeString(key: string, value: string): void;

// Convenience: read + parse-with-fallback. Used by usePlaybackRate.
export function readValidated<T>(
  key: string,
  parse: (raw: string) => T | null,  // returns null if invalid
  fallback: T,
): T;
```

Rules:
- All methods wrapped in `try/catch`. localStorage errors never bubble.
- No namespace logic inside — callers pass the fully-qualified key (`echolearn.playback_rate`). The module is a low-level wrapper, not a schema enforcer.

### `useLoopSegment`

```typescript
// frontend/src/features/player/hooks/useLoopSegment.ts

function useLoopSegment(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,
): void;
```

- Runs a RAF loop when `enabled && player && segments.length > 0`.
- **No-ops on degenerate segments:** if `segments[currentIndex].end - segments[currentIndex].start <= 2 * AUTO_PAUSE_EPSILON`, the tick returns without firing or touching the guard. Prevents infinite seek loops on 0-duration / negative-duration / too-short Whisper output.
- On each tick (non-degenerate segment): reads `player.getCurrentTime()`; if `currentIndex >= 0` and `t >= segments[currentIndex].end - AUTO_PAUSE_EPSILON` and `lastFiredIndexRef.current !== currentIndex`, calls `player.seekTo(segments[currentIndex].start, true)` and sets `lastFiredIndexRef.current = currentIndex`.
- **Watermark guard-release:** on any tick where `lastFiredIndexRef.current === currentIndex` and `t < (segments[currentIndex].start + segments[currentIndex].end) / 2`, reset `lastFiredIndexRef.current = -1`. This holds the guard across the ~190ms IFrame postMessage transient after `seekTo` (see invariant 3).
- When `currentIndex` changes, resets `lastFiredIndexRef.current = -1`.
- On `enabled=false`, cancels the RAF and is a pure no-op.
- Cleans up RAF on unmount and on any dep change.
- Returns void; no observable state.

### `usePlaybackRate`

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

- Reads `echolearn.playback_rate` on mount via `readValidated`; initializes `rate`.
- On every `rate` change: calls `player.setPlaybackRate(rate)` (guarded by `player !== null`) AND writes `rate` to localStorage.
- `setRate(r)`: if `r` is one of `ALLOWED_RATES`, sets it; otherwise no-op (defensive).
- `stepUp` / `stepDown`: moves cursor in `ALLOWED_RATES`, clamped at boundaries.
- When `player` becomes non-null (IFrame finished loading), applies the current `rate` once so the persisted preference is honored even if the user never touches the control.

### `useAutoPause` (modified)

```typescript
// MODIFIED: add `enabled` prop.
function useAutoPause(
  player: YT.Player | null,
  segments: Segment[],
  currentIndex: number,
  enabled: boolean,   // NEW
): void;
```

Matches the signature already documented in `openspec/archive/phase0-refactor/specs/sync.md`. When `enabled=false`, the hook is a no-op (no RAF, no pause). All existing tests continue to pass with `enabled=true` threaded through.

### `useKeyboardShortcuts` (extended)

```typescript
export interface KeyboardShortcutsOptions {
  onTogglePlay: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRepeat: () => void;
  onToggleLoop: () => void;   // NEW — bound to L / l
  onSpeedDown: () => void;    // NEW — bound to [
  onSpeedUp: () => void;      // NEW — bound to ]
}

function useKeyboardShortcuts(options: KeyboardShortcutsOptions): void;
```

- Same event-target suppression rule as Phase 0: shortcuts do not fire when the event target is an input / textarea / contentEditable.
- `L` matches case-insensitively, consistent with `R` in Phase 0.
- `[` and `]` match the literal key (no Shift modifier required).

---

## Section 4 — Composition in `PlayerPage`

```typescript
const [loop, setLoop] = useState(false);
const [searchParams] = useSearchParams();
const measure = searchParams.get('measure') === '1';  // established PlayerPage convention from Phase 0

const { autoPauseEnabled, loopEnabled } = computePlaybackFlags(measure, loop);

const { currentIndex, currentWordIndex } = useSubtitleSync(player, segments);
useAutoPause(player, segments, currentIndex, autoPauseEnabled);
useLoopSegment(player, segments, currentIndex, loopEnabled);

const { rate, setRate, stepUp, stepDown } = usePlaybackRate(player);

useKeyboardShortcuts({
  onTogglePlay: ...,
  onPrev:       ...,
  onNext:       ...,
  onRepeat:     ...,
  onToggleLoop: () => setLoop(v => !v),
  onSpeedDown:  stepDown,
  onSpeedUp:    stepUp,
});
```

`PlayerControls` receives `loop`, `setLoop`, `rate`, `setRate` as props and renders the loop button + speed group. All playback-rate buttons simply call `setRate(step)`.

---

## Section 5 — Test strategy

### `useLoopSegment.test.ts`
- Fires `seekTo(segment.start)` exactly once when time crosses `end - epsilon` with `enabled=true`.
- Does NOT fire when `enabled=false`.
- Does NOT fire before `end - epsilon`.
- Does NOT pause (no `pauseVideo` call).
- After firing, does not fire a second time on the next tick (fire-guard works).
- Resets the guard when `currentIndex` changes, so a second segment's loop also fires.
- Cleans up RAF on unmount (no calls after unmount).

Uses the same fake-player pattern as `useAutoPause.test.ts` — a `vi.fn()`-backed `getCurrentTime` and `seekTo`, advanced manually between ticks.

### `usePlaybackRate.test.ts`
- Default `rate` is `1` when localStorage has no entry.
- Reads existing valid entry (`"0.75"`) from localStorage on mount.
- Invalid entry (`"0.6"`, `"banana"`, `""`) falls back to `1`.
- `setRate(0.5)` updates state, calls `player.setPlaybackRate(0.5)`, writes `"0.5"` to storage.
- `setRate(0.6)` is a no-op (defensive clamp).
- `stepUp` at `1.5` is a no-op; `stepDown` at `0.5` is a no-op (clamped).
- `stepUp` at `1` produces `1.25`; `stepDown` at `1` produces `0.75`.
- When `player` is `null`, state still updates and storage still writes; `setPlaybackRate` is called once when `player` transitions to non-null.

### `useAutoPause.test.ts` (modified)
- Existing cases keep working with `enabled=true`.
- NEW: `enabled=false` → no pause, no `pauseVideo` call, even across many RAF ticks that cross the boundary.

### `useKeyboardShortcuts.test.ts` (modified)
- `L` key → `onToggleLoop` fires.
- `[` key → `onSpeedDown` fires.
- `]` key → `onSpeedUp` fires.
- All three are suppressed when event target is an input/textarea.

### Composition test (in `PlayerPage.test.tsx` if exists, else a lightweight integration test)
- For each `(measure, loop)` in `{F,F}, {F,T}, {T,F}, {T,T}`: at most one of `autoPauseEnabled`/`loopEnabled` is true.

### ui-verifier (T07)
- Loop seek latency p95 ≤ 200ms (methodology: Playwright scripted timing per T07; no new URL flag).
- Speed-change sync precision: after `setRate(0.75)` followed by 1s of playback, sentence p95 ≤ 100ms / word p95 ≤ 150ms over ≥ 20 IFrame transitions.
- `?measure=1` disables loop: toggle loop on, navigate to `?measure=1`, verify `seekTo` is never called at a segment boundary (20+ transitions sample).
- localStorage round-trip: set rate via button, reload page, assert button group + `player.getPlaybackRate()` both equal the stored value.

---

## Section 6 — Edge cases

- **Segment switch during active loop.** User presses `L` to loop segment 3, then presses `→` mid-segment. Expected: `currentIndex` changes from 3 to 4; `useLoopSegment` resets its guard; at segment 4's end it will seek back to segment 4's start. Toggle stays ON. Covered by `useLoopSegment.test.ts` "multiple segments".
- **User seeks manually inside a looping segment.** User drags the YouTube timeline backward while `loop=true`. `currentIndex` may stay the same; `t` is now smaller than `end - epsilon`; no seek fires until `t` crosses end again. Behavior is correct without special handling.
- **User seeks OUT of the looping segment.** `currentIndex` changes; guard resets. New current segment gets the loop treatment. Correct by construction.
- **Speed change during a loop-seek.** Speed change happens on the same tick as the button press / keypress; `setPlaybackRate` applies. The loop seek is independent (it fires on the RAF tick that detects the boundary). The two never conflict because they operate on different player methods. During the ~190ms transient between `seekTo(start)` and the IFrame's acknowledgement, `getCurrentTime()` may still report the old end-of-segment time — this is the same IFrame postMessage physics Phase 0 excludes from sync-precision measurement. Speed change during this window is accepted as-is; the DoD's 1-second grace window before the precision gate applies covers it.
- **Degenerate segment (0-duration / negative-duration / too-short).** Whisper occasionally produces segments where `end <= start` or `end - start` is within epsilon. `useLoopSegment` short-circuits: if `end - start <= 2 * AUTO_PAUSE_EPSILON`, the tick returns without firing or touching the guard. Why `2 * epsilon` and not `1 * epsilon`: the loop needs at least one epsilon of playable room before the trigger band plus one epsilon after the seek lands — otherwise the guard watermark never gets a chance to re-arm. Auto-pause is unaffected (it terminates its RAF after firing, so even a tiny segment pauses exactly once). T01 covers `end < start`, `end == start`, `end - start == epsilon` (still degenerate, no-op), and `end - start == 2 * epsilon + 0.001` (just barely OK, fires normally).
- **Page load with no localStorage entry.** `readValidated` returns fallback `1`; `player.setPlaybackRate(1)` is called once when the player is ready. Default behavior unchanged from Phase 0.
- **Page load with `echolearn.playback_rate = "2"`.** Not in `ALLOWED_RATES` → `readValidated` returns fallback `1`. No error, no warning spam.
- **Page load with `?measure=1` and `loop=true` stored somewhere.** Not applicable — loop does not persist. Fresh page = `loop=false`. `?measure=1` simply never gets to matter for loop here.
- **localStorage schema migration.** Nothing to migrate: this is the first Phase 1a key; there is no pre-existing schema to upgrade. If future changes need to evolve the format, bump to a new key (`echolearn.playback_rate.v2`) rather than reinterpret — the current key always means "one of the five allowed rates, as a string".
- **IFrame not ready when user changes speed.** `player` is `null` until the IFrame API finishes loading. State updates and storage writes happen regardless. When `player` becomes non-null, `usePlaybackRate` applies the current rate exactly once (see Section 3). Covered by a dedicated test.
- **Rapid `[[[[[`**. Each keypress calls `stepDown`; after reaching `0.5` further presses are no-ops. No thrashing. localStorage writes coalesce naturally because each write is synchronous and identical.

---

## Section 7 — Size / convention gate

- `useLoopSegment.ts` target ≤ 80 LOC (RAF loop + guard + cleanup + degenerate-segment short-circuit).
- `usePlaybackRate.ts` target ≤ 80 LOC (state + three callbacks + effect).
- `lib/storage.ts` target ≤ 40 LOC (three tiny functions).
- `features/player/lib/constants.ts` target ≤ 10 LOC (exports `AUTO_PAUSE_EPSILON`; optional cohabitation with `flags.ts` if the combined file stays under 30 LOC).
- `features/player/lib/flags.ts` target ≤ 15 LOC (`computePlaybackFlags` pure helper).
- `useAutoPause.ts` must remain ≤ 200 LOC after adding `enabled`. Imports `AUTO_PAUSE_EPSILON` from the new `lib/constants.ts`.
- `useKeyboardShortcuts.ts` three new handlers ≈ 10–15 LOC added; still ≤ 200.
- `PlayerControls.tsx` adds ~40 LOC for loop button + five-step group; verify ≤ 200 post-change.
- `PlayerPage.tsx` adds composition glue (~20 LOC); verify ≤ 200 post-change.

All files verified in T07 as part of the 200-line scan (same command Phase 0 used).
