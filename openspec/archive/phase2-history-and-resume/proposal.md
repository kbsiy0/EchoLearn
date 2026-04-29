# Phase 2 — Video History and Learning Progress Recovery

**Status:** Brainstorm output (this doc) — spec-writer will produce `design.md`, `tasks.md`, and `specs/` from here.

## What this change is

Two coupled features:

1. **Video history surfacing** — HomePage's "最近觀看" list re-sorts so videos with active progress float to the top, each card carries a progress bar showing `last_played_sec / duration_sec`, and a "重置進度" affordance lets the user clear progress on a card without deleting the cached subtitles.

2. **Learning progress recovery** — When the user navigates back to `/watch/:videoId`, the player auto-resumes to last-played position with the previously-used playback rate and loop-toggle state, and a 5-second toast confirms the restoration with an escape "從頭播" button.

## Why

CLAUDE.md roadmap defines Phase 2 as "影片歷史、學習進度恢復". The current HomePage already lists past videos but sorts by creation date and offers no resume mechanism — re-opening a partially-watched video starts from `t=0` with default speed/loop. This Phase makes the list useful for resumption and persists per-video player state across sessions.

## Decisions locked during brainstorming

The following six decisions were settled by user choice during brainstorming. spec-writer must honor them.

| # | Decision | Resolved |
|---|---|---|
| 1 | What "learning progress" means | last_played_sec + last_segment_idx + playback_rate + loop_enabled (per-video state, not per-segment marks — those are Phase 3) |
| 2 | Where progress lives | Server SQLite (`video_progress` table) — single source of truth, syncs across browsers on the same instance |
| 3 | Resume behavior on click | Auto-resume + 5s toast "已恢復到 1:07 (第 18 句)" + 「從頭播」escape button |
| 4 | History list UX | Re-sort by `progress.updated_at DESC` (with-progress first), progress bar on each card, per-card "重置進度" button |
| 5 | Progress write timing | Event-driven: pause / seek / rate-change / loop-toggle / visibilitychange=hidden / unmount, with 1s debounce |
| 6 | "重置進度" semantics | **Soft delete** — only clears `video_progress` row; `videos` / `segments` / `jobs` / audio file all preserved (re-submit URL hits cache instantly) |

## Architecture summary

**New files**:
- `backend/app/repositories/progress_repo.py`
- `backend/app/routers/progress.py`
- `frontend/src/api/progress.ts`
- `frontend/src/features/player/hooks/useVideoProgress.ts`
- `frontend/src/features/player/components/ResumeToast.tsx`
- `frontend/src/features/jobs/components/VideoCard.tsx`

**Modified files**:
- `backend/app/db/schema.sql` — add `video_progress` table + index
- `backend/app/repositories/videos_repo.py` — `list_videos()` LEFT JOIN's progress + custom ORDER BY
- `backend/app/routers/videos.py` — wire the new shape through
- `backend/app/models/schemas.py` — `VideoProgress` model + nest into `VideoSummary`
- `backend/app/main.py` — register the new progress router
- `frontend/src/types/subtitle.ts` — extend `VideoSummary` with `progress: VideoProgress | null`
- `frontend/src/routes/HomePage.tsx` — replace inline `<li>` markup with `<VideoCard>`, wire reset callback
- `frontend/src/features/player/components/CompletedLayout.tsx` — call `useVideoProgress`, run resume effect, mount `ResumeToast`, propagate save events from rate/loop/pause/seek

**No changes**: Phase 1b streaming pipeline, `useSubtitleStream`, `VideoPlayer`, `SubtitlePanel`, `useSubtitleSync` — all stay untouched.

## Data model

```sql
CREATE TABLE video_progress (
  video_id          TEXT PRIMARY KEY,
  last_played_sec   REAL NOT NULL,
  last_segment_idx  INTEGER NOT NULL,
  playback_rate     REAL NOT NULL,
  loop_enabled      INTEGER NOT NULL,        -- 0 or 1
  updated_at        TEXT NOT NULL,           -- ISO; doubles as last_played_at for sort
  FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);
CREATE INDEX idx_progress_updated_at ON video_progress(updated_at DESC);
```

```python
class VideoProgress(BaseModel):
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool
    updated_at: str

class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str
    progress: VideoProgress | None
```

## API surface

```
GET    /api/videos/{video_id}/progress
  200 → VideoProgress
  404 → { error_code: "NOT_FOUND" }     when never played

PUT    /api/videos/{video_id}/progress
  body  : VideoProgressIn (no updated_at — server stamps)
  204
  400 → { error_code: "VALIDATION_ERROR" }   when rate ∉ [0.5, 2.0] or sec < 0
                                             (via custom RequestValidationError handler)

DELETE /api/videos/{video_id}/progress
  204                                          idempotent

GET    /api/videos                              # MODIFIED
  200 → VideoSummary[] with progress field, sorted (with-progress first by updated_at, then by created_at)
```

## Edge cases

- `last_played_sec > duration_sec` (re-transcribe shrunk duration): backend `GET` clamps to duration before returning
- `last_segment_idx ≥ len(segments)` (re-transcribe gave fewer segments): frontend `CompletedLayout` ignores stored idx and re-derives from `last_played_sec` via the same binary search `useSubtitleSync` uses
- `playback_rate ∉ [0.5, 2.0]` (DB corruption / older client): frontend clamps before applying
- `recomputeSegmentIdx` finds nothing (e.g. all segments before 0): fall back to idx 0, no toast

## Error-handling philosophy

Progress is "best-effort enrichment, never blocks the player." All silent except the user-initiated DELETE, which surfaces inline error on failure.

| Failure | Response |
|---|---|
| GET progress 5xx / network | Treat as null, no toast, no error UI |
| PUT progress (any failure) | Silent — `console.warn` only; next save overwrites |
| DELETE progress | Inline red text on the affected `VideoCard` |
| Player not ready when progress arrives | Wait for `isReady` before applying; no race |

## Acceptance gates (high-level — spec-writer expands)

- TTFR (time-to-first-resume): cache-hit + has-progress, click → seek complete ≤ 500ms p95
- Progress write latency: pause → backend received PUT ≤ 1.5s (1s debounce + write)
- Crash survivability: tab closed within 1s of pause, next session resumes within ±5s of pause point
- Sync precision unchanged: existing sentence p95 ≤ 100ms / word p95 ≤ 150ms (regression check)
- Player mount-once invariant unchanged

## Out of scope

- **Per-segment marks ("I've practiced this sentence")** — this overlaps Phase 3's 句子收藏/字卡; defer
- **Multi-device sync** — current architecture is single-instance; no auth, no user model
- **Search / filter on history list** — YAGNI for first cut; small N expected for personal use
- **Watch-time analytics / stats** — out of scope; would need a separate stats table
- **Hard delete videos** ("delete this video and its cached subtitles") — out of scope; soft-delete-only per Decision #6
- **Resume across same-window tabs in real-time** — server-side single-source-of-truth gives eventual consistency on next mount; no broadcast
- **Bookmarks / chapters** — Phase 3+

## Risks

| Risk | Mitigation |
|---|---|
| `useVideoProgress` race with `useYouTubePlayer.isReady` | gated `useEffect` with `restoredRef` ensures resume runs exactly once after both `loaded && isReady` |
| Debounced PUT swallowed when tab closes mid-debounce | hook listens to `visibilitychange=hidden` + `beforeunload` and force-flushes |
| Rate / loop change being persisted before `isReady` (initial render) | save calls gated by `isReady` to avoid writing default state over real progress on first mount |
| Toast obscuring player controls on small viewports | toast positioned bottom-right with `pointer-events-none` on backdrop; auto-dismiss 5s |

## Spec-writer handoff

This proposal locks the public-facing decisions and the data model. spec-writer should produce:

- `design.md` — full architectural detail (sections per file, render trees, sequence diagrams for resume + write paths)
- `tasks.md` — TDD-shaped task breakdown (likely 8–10 tasks: schema migration, repo, router, schemas update, list_videos modification, useVideoProgress hook, ResumeToast, VideoCard, HomePage integration, PlayerPage/CompletedLayout integration, integrator gate)
- `specs/` — capability specs:
  - `progress-api.md` (GET/PUT/DELETE behavioral table)
  - `video-history-ui.md` (HomePage list ordering, VideoCard contract, reset flow)
  - `player-resume.md` (CompletedLayout resume effect, ResumeToast contract, write-event mapping)

## Open questions for spec-writer

- Should the GET /api/videos response stay backward-compatible (always include `progress` field, possibly null) or version the endpoint? **Recommendation: stay backward-compatible — the existing single frontend caller can handle the new shape without versioning.**
- Toast 5-second auto-dismiss: should it pause the timer when player is paused, or always 5s wall-clock? **Recommendation: always 5s wall-clock — pausing the timer adds complexity for marginal value.**
- Default `playback_rate` and `loop_enabled` for first PUT: are these recorded on first play (auto-saved on `isReady`) or only when user explicitly changes them? **Recommendation: only record after user-initiated change — avoids polluting progress with defaults that might never have been "intentional".**
