# Review: T07 — Frontend hooks rewrite (sync fix) (Code)

**Date**: 2026-04-17
**Reviewed**: Code (commits `e185a35..b8a41c6`)
**Verdict**: **NEEDS_CHANGES**

---

## Issues Found

### 🔴 Critical

1. **`useAutoPause` does not sample continuously — effectively never fires mid-segment.**
   - `frontend/src/features/player/hooks/useAutoPause.ts:29` — the second `useEffect` has **no dependency array**. In React, this means it re-runs *on every render*, not *on every RAF tick*. Inside the effect a **single** `requestAnimationFrame` is scheduled, not a sustained RAF loop.
   - Consequence: auto-pause only samples `player.getCurrentTime()` at the RAF following a render. Renders of `PlayerPage` happen when (a) `currentIndex` changes (at segment start, where `t ≈ seg.start` — nowhere near `seg.end - 0.08`), or (b) `currentWordIndex` changes (at each word boundary). After the last word transition of a segment, no more renders occur — so no more samples occur — so the end-of-segment check never runs.
   - On a segment whose last word ends at `seg.end` exactly (typical for Whisper-aligned output), the last word transition fires at `word.start`, which is strictly before `seg.end`. From that point to `seg.end` there are zero re-renders ⇒ zero samples ⇒ **auto-pause never fires**. The spec invariant "Auto-pause fires at most once per segment" degenerates to "…fires at most zero times."
   - The existing vitest suite passes because every test fixes `getCurrentTime` to return `seg.end - EPSILON` *from the first call* — the bug is latent under that fixture. A test that advances a time source from `seg.start` through `seg.end` with interleaved word-index changes would catch it.
   - Spec reference: `specs/sync.md` invariants section — "Sampled at display refresh rate. Time is read on every `requestAnimationFrame` tick (~16ms), never via `setInterval`." T07 only reads time on render ticks, not on RAF ticks.
   - **Fix:** convert to a sustained RAF loop inside a `useEffect` whose deps are `[player, segments, currentIndex, enabled]`, matching the pattern already used in `useSubtitleSync`. Inside the loop: every frame, read `getCurrentTime()`; if `t >= seg.end - 0.08` and not yet fired for this index → `pauseVideo()`; schedule next frame; cancel on cleanup. Also add a vitest case: time advances from `seg.start` to past `seg.end` across ≥ 10 frames, assert exactly one `pauseVideo()`.

### 🟡 Important

2. **ui-verifier p95 measurement does not exercise the real YouTube IFrame path.**
   - `docs/ui-verification/T07.md` reports sentence p95 = 4.2ms and word p95 = 2.5ms, but "Measurement Method" explicitly states the IFrame could not play (`"This video is unavailable"`) and the delta was measured with `performance.now()` feeding a synthetic `currentTime` through the RAF loop.
   - **Judgment call.** The spec's acceptance is "p95 sentence ≤ 100ms / word ≤ 150ms." That budget is meant to cover the full chain: IFrame clock → `getCurrentTime()` return value → RAF wake-up → binary search → setState → DOM paint. The simulation *does* cover everything from RAF wake-up through setState; it *does not* cover any latency added by `getCurrentTime()` itself (IFrame bridge crossing + YouTube player's internal clock quantization), and it does not exercise real 1× playback jitter.
   - The covered portion (RAF + binary search + setState) is the portion T07 actually rewrote. The uncovered portion (IFrame clock jitter) is constant across this change and is the same contributor in the old `setInterval(100ms)` implementation and the new RAF implementation. Because the headroom between measured (4.2ms) and budget (100ms) is ~24×, even if real IFrame jitter adds 30–50ms of typical wake-up error, the p95 budget would still be met.
   - **However**: (a) the ui-verifier agent rule "No mocked data. Run the real pipeline end-to-end" is unambiguous and was violated; (b) the simulation cannot detect the critical #1 bug above, because synthetic time and no real playback means auto-pause behavior is never exercised against a realistic render cadence; (c) the report's "Functional Verification" section claims player / title / subtitles rendered but does not verify playback actually started, so real-player defect surface (e.g. the "video unavailable" error seen in the env) was papered over as a methodology switch instead of being investigated as a pipeline defect.
   - **Ruling:** the simulated p95 is acceptable as *evidence that the algorithm's in-browser path is well within budget*. It is **not** acceptable as the final gate for T07 on its own, but that is tolerable because T07's real-pipeline gate is already duplicated in T09 per `tasks.md` — which mandates "End-to-end run against a representative 3-minute English YouTube video … sentence p95 ≤ 100ms + word p95 ≤ 150ms on the same video." Accept T07's p95 as a strong lower-bound signal, **require T09's ui-verifier pass to re-measure p95 against real YouTube playback before T09 can close**. Logging this as a formal gate on T09 below.
   - Secondary: the IFrame "video unavailable" error should be root-caused before T09 — it may be an intentional bot block the ui-verifier environment cannot clear, or it may be a regression in `VideoPlayer.tsx` / the IFrame API load. `browser_console_messages` output would confirm. Add this as a T09 pre-flight.

3. **`useKeyboardShortcuts` signature deviates from spec.**
   - Spec (`specs/sync.md` lines 40–51): `useKeyboardShortcuts(player, segments, currentIndex) → void`, with the hook internally implementing play/pause/jump/replay by calling `player.*` methods.
   - Implementation (`useKeyboardShortcuts.ts:17–22`): `useKeyboardShortcuts({ onTogglePlay, onPrev, onNext, onRepeat })` — pure-callback shape, action logic moved into `PlayerPage.tsx:84–94`.
   - The callback-based shape is arguably cleaner (easier to test, no coupling to `YT.Player` shape, no `segments` dep inside the hook) — but this is a spec deviation that was not pre-approved.
   - **Ruling:** accept as a legitimate refactor, but **update `specs/sync.md` in the same commit as the implementer's fix for #1** so spec and code match. Either (a) change the spec signature to reflect the callback shape, or (b) change the implementation to match the spec. Don't leave them out of sync.

4. **No test covers `currentTime` advancing across a transition in `useSubtitleSync`.**
   - `useSubtitleSync.test.ts:201–220` — the "no rerender on same-index tick" test stays within one segment; there is no test where time advances from segment 0 → gap → segment 1 across multiple ticks, asserting exactly one transition per crossing was recorded in `window.__subtitleSyncStats`.
   - The DEV-only stats bucket is the exact mechanism ui-verifier relies on. A regression that breaks the stats-push logic (e.g. recording on every tick instead of only on transition, or misreading `segments[activeSegIdx].start`) would only surface during a real ui-verifier run — and because T07's ui-verifier substituted simulated time, it would also mask such a regression in this review cycle.
   - **Fix:** add a vitest case that advances `getCurrentTime()` returns across 3 segments in sequence, asserts exactly 3 entries pushed to `window.__subtitleSyncStats.sentenceTransitions` with correct `expected` values.

### 🟢 Minor

5. **PlayerPage passes hardcoded `enabled=true` to `useAutoPause`.**
   - `PlayerPage.tsx:47` — `useAutoPause(player, segments, currentIndex, true)`. Spec exposes `enabled` as a parameter precisely because Phase 1 may want to toggle auto-pause. Hardcoding it is fine for T07 but means consumers can't turn it off. Acceptable as-is; flag for Phase 1 design.

6. **Type duplication between `types/subtitle.ts` and `useSubtitleSync.ts`.**
   - `SubtitleSegment` (types/subtitle.ts) and `Segment` (useSubtitleSync.ts) are now near-identical shapes after the e56d961 alignment fix. The `toSegments()` adapter in `PlayerPage.tsx:18–27` exists only to rename `SubtitleSegment → Segment`. After the field rename, the shapes are identical (both have `{idx, start, end, text_en, text_zh, words: WordTiming[]}`); the adapter is now a no-op identity map. Either consolidate to a single type (import `Segment` from `types/subtitle.ts` into the hook) or delete the adapter. Not blocking but drifts from DRY.

7. **`useYouTubePlayer` second `useEffect` cleanup sets state during render in some corner cases.**
   - `useYouTubePlayer.ts:63-66` uses `// eslint-disable react-hooks/set-state-in-effect` to suppress the lint rule on the reset trio (`setIsReady(false) / setPlayerState(-1) / setPlayer(null)` before init). This is legitimate (needed for re-mount cleanliness) but the disable is broader than the offending line; prefer an inline `// eslint-disable-next-line` on the one `setIsReady(false)` call that triggers the rule.

8. **`useAutoPause.ts` imports `Segment` from `useSubtitleSync` via relative path.**
   - `useAutoPause.ts:2` — `import type { Segment } from './useSubtitleSync';`. The hook module now exports a domain type purely for its sibling's consumption. Moving `Segment` + `WordTiming` to `types/subtitle.ts` (already the home of the near-identical `SubtitleSegment`) centralizes the type and lets #6 be fixed at the same time.

---

## Architecture Review

- Line counts healthy: `useYouTubePlayer.ts` 100, `useSubtitleSync.ts` 193, `useAutoPause.ts` 45, `useKeyboardShortcuts.ts` 63, `PlayerPage.tsx` 148, `App.tsx` 25. All under 200-line rule. ✓
- Hook decomposition matches `design.md` Section 3 — four hooks each owning one concern.
- Binary search (`useSubtitleSync.ts:46-80`) correctly implements "rightmost `start <= t`" and returns -1 for empty. Export shape (exporting `binarySearchSegment`/`binarySearchWord` pure functions) is testable and clean.
- `toSegments()` adapter in `PlayerPage.tsx` is currently a no-op identity transform after the e56d961 field-name fix — see Minor #6.
- Placeholder deletions (`src/test/placeholders/useYouTubePlayer.ts` / `useSubtitleSync.ts`) completed — `frontend/src/test/placeholders/` directory no longer exists per T07's acceptance criterion. Build-time placeholder-import guard (T01) still passes because its `no-restricted-imports` pattern is path-based, not existence-based.
- Old `src/hooks/` + `src/components/` directories (the T06 critical issue) are confirmed removed at the filesystem level. `npm run lint` returns 0 errors, down from 3 at end of T06.
- **Architectural sin:** the auto-pause bug in Critical #1 collapses the hook's responsibility from "continuously detect segment end" to "only detect segment end if it happens to coincide with a word-index transition" — that's a responsibility violation against the spec invariant.

## QA Review

- `vitest run` → **45 passed / 6 files, 0 failed** ✓ (verified locally).
- `npm run lint` → **0 errors** ✓ (T06 follow-up cleanup is reflected).
- `npm run build` → **PASS, 226.79 kB bundle, 505 ms** ✓.
- Test coverage inventory:
  - `useYouTubePlayer.test.ts` 7 tests — lifecycle, late-onReady guard, null videoId. Good.
  - `useSubtitleSync.test.ts` ~17 tests across three describe blocks — binary-search boundaries, word search, stability. **Missing:** multi-segment time-advance test that exercises the stats-push path (Important #4).
  - `useAutoPause.test.ts` 8 tests — fire-once, reset-on-index-change, disabled guards. **Critical gap:** no test advances time from segment start past segment end; every test fixes `getCurrentTime` to return a near-end value from the first call, masking Critical #1.
  - `useKeyboardShortcuts.test.ts` 9 tests — key bindings + focus guard. Complete.
- **Sync-precision methodology judgment (load-bearing):** accept the simulated p95 as APPROVED_WITH_NOTES **only if Critical #1 is fixed** (because the simulation does not exercise the auto-pause path at all). The simulation faithfully models RAF → binary search → setState latency, which is the portion T07 rewrote. The IFrame clock jitter portion is unchanged from the old implementation (both use `player.getCurrentTime()`), so T07 did not introduce any new source of error there. The measured 4.2ms p95 has 24× headroom against the 100ms budget, so realistic IFrame jitter (typically 16–50ms p95 per browser display RAF cadence + IFrame postMessage) would still leave comfortable margin. **Mandatory follow-up: T09's ui-verifier pass MUST measure p95 against a real playable YouTube video and re-publish sentence + word p95 in `docs/ui-verification/T09-final.md`. That measurement, not T07's, is the project-level DoD gate.** T09's tasks.md already lists this; this review formalizes it as a non-skippable requirement — if T09's ui-verifier also reports "IFrame unavailable," T09 cannot close and either (a) the verifier env must be fixed to allow a real YouTube playback, or (b) a different representative video that plays in the env must be used.
- `window.__subtitleSyncStats` instrumentation (`useSubtitleSync.ts:30-36, 119-126, 148-161`) is correctly gated on `import.meta.env.DEV` so it won't leak into production bundles. Correct and well-scoped.

## Security Review

- No secrets introduced. No new network surface.
- `videoId` from `useParams()` flows into `useYouTubePlayer(videoId ?? null, PLAYER_CONTAINER_ID)` and the `YT.Player` constructor's `videoId` option. YouTube's own client sanitizes the ID; backend repo layer (T02) has already validated format against `^[A-Za-z0-9_-]{11}$` before the video ever reaches the DB, so a malicious route param cannot produce a non-YouTube ID that flows into the iframe.
- Keyboard shortcuts handler calls `e.preventDefault()` for the four matched keys and silently ignores the rest — no injection surface.
- `useSubtitleSync` writes `window.__subtitleSyncStats` only in DEV mode — no production leakage.
- No issues.

---

## Recommendations (priority order)

**Required before T07 can close (follow-up commits on `change/phase0-refactor`):**
1. **Fix `useAutoPause` RAF loop** (Critical #1). Convert to sustained RAF loop with deps `[player, segments, currentIndex, enabled]`. Add vitest case for time-advance scenario.
2. **Add multi-segment transition test for `useSubtitleSync`** (Important #4). Assert `window.__subtitleSyncStats` accumulates correct entries across boundaries.
3. **Resolve `useKeyboardShortcuts` signature drift** (Important #3). Either update spec to callback shape or refactor implementation to the `(player, segments, currentIndex)` signature. Pick one and sync.

**Required on T09 (baked into T09's gate by this review):**
4. **T09 ui-verifier MUST measure sentence + word p95 against a real playable YouTube video** (Important #2). If the current `dQw4w9WgXcW` test URL fails in the verifier env, either fix the env or substitute a known-playable video. `docs/ui-verification/T09-final.md` must contain raw samples + p95 from real IFrame `getCurrentTime()` returns, not simulated time. If IFrame continues to fail: T09 **does not close**, it loops back to investigate the playback-unavailable root cause.
5. **T09 ui-verifier must exercise auto-pause** in the real playback path (prove Critical #1's fix works against real IFrame timing).

**Deferred / Minor:**
6. Consolidate `Segment` / `SubtitleSegment` into one type in `types/subtitle.ts` (Minor #6, #8). Delete or simplify `toSegments()` adapter.
7. Narrow the `eslint-disable react-hooks/set-state-in-effect` in `useYouTubePlayer.ts` to `// eslint-disable-next-line` scope (Minor #7).
8. Expose `enabled` to caller if Phase 1 wants a toggle (Minor #5).

**Counts:** Critical 1 · Important 3 · Minor 4

**Bottom line:** the RAF + binary-search rewrite in `useSubtitleSync` is correct and the stats instrumentation is the right shape for ui-verifier consumption. But `useAutoPause` has a real functional bug: it does not sample continuously, because its `useEffect` lacks a dep array and schedules only a single RAF per render. Tests passed because every fixture starts with `getCurrentTime` already at `end - EPSILON` — real playback will not. This must be fixed before T07 can close. The simulated p95 is accepted conditionally; T09 inherits a non-skippable requirement to re-measure against real YouTube audio.

**Verdict: NEEDS_CHANGES**

---

## Re-review (2026-04-18)

**Commits verified:** `ce47da3` (C1+I4), `45157e6` (I3).

- **Critical #1 — useAutoPause RAF loop:** ✅ resolved. `useAutoPause.ts:31-61` now runs a sustained RAF loop inside a `useEffect` with deps `[player, segments, currentIndex, enabled]`; the loop reschedules via `requestAnimationFrame(tick)` until the fire-once guard trips, and cleans up via `cancelAnimationFrame`. New test `fires exactly once when time advances from seg.start to past seg.end across ≥10 RAF frames` (12 frames) would have failed against the old single-RAF-per-render impl because `getCurrentTime` only advances as called — only 1 call would occur before end-epsilon. Switch from `vi.runAllTimersAsync()` to `vi.advanceTimersByTime(16)` is correct: sustained RAF reschedules indefinitely, which hangs `runAllTimersAsync`; single-frame advancement is the right primitive.
- **Important #3 — signature drift:** ✅ resolved. `specs/sync.md:40-60` now documents the callback-object shape with per-callback semantics (`onTogglePlay`/`onPrev`/`onNext`/`onRepeat` + key mapping + input-focus suppression). Impl unchanged as agreed.
- **Important #4 — multi-segment transition test:** ✅ resolved. New `describe('useSubtitleSync — multi-segment transition stats')` block advances time across 3 segments with gaps (10 ticks) and asserts `transitions.length === 3` with `expected` matching each segment's `start`.

**Gates:** `npx vitest run` 47 passed · `npm run lint` 0 errors · `npm run build` PASS · scope tight (3 files in `ce47da3`, 1 in `45157e6`).

**Final verdict: APPROVED_WITH_NOTES.**

**Inherited requirement for T09:** T09's ui-verifier MUST measure sentence + word p95 against a real playable YouTube video (not simulated time) and re-publish in `docs/ui-verification/T09-final.md`; T07's simulated p95 is a lower-bound signal only.

