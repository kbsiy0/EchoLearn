# Capability — Frontend Router

## Responsibilities
- Provide stable URLs for the two Phase 0 views: HomePage (`/`) and PlayerPage (`/watch/:videoId`).
- Keep `App.tsx` as a thin composition root (< 150 lines) — routing only, no domain logic.
- Host the directory layout under which future Phase 1+ features will slot in (`features/player/`, `features/jobs/`).

## Public interfaces

### Routes

| Path               | Component      | Purpose                                              |
|--------------------|----------------|------------------------------------------------------|
| `/`                | `HomePage`     | URL input + history list of processed videos         |
| `/watch/:videoId`  | `PlayerPage`   | Player + subtitle panel for the given `videoId`      |

Unknown paths redirect to `/`.

### Directory layout

```
frontend/src/
  App.tsx                              (BrowserRouter + <Routes>, nothing else)
  routes/
    HomePage.tsx
    PlayerPage.tsx
  features/
    player/
      components/                      (YouTubePlayer, SubtitlePanel, SentenceRow, ...)
      hooks/                           (useYouTubePlayer, useSubtitleSync, useAutoPause, useKeyboardShortcuts)
    jobs/
      components/                      (JobProgress, ...)
      hooks/                           (useJobPolling, ...)
  api/                                 (fetch wrappers per endpoint)
  lib/                                 (youtube URL parsing, time utilities)
  types/                               (shared TS types mirroring backend Pydantic)
  test/setup.ts                        (MSW init)
```

### HomePage contract
- Input: YouTube URL text field + submit button.
- On submit: POST to `/api/subtitles/jobs`; render `<JobProgress>` tracking the returned `job_id`; on completion, navigate to `/watch/:videoId`.
- On mount: GET `/api/videos`; render a list of past videos with clickable rows linking to `/watch/:videoId`.

### PlayerPage contract
- Reads `videoId` from the route param.
- Fetches `GET /api/subtitles/{video_id}`; renders loading state, then renders the player + subtitle panel composing the four player hooks.
- Invalid / not-yet-completed `videoId` → redirect to `/` with a user-visible message.

## Invariants
- **App.tsx is routing only.** No state management beyond `<BrowserRouter>` and `<Routes>`. Line count < 150.
- **Components live under a feature directory.** No component resides directly in `frontend/src/` (aside from `App.tsx`).
- **API calls go through `api/`.** No component fetches directly; hooks in `features/*/hooks/` call the `api/` wrappers.
- **Types mirror backend.** Shared TS types in `types/` match Pydantic shapes from `jobs-api` spec.
- **Behavior parity at the reshuffle step.** T06 must not change any user-visible behavior; only structure.

## Non-goals
- Nested routes for subtitle detail views, flashcards, or library management (Phase 1+).
- Route-level code splitting / lazy loading (Phase 1+).
- Server-side rendering.
- Persisting UI state across reloads beyond what the URL carries.
