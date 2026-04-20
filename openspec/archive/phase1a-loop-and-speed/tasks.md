# Phase 1a: Loop & Speed — Tasks

Ordering reflects the dependency graph below. T01 / T02 / T03 are independent and MAY run in parallel (three separate `tdd-implementer` dispatches). T04 / T05 / T06a are merge points depending on their hooks; T06b depends on both T04 and T05 because all three write to `PlayerPage.tsx`. T07 is the final ui-verifier gate.

```
T01 (useLoopSegment)    ─┐
T02 (usePlaybackRate)   ─┼─→ T04 (loop UI wiring)  ─┐
T03 (useAutoPause ext)  ─┘   T05 (speed UI wiring) ─┼─→ T06b (keyboard wiring) ─→ T07
                             T06a (keyboard hook)  ─┘
```

T06a (hook signature + tests, no `PlayerPage.tsx` touch) runs in parallel with T04 / T05. T06b (the actual `PlayerPage.tsx` plumbing of the three new callbacks) runs after T04 AND T05 land, so only one task at a time writes to `PlayerPage.tsx`.

Legend:
- **Dependencies** = tasks that must be complete before this one can start.
- **Parallelizable with** = tasks that may run concurrently (independent file sets, no handoff).
- **Required agents** = must sign off before the task is considered done. `tdd-implementer` is always required. `ui-verifier` is required for any task with observable frontend behavior change, gated at T07. `spec-reviewer` reviews every task at completion.

**Pre-flight check (applies to every task T01–T07):**
> tdd-implementer MUST verify `git branch --show-current` returns `change/phase1a-loop-and-speed` before any file change. If on `main`, STOP and surface to parent; do not switch or commit.

**Commit message template (every task):**
> `<type>(<scope>): <subject>` per project convention. One task = one commit (refactor sub-step may be a second commit within the same task).

---

## T01 — `useLoopSegment` hook + tests

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** none
- **Parallelizable with:** T02, T03

**Acceptance criteria**
- `frontend/src/features/player/lib/constants.ts` (NEW) exports `export const AUTO_PAUSE_EPSILON = 0.08;`. This is the single source; all hooks import from here.
- `frontend/src/features/player/hooks/useLoopSegment.ts` implements the hook per `design.md` Section 3:
  - Signature: `(player, segments, currentIndex, enabled) => void`.
  - Imports `AUTO_PAUSE_EPSILON` from `../lib/constants`.
  - RAF loop only when `enabled && player && segments.length > 0`.
  - **Degenerate-segment short-circuit:** if `segments[currentIndex].end - segments[currentIndex].start <= 2 * AUTO_PAUSE_EPSILON`, the tick returns without firing or touching the guard.
  - On tick (non-degenerate): if `currentIndex >= 0` and `t >= segments[currentIndex].end - AUTO_PAUSE_EPSILON` and `lastFiredIndexRef.current !== currentIndex`, call `player.seekTo(segments[currentIndex].start, true)` and set `lastFiredIndexRef.current = currentIndex`.
  - **Watermark guard-release:** on any tick where `lastFiredIndexRef.current === currentIndex` and `t < (start + end) / 2`, reset `lastFiredIndexRef.current = -1` (tolerates IFrame postMessage ~190ms transient — invariant 3).
  - Resets `lastFiredIndexRef.current = -1` when `currentIndex` changes.
  - On `enabled=false`, cancels RAF; no-op.
  - Cleans up RAF on unmount and on any dep change.
- `frontend/src/features/player/hooks/useLoopSegment.test.ts` asserts:
  - `test_fires_seek_at_end_minus_epsilon` — fires `seekTo(segment.start)` exactly once.
  - `test_no_fire_when_disabled` — `enabled=false` across many ticks → zero `seekTo` calls.
  - `test_no_fire_before_epsilon_band` — `t < end - epsilon` → no seek.
  - `test_does_not_pause` — `pauseVideo` never called (loop is not auto-pause).
  - `test_fire_guard_holds_through_postmessage_transient` — after seek fires, 10 consecutive ticks still reporting `t >= end - epsilon` (simulating IFrame postMessage lag) produce exactly zero additional `seekTo` calls.
  - `test_fire_guard_rearms_after_watermark_crossed` — following the previous scenario, once a tick reports `t < (start + end) / 2`, the guard re-arms; the next tick at `t >= end - epsilon` fires exactly one more seek.
  - `test_guard_resets_on_segment_change` — `currentIndex` rerender → next segment's end still triggers a seek.
  - `test_noop_on_degenerate_segment` — four sub-cases: (a) `end < start`, (b) `end == start`, (c) `end - start == AUTO_PAUSE_EPSILON` (still degenerate, still no-op), (d) `end - start == 2 * AUTO_PAUSE_EPSILON + 0.001` (just barely OK, fires normally). In the no-op cases, ≥ 20 ticks crossing the nominal boundary produce zero `seekTo` calls.
  - `test_raf_cleanup_on_unmount` — after unmount, no further `getCurrentTime` calls.
- `npm run test -- --run` green for the new file and all existing vitest suites.
- `useLoopSegment.ts` ≤ 200 LOC (target ≤ 80); `lib/constants.ts` ≤ 10 LOC.

**Files expected to touch**
- `frontend/src/features/player/lib/constants.ts` (NEW)
- `frontend/src/features/player/hooks/useLoopSegment.ts` (NEW)
- `frontend/src/features/player/hooks/useLoopSegment.test.ts` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): add useLoopSegment hook`

---

## T02 — `usePlaybackRate` hook + `lib/storage.ts` + tests

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** none
- **Parallelizable with:** T01, T03

**Acceptance criteria**
- `frontend/src/lib/storage.ts` (NEW — verified no existing `storage.ts` in `lib/`) exposes:
  - `readString(key: string): string | null`
  - `writeString(key: string, value: string): void`
  - `readValidated<T>(key, parse, fallback): T`
  - All methods wrap localStorage access in `try/catch`; errors never bubble.
- `frontend/src/features/player/hooks/usePlaybackRate.ts` implements the hook per `design.md` Section 3:
  - `ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5] as const` exported.
  - `PlaybackRate` type derived from the tuple.
  - Returns `{ rate, setRate, stepUp, stepDown }`.
  - Reads `echolearn.playback_rate` on mount via `readValidated`.
  - On `rate` change: calls `player.setPlaybackRate(rate)` (if `player !== null`) and writes to storage.
  - When `player` transitions from `null` to non-null, applies current `rate` once.
  - `setRate` clamps to allowed list (no-op for invalid values).
  - `stepUp` / `stepDown` clamped at array boundaries (no wraparound).
- `frontend/src/features/player/hooks/usePlaybackRate.test.ts` asserts:
  - `test_default_rate_is_one_when_storage_empty`.
  - `test_reads_valid_stored_rate_on_mount` — `"0.75"` → `rate === 0.75`.
  - `test_invalid_stored_rate_falls_back_to_one` — cases: `"0.6"`, `"banana"`, `""`.
  - `test_set_rate_updates_state_player_storage` — calls `setRate(0.5)` → state, `setPlaybackRate(0.5)`, `localStorage.getItem('echolearn.playback_rate') === "0.5"`.
  - `test_set_rate_rejects_disallowed_value` — `setRate(0.6 as any)` → state unchanged.
  - `test_step_up_at_max_is_noop` — starting at `1.5`, `stepUp` keeps `1.5`.
  - `test_step_down_at_min_is_noop` — starting at `0.5`, `stepDown` keeps `0.5`.
  - `test_step_up_from_one` — produces `1.25`.
  - `test_step_down_from_one` — produces `0.75`.
  - `test_player_null_then_ready_applies_rate_once` — mount with `player=null`, change rate, then transition `player` to non-null; `setPlaybackRate` called exactly once with current rate.
  - `test_stored_rate_applied_when_player_becomes_ready` — seed `localStorage['echolearn.playback_rate'] = "0.75"`, mount with `player=null`, then transition `player` to non-null; `setPlaybackRate(0.75)` is called exactly once without any user interaction. (This is the common page-load path.)
- `frontend/src/lib/storage.test.ts` (NEW) asserts:
  - `test_read_returns_null_when_storage_throws` — mocked localStorage.getItem throws → `readString` returns `null`, no rethrow.
  - `test_write_swallows_quota_exceeded` — mocked localStorage.setItem throws `QuotaExceededError` → `writeString` returns normally, no rethrow, no console error.
  - `test_read_validated_falls_back_on_invalid` — stored value fails the `parse` function → `readValidated` returns fallback.
- `npm run test -- --run` green.
- Hook file ≤ 200 LOC (target ≤ 80); `storage.ts` ≤ 40 LOC.

**Files expected to touch**
- `frontend/src/lib/storage.ts` (NEW)
- `frontend/src/lib/storage.test.ts` (NEW)
- `frontend/src/features/player/hooks/usePlaybackRate.ts` (NEW)
- `frontend/src/features/player/hooks/usePlaybackRate.test.ts` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): add usePlaybackRate hook and storage helper`

---

## T03 — Extend `useAutoPause` with `enabled` prop

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** none
- **Parallelizable with:** T01, T02

**Acceptance criteria**
- `useAutoPause` signature updated to `(player, segments, currentIndex, enabled: boolean) => void`, matching `specs/sync.md` (already the contract in the archived Phase 0 spec — this task brings the implementation into full conformance with the documented shape).
- `useAutoPause.ts` now imports `AUTO_PAUSE_EPSILON` from `../lib/constants` (the new shared module created in T01). Any local definition of the constant is removed. Note: T01 creates `lib/constants.ts`; T03 migrates `useAutoPause.ts` to consume it. If T01 has not merged yet, T03 inlines the same value and adjusts the import in a follow-up commit — but the expected path is T01-first or the two tasks coordinated at merge.
- When `enabled=false`, the hook is a pure no-op: no RAF started, no `pauseVideo` call, no ref writes.
- Existing behavior preserved when `enabled=true`: pauses exactly once at `segment.end ± 0.08s` per segment.
- All existing `useAutoPause.test.ts` cases updated to pass `enabled=true` and continue to pass unchanged.
- NEW test `test_enabled_false_never_pauses` asserts that over many RAF ticks that cross the boundary, `pauseVideo` is never called.
- Callers that import `useAutoPause` are left alone in this task (the `PlayerPage` wiring change happens in T04); if callers currently pass fewer arguments, either (a) TypeScript compilation breaks intentionally to be fixed in T04, or (b) `enabled` defaults to `true` — implementer picks (b) to keep T03 independently mergeable, and T04 removes the default.
- File length ≤ 200 LOC after change.
- `npm run test -- --run` green; lint clean.

**Files expected to touch**
- `frontend/src/features/player/hooks/useAutoPause.ts`
- `frontend/src/features/player/hooks/useAutoPause.test.ts`

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `refactor(player): add enabled prop to useAutoPause`

---

## T04 — Loop toggle UI + `PlayerPage` wiring

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** T01, T03
- **Parallelizable with:** T05

**Acceptance criteria**
- `frontend/src/features/player/lib/flags.ts` (NEW) exports the pure helper `computePlaybackFlags(measure: boolean, loop: boolean): { autoPauseEnabled: boolean; loopEnabled: boolean }` as specified in `design.md` Section 2. May cohabit with `lib/constants.ts` if the combined file stays ≤ 30 LOC; otherwise its own file.
- `frontend/src/features/player/lib/flags.test.ts` (NEW) asserts the full matrix for `(measure, loop)` in `{F,F}, {F,T}, {T,F}, {T,T}`: at most one of `{autoPauseEnabled, loopEnabled}` is true in every cell. This is the composition invariant — pure unit test, no React render needed.
- `PlayerControls.tsx` gains a loop toggle button: accessible label ("Loop segment"), visible active state when `loop=true`, click handler calls the passed `onToggleLoop`.
- `PlayerPage.tsx`:
  - Owns `const [loop, setLoop] = useState(false)`.
  - Reads `measure` inline: `const measure = searchParams.get('measure') === '1'` (established PlayerPage convention from Phase 0 — do not introduce a new `useMeasureFlag` hook).
  - Destructures flags: `const { autoPauseEnabled, loopEnabled } = computePlaybackFlags(measure, loop)`.
  - Calls `useAutoPause(player, segments, currentIndex, autoPauseEnabled)` (removing the default `enabled=true` fallback from T03).
  - Calls `useLoopSegment(player, segments, currentIndex, loopEnabled)`.
  - Passes `loop` and `onToggleLoop={() => setLoop(v => !v)}` into `PlayerControls`.
- Vitest green; `npm run build` succeeds.
- `PlayerPage.tsx` ≤ 200 LOC after change; `PlayerControls.tsx` ≤ 200 LOC after change; `lib/flags.ts` ≤ 15 LOC.

**Files expected to touch**
- `frontend/src/features/player/lib/flags.ts` (NEW)
- `frontend/src/features/player/lib/flags.test.ts` (NEW)
- `frontend/src/features/player/components/PlayerControls.tsx`
- `frontend/src/routes/PlayerPage.tsx`

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): wire loop toggle into PlayerPage`

---

## T05 — Five-step speed group UI + `PlayerPage` wiring

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** T02
- **Parallelizable with:** T04

**Acceptance criteria**
- `PlayerControls.tsx` gains a five-button group rendering `ALLOWED_RATES = [0.5, 0.75, 1, 1.25, 1.5]`:
  - Each button shows the rate label (e.g., `0.75×` or `0.75`).
  - Active button (`rate === step`) has a visible active style.
  - Click calls the passed `onSetRate(step)`.
  - Buttons expose accessible names (e.g., `aria-label="Playback speed 0.75x"` or equivalent) and `aria-pressed` reflecting active state.
- `PlayerPage.tsx`:
  - Calls `const { rate, setRate, stepUp, stepDown } = usePlaybackRate(player)`.
  - Passes `rate` and `onSetRate={setRate}` into `PlayerControls`.
  - (Does NOT yet wire `stepUp` / `stepDown` — keyboard shortcuts arrive in T06.)
- Vitest green; `npm run build` succeeds.
- `PlayerControls.tsx` ≤ 200 LOC after change; `PlayerPage.tsx` ≤ 200 LOC.

**Files expected to touch**
- `frontend/src/features/player/components/PlayerControls.tsx`
- `frontend/src/routes/PlayerPage.tsx`

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): add playback speed button group`

---

## T06a — Extend `useKeyboardShortcuts` hook signature + tests (no `PlayerPage.tsx` touch)

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** none (hook-only; keeps PlayerPage writes out of this task)
- **Parallelizable with:** T01, T02, T03, T04, T05

**Acceptance criteria**
- `useKeyboardShortcuts.ts` extended with three optional callbacks on `KeyboardShortcutsOptions`:
  - `onToggleLoop?: () => void` — bound to `L` / `l`.
  - `onSpeedDown?: () => void` — bound to `[`.
  - `onSpeedUp?: () => void` — bound to `]`.
- Callbacks are optional; omitted callbacks leave the corresponding key as a no-op. Rationale: keeps the hook backward-compatible (Phase 0 callers still compile) and makes it trivial to test combinations.
- Event-target suppression (input/textarea/contentEditable) applies to all three new keys, identical to Phase 0.
- `useKeyboardShortcuts.test.ts` extended:
  - `test_l_toggles_loop` — `keydown` `L` → `onToggleLoop` called.
  - `test_l_lowercase_toggles_loop` — `keydown` `l` → `onToggleLoop` called.
  - `test_bracket_left_steps_down` — `keydown` `[` → `onSpeedDown` called.
  - `test_bracket_right_steps_up` — `keydown` `]` → `onSpeedUp` called.
  - `test_shortcuts_suppressed_in_input` — all three suppressed when target is an `<input>`.
  - `test_rapid_toggle_converges` — five successive `L` keypresses each fire `onToggleLoop` exactly once; no stuck intermediate state. (React state batching is the integration concern; this test only asserts the hook emits one call per keypress.)
- Does NOT touch `PlayerPage.tsx`. Wiring is T06b.
- Vitest green; `npm run build` succeeds.
- `useKeyboardShortcuts.ts` ≤ 200 LOC after change.

**Files expected to touch**
- `frontend/src/features/player/hooks/useKeyboardShortcuts.ts`
- `frontend/src/features/player/hooks/useKeyboardShortcuts.test.ts`

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): add L / [ / ] handlers to useKeyboardShortcuts`

---

## T06b — Wire keyboard callbacks into `PlayerPage.tsx`

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** T04 AND T05 AND T06a (all three must be merged — T04/T05 own the `loop` / `setRate` / `stepUp` / `stepDown` bindings T06b plumbs into the hook; T06a owns the hook signature)
- **Parallelizable with:** none (only task in the batch writing to `PlayerPage.tsx` after T04 and T05)

**Acceptance criteria**
- `PlayerPage.tsx` passes the three new callbacks into `useKeyboardShortcuts`:
  - `onToggleLoop: () => setLoop(v => !v)`
  - `onSpeedDown: stepDown`
  - `onSpeedUp: stepUp`
- No other behavior changes in `PlayerPage.tsx`; this task is pure wiring.
- Vitest green; `npm run build` succeeds.
- `PlayerPage.tsx` ≤ 200 LOC after change.

**Files expected to touch**
- `frontend/src/routes/PlayerPage.tsx`

**Required agents**
- tdd-implementer
- spec-reviewer

**Suggested commit:** `feat(player): wire loop and speed keyboard shortcuts`

---

## T07 — ui-verifier pass

- **Pre-flight:** verify branch `change/phase1a-loop-and-speed`. If on main, STOP and surface.
- **Dependencies:** T01–T06b green
- **Parallelizable with:** none

**Acceptance criteria**
- ui-verifier agent boots real dev servers (backend on 8000, frontend on 5173), drives Playwright through the Phase 1a flows, and produces `docs/ui-verification/phase1a-loop-and-speed.md` with PASS on all of:
  - **Loop seek latency.** With loop ON (no `?measure=1`, because `?measure=1` forces loop OFF by spec), measured seek→resume latency p95 ≤ 200ms over ≥ 20 end-of-segment cycles on a representative video. **Methodology: Playwright scripted timing.** `page.evaluate()` reads `player.getCurrentTime()` before and after each segment-end in a test harness, computes latency per cycle, and aggregates p95. No new URL flag is introduced. `?measure=1` continues to mean "auto-pause OFF + loop OFF" per the spec.
  - **Speed-change sync precision.** After `setRate(0.75)` followed by ≥ 1s of playback, sentence-level p95 ≤ 100ms and word-level p95 ≤ 150ms over ≥ 20 IFrame transitions (same bar as Phase 0). Measured with `?measure=1` (auto-pause off) so the precision number is not contaminated by resume latency.
  - **`?measure=1` disables loop.** With loop toggle ON and `?measure=1` in the URL, verify `seekTo` is never called at a segment boundary over ≥ 20 transitions. Auto-pause is also off (Phase 0 behavior retained).
  - **localStorage round-trip.** Change rate via the button group, reload the page, assert the button group active state and `player.getPlaybackRate()` both reflect the stored value.
- Report also records: `pytest` (backend should be unchanged — quick smoke), `vitest`, `eslint`, `npm run build` all green.
- **200-line scan** — same command from Phase 0 T09 runs and shows no `.py`/`.ts`/`.tsx` file over 200 lines across `backend/app` + `frontend/src`.
- If any metric fails, ui-verifier surfaces a FAIL; loop back to the relevant T01–T06 task; do not mark T07 done.

**Files expected to touch**
- `docs/ui-verification/phase1a-loop-and-speed.md` (NEW)
- (No production code changes — verification task only; any remediation loops back to T01–T06.)

**Required agents**
- ui-verifier (final gate)
- spec-reviewer (final sign-off)

**Suggested commit:** `docs(ui-verification): phase1a loop and speed report`
