# T12 UI Verification Report — PlayerPage Segment-Streaming Rewrite

- **Date:** 2026-04-26
- **Verdict: PASS**
- **Commit verified:** `9e8cc08`
- **Branch:** `change/phase1b-segment-streaming`

## Environment

| Component | Status |
|---|---|
| Backend (FastAPI :8000) | Started for this session; 275 pytest PASS |
| Frontend (Vite :5173) | Started for this session; 146 vitest PASS |
| Playwright browser | Firefox 148.0.2 (npx playwright@1.59.1) |
| Test video — fresh processing | `jNQXAC9IVRw` ("Me at the zoo", 19s) |
| Test video — cache-hit | same, re-submitted after first run completed |
| Failed-state video | `NOTAVAILX99` (11-char ID, VIDEO_UNAVAILABLE) |

## Golden Path

- [x] Step 1: Home page loads — URL input present, empty history (fresh DB). Screenshot: `screenshots/golden/00-home.png`
- [x] Step 2: Submit `jNQXAC9IVRw` URL → navigate to `/watch/jNQXAC9IVRw` in **96–109ms** (threshold < 200ms). Screenshot: `screenshots/golden/01-player-initial.png`
- [x] Step 3: `ProcessingPlaceholder` renders with progress bar and "處理字幕中 (0%)" text. Screenshot: `screenshots/golden/02-processing-empty.png`
- [x] Step 4: Processing completes; full `CompletedLayout` mounts — VideoPlayer + subtitle panel ("字幕 (3 句)") + `PlayerControls`. Screenshot: `screenshots/golden/04-completed-player.png`
- [x] Step 5: Cache-hit path — second navigation immediately shows completed player in **231ms**. Screenshot: `screenshots/golden/05-cache-hit-completed.png`

## Edge Cases

- [x] **TTFS event fires exactly once on fresh submit:** `window.__ttfsEvents.length === 1`, `t = 10484` (finite). PASS.
- [x] **TTFS does NOT fire on cache-hit:** `window.__ttfsOnCacheHit.length === 0`. PASS.
- [x] **TTFS does NOT fire on failed state:** `window.__ttfsOnFailed.length === 0`. PASS.
- [x] **Mount-once invariant:** `MutationObserver` recorded exactly **1** `[data-testid="video-player"]` insertion (`count=1, t=175ms`). No spurious re-mounts over 5s window. PASS.
- [x] **Sticky-completed guard (cache-hit path):** `ProcessingPlaceholder` NOT shown on re-navigation to completed video; `cacheHitShowsProcessing=false`. PASS.
- [x] **Failed state UI (VIDEO_UNAVAILABLE):** `h3="處理失敗"`, gray error message "內部錯誤", `回首頁` button visible. Clicking navigates to `/`. Screenshot: `screenshots/failed/failed-state-full.png`. PASS.
- [x] **No VideoPlayer on failed state:** `[data-testid="video-player"]` absent from DOM. PASS.
- [ ] **VIDEO_TOO_LONG failed state:** NOT triggered — yt-dlp in this env (without JS runtime) can only access 3 specific videos, all ≤ 7 min. The error-mode rendering was validated via `VIDEO_UNAVAILABLE` instead. `_SAFE_MESSAGES["VIDEO_TOO_LONG"] = "影片超過 20 分鐘上限"` covered by backend unit tests only.
- [ ] **Partial-segment screenshot:** NOT captured — the 19s video processes faster than Playwright's polling interval. Backend logs confirm chunk streaming ran (`chunks_jNQXAC9IVRw/chunk_00.mp3`). TTFS event firing at 10484ms confirms the first-segment code path executed.

## Quantitative Measurements

### Navigation Immediacy

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| POST → navigate to /watch/ | 96–109ms | < 200ms | PASS |
| Cache-hit player mount | 231ms | < 2s | PASS |

### TTFS (Time-to-First-Segment)

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| TTFS event count (fresh submit) | 1 | exactly 1 | PASS |
| TTFS `t` value | 10484ms (`performance.now()`) | finite | PASS |
| TTFS on cache-hit | 0 fires | 0 | PASS |
| TTFS on failed state | 0 fires | 0 | PASS |

TTFS ~10.5s for a 19s video. Spec target p50 ≤ 15s for a 20-min video — proportionally well within budget.

### Mount-Once Invariant

| Metric | Value | Expected | Pass? |
|---|---|---|---|
| VideoPlayer DOM insertions on page load | 1 | 1 | PASS |

### Sync Precision (Simulated — IFrame not playable in headless Firefox)

Applied the same binary-search simulation as T07, using real word/segment timestamps from `jNQXAC9IVRw` API response (3 sentences, 21 words):

| Metric | Value | Threshold | Pass? |
|---|---|---|---|
| Sentence highlight p95 | 3.3ms | ≤ 100ms | PASS |
| Sentence highlight max | 3.3ms | — | — |
| Word highlight p95 | 16.5ms | ≤ 150ms | PASS |
| Word highlight max | 16.5ms | — | — |

`window.__subtitleSyncStats` is initialized correctly on `?measure=1` pages (`{sentenceTransitions: [], wordTransitions: []}`). The binary-search algorithm is unchanged from T07-verified code.

## Regressions Checked

| Previous Report | Scope Overlap | Result |
|---|---|---|
| T06 — router/HomePage | navigation | PASS — routes verified in this run |
| T07 — sync hooks | useSubtitleSync algorithm | PASS — 146 vitest green |
| T09 — resilience | useSubtitleSync error recovery | PASS — resilience.test.ts passes |
| Phase 1a — loop+speed | PlayerControls, loop flag | PASS — controls visible in player; vitest PASS |

Backend: **275 pytest PASS**. Frontend: **146 vitest PASS**.

## Console Errors

8 console errors — all YouTube SameSite cookie warnings from `youtube.com` IFrame origin. These are headless-Firefox-specific (no cookie jar for third-party frames), pre-exist this branch, and do not affect EchoLearn functionality. Zero EchoLearn-originated JS errors.

## Notes

1. **Font rendering in headless Firefox:** Chinese text renders as square boxes in screenshots due to absent CJK fonts in CI. DOM `.textContent` was verified programmatically — all Chinese strings correct.
2. **yt-dlp JS runtime:** yt-dlp 2026.03.17 requires deno/node for modern YouTube formats; only 3 videos were accessible in this environment. The 19s video is sufficient for all critical T12 code paths.
3. **Backend PATH:** uvicorn must be started with the venv `bin/` on PATH for `shutil.which("yt-dlp")` to resolve.
4. **Sticky-completed guard (polling-revert scenario):** Covered by vitest `PlayerPage.streaming.test.tsx` — `test_sticky_completed_guards_against_later_processing` and `test_sticky_completed_preserves_playback_position_on_resubmit_downgrade`. Accepted per task spec.

## Verdict

**PASS** — All T12 invariants hold: immediate navigation (96ms), TTFS fires once (10484ms, finite), VideoPlayer mounts exactly once, cache-hit skips processing, failed-state shows 回首頁 and navigates back; 146 vitest + 275 pytest all green.
