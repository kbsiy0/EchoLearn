# Phase 1a: Loop & Speed — Proposal

## Summary
Add two learner-facing playback controls on top of the Phase 0 sync engine: **single-segment infinite loop** (toggle the current sentence to repeat until disengaged) and a **five-step playback-speed selector** (0.5 / 0.75 / 1 / 1.25 / 1.5). Both are user-facing features; neither changes backend or the Whisper time base. The speed preference persists across sessions; loop does not.

- **Change id:** `phase1a-loop-and-speed`
- **Branch:** `change/phase1a-loop-and-speed`

## Why this change exists
Learners watching a foreign-language clip repeatedly ask for two things Phase 0 did not ship:

1. **Re-hear the same sentence without manual rewinding.** Today the only per-sentence repeat is the one-shot `R` key. Pressing `R` fifteen times to drill a phrase is clumsy, especially when the learner is also reading captions.
2. **Slow down fast speech.** YouTube's native speed menu is hidden behind hover + submenu and resets when the IFrame reloads; there is no in-app affordance or keyboard shortcut.

Both are pure-frontend additions — no new data, no backend work. They slot into the existing hook composition in `PlayerPage`.

## What changes — high level

- **Loop toggle.** Press `L` (or click a loop button in `PlayerControls`) to mark the current segment as looping. When time crosses `segment.end - AUTO_PAUSE_EPSILON`, the player seeks back to `segment.start` instead of pausing. Pressing `L` again, or jumping to a different segment via ←/→ or by seeking, disengages the loop seek for the new segment but preserves the toggle state.
- **Speed control.** A five-button group in `PlayerControls` exposes the YouTube-supported steps `0.5 / 0.75 / 1 / 1.25 / 1.5`; active step is highlighted. `[` moves one step slower, `]` one step faster, clamped at both ends. The chosen rate is written to `localStorage` under `echolearn.playback_rate` and restored on page load.
- **Hook composition.** Two new hooks — `useLoopSegment` and `usePlaybackRate` — sit alongside the Phase 0 player hooks. `useAutoPause` gets an `enabled` prop; `PlayerPage` computes `autoPauseEnabled = !measure && !loop` and `loopEnabled = !measure && loop` so the two boundary-end behaviors are mutually exclusive at any moment.
- **Keyboard surface.** `useKeyboardShortcuts` gains three new callbacks: `onToggleLoop`, `onSpeedDown`, `onSpeedUp`.
- **Measurement mode.** `?measure=1` now disables loop in addition to auto-pause. Speed remains user-controllable. Rationale: `?measure=1` is "give me continuous playback for precision measurement"; loop would reset time across the boundary and destroy the transition samples, so it is forced off. Speed has no measurement-contamination concern.

## Out of scope — explicitly deferred

- Segment streaming / incremental delivery (Phase 1b)
- A/B-range loop, N-times repeat, or variable loop counts (future — not a Phase 1 ask)
- Speed steps outside `[0.5, 0.75, 1, 1.25, 1.5]` (no 0.6×, no 2×; must match YouTube-native steps)
- Backend changes of any kind
- Persisting loop state across page reloads (intentional — fresh page = fresh intent)
- Global / default-speed preference UI (the localStorage value is the whole UX)

## Risks

- **Loop seek bursting on IFrame postMessage latency.** `seekTo` goes out via postMessage; `getCurrentTime()` keeps reporting the old end-of-segment value for ~190ms (~11 RAF ticks at 60fps). Naive "reset guard immediately on seek" would fire `seekTo` every frame during that window. Mitigation: fire-guard stays engaged until `t` is observed below a midpoint watermark `(segment.start + segment.end) / 2`, then re-arms. Design (Section 2, Invariant 3) specifies the exact rule; T01 tests assert zero extra seeks during the postMessage transient.
- **Malformed segment infinite seek.** Whisper occasionally produces 0-duration or negative-duration segments. With `end - start <= 2 * AUTO_PAUSE_EPSILON`, the loop would re-trigger before the guard could re-arm. Mitigation: `useLoopSegment` no-ops on degenerate segments (see `specs/sync.md`).
- **Loop and auto-pause racing.** Both watch the same epsilon band around `segment.end`. Mitigation: `PlayerPage` computes mutually exclusive flags — at any moment at most one of `{autoPauseEnabled, loopEnabled}` is true. Enforced by a Vitest test on the composition.
- **localStorage schema creep.** Adding one key is trivial today, but setting a precedent invites future keys without a shared wrapper. Mitigation: land a thin `lib/storage.ts` that reads/writes namespaced keys and validates against a fallback. Invalid / unknown values fall back to defaults.
- **YouTube IFrame speed semantics.** `setPlaybackRate` only accepts values in `getAvailablePlaybackRates()`. Mitigation: the five values are a subset of the documented YT supported rates; validate anyway by clamping to the allowlist before calling.
- **Measurement-mode regression.** Phase 0 shipped `?measure=1` with a single meaning ("auto-pause off"). Expanding its meaning risks ambiguity in the ui-verifier's interpretation. Mitigation: spec change explicitly documents both disabled behaviors; ui-verifier docs under T07 of Phase 0 referenced loop OFF-by-default, which still holds.

## Acceptance gates (Definition of Done)

- Loop ON: at `t >= segment.end - AUTO_PAUSE_EPSILON` the player seeks to `segment.start`; no pause is issued. Seek→resume latency p95 ≤ 200ms over ≥ 20 cycles, measured by ui-verifier via Playwright scripted timing (reading `player.getCurrentTime()` before/after segment-end in `page.evaluate`). No new URL flag is introduced; `?measure=1` continues to force loop OFF.
- Speed change takes effect on the tick that `setPlaybackRate` returns. After 1 second of playback at the new rate, sync precision still meets the Phase 0 bar: sentence p95 ≤ 100ms, word p95 ≤ 150ms.
- `?measure=1` URL: auto-pause OFF (Phase 0 behavior, unchanged), loop forced OFF regardless of toggle, speed still adjustable.
- `echolearn.playback_rate` round-trips: set speed → reload page → button group and actual playback rate both reflect the stored value. Invalid stored value → falls back to `1`.
- vitest green; lint green; `npm run build` succeeds.
- Every new or modified file stays ≤ 200 LOC (project-wide rule from Phase 0).
- ui-verifier produces `docs/ui-verification/phase1a-loop-and-speed.md` with PASS on: loop seek latency p95, speed-change sync precision, `?measure=1` disables loop, localStorage round-trip.
