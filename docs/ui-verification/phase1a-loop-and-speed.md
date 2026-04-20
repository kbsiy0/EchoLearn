# Phase 1a Loop & Speed — UI Verification Report

Date: 2026-04-20
Branch: change/phase1a-loop-and-speed
Commit: 0cd9567 — `fix(player): guard usePlaybackRate against uninitialised IFrame API`
Reviewer: ui-verifier agent (Playwright MCP)

## Verdict: **PASS**

PlayerPage loads cleanly after the `usePlaybackRate` readiness guard; loop holds a segment through ≥18 s of continuous playback, speed control works via click + `[` / `]` + survives refresh, `?measure=1` disables loop seek-back even when the button is visually pressed, and no file exceeds the 200-line cap.

## Environment

- Backend: uvicorn on :8000 (`/docs` → 200)
- Frontend: Vite dev on :5173 (`/` → 200)
- Test video: `L_jWHffIx5E` "Smash Mouth - All Star" (20 segments, cached)
- Browser: Chromium via MCP Playwright

## Metric results

| # | Metric | Result | Evidence |
|---|--------|--------|----------|
| 1 | PlayerPage loads without crashing | **PASS** | `screenshots/phase1a/01-player-page-loaded.png` |
| 2 | Loop holds single segment across cycles | **PASS** | `screenshots/phase1a/02-loop-active.png` |
| 3 | Speed buttons + `[` / `]` keys + localStorage persistence | **PASS** | `screenshots/phase1a/03-speed-persistence.png` |
| 4 | `?measure=1` disables loop regardless of button state | **PASS** | `screenshots/phase1a/04-measure-mode.png` |
| 5 | 200-line scan (prod code) | **PASS** | no file exceeds 200 lines |

## Per-metric detail

### Metric 1 — PlayerPage loads without crashing

- Navigated to `http://localhost:5173/watch/L_jWHffIx5E`.
- Console after load + 2 s idle: `0 errors, 2 warnings`. The warnings are YouTube IFrame cookie warnings, not application errors.
- Zero occurrences of `TypeError: player.setPlaybackRate is not a function` (the symptom of the previous FAIL).
- Accessibility snapshot shows all required controls rendered: `上一句`, `重複`, `循環`, `播放`, `下一句`, five speed buttons (`0.5×` … `1.5×`), and the `第 0/20 句` counter, plus the subtitle panel with "字幕 (20 句)" and all 20 segments.
- Evidence: `01-player-page-loaded.png`.

### Metric 2 — Loop sustained

- Clicked the `0:55` segment → counter jumped to `第 7/20 句`.
- Clicked `循環` → `aria-pressed=true`, blue styling; then clicked `播放`.
- Sampled the counter at t+8 s and t+18 s of continuous playback (button showed `暫停` throughout): both samples returned `第 7/20 句`.
- Counter stability across 18+ s of real playback means the loop seek-back is working — segment 7 on this song is only ~15 s long, so the loop has cycled back at least once.
- Sanity check: after disabling loop (button unpressed) the counter advanced to `第 8/20 句` within seconds, confirming loop was the cause of the hold, not a paused player.
- Evidence: `02-loop-active.png`.

### Metric 3 — Speed + keyboard + persistence

Performed in sequence with `localStorage.echolearn.playback_rate` initially cleared:

1. Click `1.25×` → `aria-pressed=true`, `localStorage = "1.25"`.
2. Click `1×` → `aria-pressed=true` on `1×`, `localStorage = "1"`.
3. Press `]` → `1.25×` now pressed, `localStorage = "1.25"`.
4. Press `[` → `1×` now pressed, `localStorage = "1"`.
5. Click `0.75×` → `localStorage = "0.75"`; reloaded page; after reload, `0.75×` had `aria-pressed=true` and `localStorage` still `"0.75"`.

All five sub-assertions held. Evidence: `03-speed-persistence.png` (bottom bar shows `0.75×` highlighted blue after a hard refresh).

### Metric 4 — `?measure=1` disables loop

- Navigated to `http://localhost:5173/watch/L_jWHffIx5E?measure=1` — page loaded, `0 errors, 2 warnings` (same harmless YT warnings).
- Clicked `循環` (button visually pressed, `aria-pressed=true`) and then `播放`.
- Counter progression under measure mode while 循環 was pressed and playback running:
  - t+0: `第 1/20 句`
  - t+23 s: `第 5/20 句`
  - t+38 s: `第 7/20 句`
  - t+53 s (screenshot): `第 8/20 句`
- Counter advanced monotonically across **≥ 7 segment transitions** despite the loop button being pressed → `computePlaybackFlags(measure=true)` is correctly forcing `loopEnabled=false`. No seek-back observed.
- Evidence: `04-measure-mode.png` (循環 blue-pressed, `暫停` active, counter `第 8/20 句`).

### Metric 5 — 200-line scan

Ran the specified two `find … awk` commands against `frontend/src` (excluding tests) and `backend/app`. Both returned zero output. No production file exceeds 200 lines.

## Quality gates

- `npx vitest run`: **100 / 100 PASS** (16 test files, 4.34 s)
- `npm run build`: **success** — `dist/assets/index-AJIJjSuv.js 230.42 kB` (gzip 73.63 kB), 54 modules, 524 ms
- `python -m pytest`: **169 / 169 PASS** (2.71 s)
- `npm run lint`: **clean** (no output from eslint)

## Overall

All five metrics PASS and all four quality gates are green. The `usePlaybackRate` readiness guard has resolved the prior crash; loop, speed, keyboard shortcuts, persistence, and `?measure=1` gating all behave per spec.

**Ready for integrator.**

## Screenshots

- `docs/ui-verification/screenshots/phase1a/01-player-page-loaded.png`
- `docs/ui-verification/screenshots/phase1a/02-loop-active.png`
- `docs/ui-verification/screenshots/phase1a/03-speed-persistence.png`
- `docs/ui-verification/screenshots/phase1a/04-measure-mode.png`
