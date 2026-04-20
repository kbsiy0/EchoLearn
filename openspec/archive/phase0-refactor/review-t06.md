# Review: T06 — Frontend Router + directory reshuffle (Code)

**Date**: 2026-04-17
**Reviewed**: Code (commits `fe8006c..ec65e3e`)
**Verdict**: **NEEDS_CHANGES**

---

## Issues Found

### 🔴 Critical

1. **Old `frontend/src/components/` and `frontend/src/hooks/` directories were NOT deleted.**
   - Files present (and identical / near-identical to the new `features/` copies):
     - `src/components/{LoadingSpinner,PlayerControls,SubtitleLine,SubtitlePanel,URLInput,VideoPlayer}.tsx`
     - `src/hooks/{useSubtitleSync,useYouTubePlayer}.ts`
   - T06 spec `specs/frontend-router.md` invariant: *"Components live under a feature directory. No component resides directly in `frontend/src/` (aside from `App.tsx`)."*
   - Tasks.md T06: *"Components relocated under …"* and *"Existing hooks move (not rewritten) under …"* — move, not copy.
   - **Consequences:**
     - `npm run lint` reports **3 errors**, all from the orphaned `src/hooks/` files (`react-hooks/set-state-in-effect`, `react-hooks/refs`). T05 accepted these while the files were live; in T06 the files are now **dead code**, so the errors are no longer a "pre-existing live-code debt" — they are avoidable noise that a dead-code cleanup would eliminate.
     - Two live sources of truth for the same component set. Any future edit done in the wrong directory silently breaks behavior parity.
     - Violates the 200-line / single-source-of-truth hygiene the change is supposed to enforce.
   - **Evidence of purity:** `diff` between old `src/components/*` and new `features/*/components/*` shows only relative-import path changes. `diff` between old hooks and new hooks shows only whitespace + added `eslint-disable` comments. So deletion is safe — no unique content would be lost.
   - **Fix:** `git rm -r frontend/src/components frontend/src/hooks` (one commit), then re-run `npm run lint` — should report **0 errors**.

### 🟡 Medium

2. **`CORS`-facing `fetch(\`/api/subtitles/jobs/${jobId}\`)` in `useJobPolling.ts` uses a same-origin path, while the rest of the client uses absolute `http://localhost:8000/api/...`.**
   - `src/features/jobs/hooks/useJobPolling.ts:49` → `fetch(\`/api/subtitles/jobs/${jobId}\`)` (relative).
   - `src/api/subtitles.ts:3,19` → `const API_BASE = 'http://localhost:8000/api';`.
   - In dev via Vite on :5173 with **no proxy configured**, a relative `/api/...` request hits the Vite dev server, which has nothing to serve it; the job-polling request will fail in the real browser (Vite returns 404 for the HTML bundle or network error). Tests pass only because MSW intercepts `/api/...` path patterns regardless of origin.
   - This may be what the D1 ui-verifier "cache-hit only" path accidentally masks: cache-hit short-circuits to navigate without ever polling, so the broken polling URL never fires. A real pipeline run would poll → hit the broken endpoint → UI stays stuck on "submitting" until timeout.
   - **Fix:** Use the same `API_BASE` as the rest of the client (or call `pollJobStatus` from `api/subtitles.ts` — it exists and is unused). Add a vitest/contract test that asserts `fetch` was called with the expected absolute URL.

3. **D2 field-name regression has no contract test.**
   - The `youtube_url → url` fix in `f4f4b9a` confirms frontend/backend JSON contract drift went undetected across T05 → T06. Vitest covers `useJobPolling` polling semantics but nothing asserts `createJob` sends `{url: ...}` (not `{youtube_url: ...}`).
   - Without a contract test (MSW handler that rejects requests missing `url`), the same class of regression will slip in future. Recommend adding one in T07 or as a T06 follow-up patch before T09.

4. **ui-verifier "golden path" only exercised the cache-hit branch (D1).**
   - `docs/ui-verification/T06.md` explicitly uses `dQw4w9WgXcW` (already in DB) — this bypasses `createJob`'s non-cached response path, bypasses `useJobPolling`, and never renders `LoadingSpinner` with real progress updates.
   - Segments in the cache-hit test fixture are empty (`"字幕 (0 句)"`), so `SubtitlePanel` / word-highlighting was never visually verified either.
   - The broken relative polling URL (Medium #2) is directly hidden by this shortcut.
   - Comment in report claims `jNQXAC9IVRw` ("Me at the zoo") "is unavailable" — this is YouTube's first-ever upload and is almost certainly still accessible; more likely the pipeline (yt-dlp metadata probe or Whisper path) errored. Either way that failure mode wasn't investigated before falling back to the cached URL.
   - **Recommendation:** Defer a fresh-pipeline pass to T07 (which must run against real audio for sync p95 anyway) or T09 final. Do **not** block T07 on re-running T06 ui-verifier — but the above Critical + Medium #2 must be fixed before T07 starts, otherwise T07's ui-verifier will also fail on the polling URL.

### 🟢 Low

5. **`HomePage.tsx` duplicates `API_BASE` constant** (`const API_BASE = 'http://localhost:8000/api'` at line 16). The `api/` layer was supposed to own HTTP composition per the spec invariant "API calls go through `api/`". `GET /api/videos` should be wrapped in e.g. `api/videos.ts` and imported. Not blocking but drifts from the directory contract.

6. **`PlayerPage.tsx` error handling gap:** `getSubtitles(videoId)` 404 → caught by `.catch()` → sets generic `'無法載入字幕'`. No differentiation between "video doesn't exist" and "network error". Spec `PlayerPage contract` says "Invalid / not-yet-completed `videoId` → redirect to `/` with a user-visible message" — current code shows an inline error div instead of redirecting. Low because behavior is reasonable, just not spec-compliant.

7. **`App.tsx` does not specify a fallback route.** Spec `frontend-router.md` says "Unknown paths redirect to `/`"; current `<Routes>` has only `/` and `/watch/:videoId`, no `*` catch-all. React Router 6 falls back to rendering nothing for unmatched routes — user sees only the header. Add `<Route path="*" element={<Navigate to="/" replace />} />`.

8. **`useJobPolling` hard-codes default `intervalMs=1000`** — design calls for 1s so fine, but the T01 test contract suggested exposing the tunable. It is exposed; noting for completeness only.

9. **Dev workflow note — `.playwright-mcp/` is untracked.** Should be in `.gitignore` (likely ui-verifier artifact cache). Not T06's direct responsibility, but flagged.

---

## Architecture Review

- `App.tsx` at **25 lines** is clean routing composition — good.
- `HomePage.tsx` (131) and `PlayerPage.tsx` (171) are below 200. PlayerPage is dense but still comprehensible; some of its logic (auto-pause effect, keyboard shortcuts) is earmarked for T07 extraction into `useAutoPause` / `useKeyboardShortcuts`, so its current size is acceptable.
- `features/jobs/` vs `features/player/` split matches `design.md Section 5`. Component/hook placement is correct.
- **Sins:**
  - Old `src/components/` + `src/hooks/` not removed (Critical #1).
  - `HomePage.tsx` reaches directly to `fetch` for `/api/videos` instead of using an `api/` wrapper (Low #5).

## QA Review

- **Vitest: 27 passed / 0 failed** ✓
- `useJobPolling` tests now import from the real hook (`./useJobPolling`), placeholder deleted ✓
- ESLint placeholder guard **verified** — manually wrote a guard-trip file importing both `test/placeholders/useYouTubePlayer` and `test/placeholders/useJobPolling`; both rejected with `no-restricted-imports`. Guard survives even after T06 deleted the useJobPolling placeholder (the restricted-pattern is path-based, not module-existence-based).
- **`npm run lint`: 3 errors** — all in stale `src/hooks/` (Critical #1). Expected to drop to 0 after cleanup.
- **`npm run build`: PASS** (226 kB bundle, 485 ms) ✓
- **Feature hooks: pure moves** verified by `diff`. `useYouTubePlayer.ts` added only `eslint-disable react-hooks/refs` around the return object; `useSubtitleSync.ts` added only `eslint-disable react-hooks/set-state-in-effect` on one line. No behavior changes — T07's actual hook rewrite is still pending.
- **ui-verifier report:** PASS verdict recorded, 5 golden-path steps documented, 1 screenshot attached. Format is acceptable but shallow — no timing data (fine, T07 gate), limited cache-hit scope (D1, flagged as Medium #4).

## Security Review

- No secrets / credentials introduced.
- No new attack surface: routes are public-read, navigation uses `useNavigate()` (no `window.location` injection risk).
- `videoId` from `useParams()` is passed to `getSubtitles(videoId)` and `VideoPlayer`. Backend validates `^[A-Za-z0-9_-]{11}$` at the repo layer (T02) and returns 404 for malformed IDs (T05 follow-up) — so a malicious route param cannot reach the DB. Frontend currently shows inline error; a defense-in-depth check could regex-guard before issuing the fetch, but this is not critical.
- URL input goes through `extractVideoId()` in `lib/youtube.ts`; invalid URLs surface as "無效的 YouTube URL" before the API call. Acceptable.

## Key Findings on the User's Two Deviation Questions

**D1 (cache-hit-only ui-verifier):** Report is **not sufficient** for a "use prior behavior unchanged" claim — the fresh-pipeline path was never exercised. Combined with the unrelated polling-URL bug (Medium #2), the cache-hit shortcut likely **masked a real breakage**. However re-running ui-verifier on T06 alone is wasted effort: T07 must run real-pipeline smoke anyway for p95 gate. Fix the polling-URL bug + dead-code cleanup, then let T07 prove the full path.

**D2 (field-name bug):** The fix is correct. The **absence of a contract test** is the real finding. Add an MSW-based vitest assertion that `createJob()` posts `{url: ...}`. Scope: Medium. Do not block T07 start, but add it as a T06 follow-up patch or T07 parallel task.

**Hook rewrite check:** Confirmed **no hook was rewritten** in T06. `useSubtitleSync` and `useYouTubePlayer` are pure moves + eslint-disable comments. T07's RAF / binary-search rewrite is still pending. Good.

## Recommendations

**Follow-up patch required before T07 starts:**
1. `git rm -r frontend/src/components frontend/src/hooks` — delete dead directories. Re-verify `npm run lint` returns 0 errors.
2. Fix `useJobPolling.ts` URL to use absolute `http://localhost:8000/api/...` (or import `pollJobStatus` from `api/subtitles.ts`).
3. Add vitest contract test: `createJob('url')` issues `POST` with JSON body containing key `url` (not `youtube_url`) — MSW reject-handler style.

**Deferred to later tasks (accept-as-notes):**
4. `HomePage.tsx`: extract `/api/videos` fetch into `api/videos.ts` (T07 or T08 hygiene).
5. `App.tsx`: add `<Route path="*" element={<Navigate to="/" replace />} />`.
6. `PlayerPage.tsx`: differentiate 404 from network error; redirect on `videoId` invalid per spec.
7. Fresh-pipeline (non-cached) ui-verifier pass: let T07 handle this in its real-audio p95 run.

**Counts:** Critical 1 · Medium 3 · Low 5

**Bottom line:** T06's directory reshuffle is 90% correct but the dead-directory deletion was skipped, which breaks the "no component outside features/" invariant and leaves lint errors that would otherwise be gone. Combined with the polling-URL bug hidden by the cache-hit ui-verifier shortcut, I cannot in good conscience mark T06 complete. Fix items 1–3 (small, mechanical) and T07 can start.
