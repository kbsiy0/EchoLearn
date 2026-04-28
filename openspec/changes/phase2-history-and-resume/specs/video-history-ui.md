# Capability — Video History UI (Phase 2)

## Responsibilities

- Render the HomePage's "最近觀看" list as a sequence of `<VideoCard>`
  components, one per video returned from `GET /api/videos`.
- Sort the list with-progress-first (by `progress.updated_at` DESC), then
  without-progress (by `created_at` DESC), so that videos the user is
  currently learning float to the top.
- Render a per-card progress bar based on `last_played_sec / duration_sec`,
  clamped to `[0, 1]`.
- Provide a per-card "重置進度" button that calls `DELETE
  /api/videos/{video_id}/progress` and refetches the list to reflect the
  new state.
- Isolate card-click navigation from reset-button click via
  `e.stopPropagation()`.
- Surface inline error UI on the affected card when reset fails; never
  block the rest of the list.

## Public interfaces

### List endpoint shape

```ts
// frontend/src/types/subtitle.ts

export interface VideoProgress {
  last_played_sec: number;
  last_segment_idx: number;
  playback_rate: number;
  loop_enabled: boolean;
  updated_at: string;
}

export interface VideoSummary {
  video_id: string;
  title: string;
  duration_sec: number;
  created_at: string;
  progress: VideoProgress | null;    // NEW; null when never played
}
```

### `VideoCard` component

```tsx
// frontend/src/features/jobs/components/VideoCard.tsx

interface VideoCardProps {
  summary: VideoSummary;
  onClick: (videoId: string) => void;
  onReset: (videoId: string) => Promise<void>;
}

export function VideoCard(props: VideoCardProps): JSX.Element;
```

### `HomePage` integration

`HomePage` continues to fetch `GET /api/videos` once on mount. It maps the
result to `<VideoCard>` instances. Card-click delegates to
`navigate('/watch/${id}')`. Card-reset delegates to a local handler that
calls `deleteProgress(id)` and refetches the list.

## Behavior scenarios

### List shape: `progress` field present per video

GIVEN a Phase 2 client has loaded `GET /api/videos`
WHEN the response is parsed
THEN every element of the array has a `progress` field
AND the value is either a fully-populated `VideoProgress` object (when a
row exists) or `null` (when never played).

### List shape: backward-compat for Phase 0 / 1b consumers

GIVEN the response of `GET /api/videos`
WHEN a consumer reads only the keys `video_id`, `title`, `duration_sec`,
`created_at`
THEN those values are byte-equal to the equivalent Phase 0 / Phase 1b
response for the same DB state.

### Sort: with-progress before without-progress

GIVEN three videos:
- Alpha: `created_at = 2026-04-25T10:00Z`, no progress
- Beta: `created_at = 2026-04-25T09:00Z`, `progress.updated_at =
  2026-04-26T08:00Z`
- Gamma: `created_at = 2026-04-25T11:00Z`, `progress.updated_at =
  2026-04-25T15:00Z`
WHEN the client calls `GET /api/videos`
THEN the response order is **Beta → Gamma → Alpha**.

### Sort: with-progress group sorted by progress.updated_at DESC

GIVEN three videos all with progress, ordered by `progress.updated_at`
T3 > T2 > T1
WHEN the client renders the list
THEN the DOM order from top to bottom is the video at T3, then T2, then T1.

### Sort: without-progress group sorted by created_at DESC

GIVEN three videos none with progress, ordered by `created_at` C3 > C2 >
C1
WHEN the client renders the list
THEN the DOM order matches the existing Phase 0 / Phase 1b ordering: C3,
C2, C1.

### Sort: only one video, no progress

GIVEN one video with no progress
WHEN the client renders the list
THEN that single video is rendered.

### Empty state

GIVEN `GET /api/videos` returns `[]`
WHEN the client renders the HomePage
THEN no `<VideoCard>` is rendered
AND the empty-state copy `"貼上 YouTube URL 開始學習"` is visible.

### VideoCard: render without progress

GIVEN `summary.progress === null`
WHEN `VideoCard` is rendered
THEN the title is rendered (truncated if long)
AND the duration is rendered as `"<m>分<s>秒"` (e.g., `"3分27秒"` for 207s)
AND the created_at date is rendered in zh-TW locale
AND no progress bar is rendered
AND no "重置進度" button is rendered.

### VideoCard: render with progress

GIVEN `summary.progress = { last_played_sec: 60, ..., updated_at: ... }`
AND `summary.duration_sec = 180`
WHEN `VideoCard` is rendered
THEN a progress bar is rendered with width approximately `33.3%`
AND a percentage label reflects the same ratio (e.g., `"33%"`)
AND a "重置進度" button is rendered.

### VideoCard: progress bar clamped above 100%

GIVEN `last_played_sec = 300`, `duration_sec = 180` (stale value beyond
backend clamp)
WHEN the card renders
THEN the progress bar's width is `100%` (clamped to 1.0)
AND the percentage label shows `"100%"`.

### VideoCard: progress bar clamped below 0%

GIVEN `last_played_sec = -5` (defensive; should never happen due to
backend validation)
WHEN the card renders
THEN the progress bar's width is `0%`
AND the percentage label shows `"0%"`.

### VideoCard: click navigates via onClick

GIVEN any `VideoCard` rendered with `onClick=spyA`
WHEN the user clicks any non-reset region of the card
THEN `spyA(summary.video_id)` is called exactly once.

### VideoCard: navigation works regardless of progress presence

GIVEN a card rendered with `progress=null`
WHEN the user clicks the card
THEN `onClick(summary.video_id)` is called (the lack of progress does not
disable the click).

GIVEN a card rendered with `progress` populated
WHEN the user clicks any non-reset region
THEN `onClick(summary.video_id)` is called.

### VideoCard: click on "重置進度" does NOT navigate

GIVEN a card rendered with `onClick=spyA, onReset=spyB` and a populated
`progress`
WHEN the user clicks the "重置進度" button
THEN `spyB(summary.video_id)` is called once
AND `spyA` is NOT called (the reset handler invokes `e.stopPropagation()`).

### VideoCard: reset button has type="button"

GIVEN a card rendered inside any nested form context
WHEN the reset button's HTML attributes are inspected
THEN it has `type="button"` (defensive against accidental form submission).

### VideoCard: inline error on reset failure

GIVEN a card whose `onReset` returns a rejected promise
WHEN the user clicks "重置進度"
THEN `onReset` is called once
AND a small inline error message (e.g., `"重置失敗，請稍後再試"`) is
rendered on the card
AND the card remains clickable for navigation.

### VideoCard: inline error clears on successful retry

GIVEN a card showing a previous reset error
WHEN the user clicks "重置進度" again and `onReset` resolves
THEN the error message is removed from the DOM.

### VideoCard: reset failure does not affect other cards

GIVEN a list of three cards rendered with three independent `onReset`
handlers
WHEN the user resets card 1 and that fails
THEN cards 2 and 3 do NOT render the error message
AND clicking cards 2 and 3 still navigates normally.

### HomePage: maps videos to VideoCards

GIVEN `GET /api/videos` returns three entries
WHEN HomePage renders
THEN exactly three `<VideoCard>` instances are mounted
AND each receives the corresponding `summary` prop.

### HomePage: clicking a card navigates to /watch/:id

GIVEN HomePage with three cards
WHEN the user clicks the second card
THEN `useNavigate` is called with `/watch/${summary[1].video_id}`.

### HomePage: reset triggers DELETE then refetch

GIVEN HomePage with three cards (one with progress)
WHEN the user clicks "重置進度" on the with-progress card
THEN `DELETE /api/videos/${id}/progress` is called once
AND on success, `GET /api/videos` is called a second time (refetch)
AND the new list replaces the old in component state.

### HomePage: after reset, the affected card has progress=null

GIVEN HomePage where Beta has progress and Gamma has progress (per the
example above) and Alpha does not
WHEN the user resets Beta
AND the refetch returns Alpha (T_A.created_at), Beta (progress=null),
Gamma (still has progress)
THEN the new render shows the order **Gamma → (Alpha vs Beta by
created_at)**
AND Beta's card no longer renders the progress bar or the reset button.

### HomePage: reset failure does not refetch

GIVEN HomePage and a card click that fails
WHEN `DELETE /api/videos/${id}/progress` rejects
THEN `GET /api/videos` is NOT called a second time
AND the local `videos` state is unchanged
AND the affected card surfaces the inline error
AND other cards are untouched.

### HomePage: list-fetch error is silent

GIVEN the initial mount of HomePage
WHEN `GET /api/videos` fails (network or 5xx)
THEN no error is rendered above the list (existing Phase 0 behavior
preserved)
AND the empty-state copy is shown
AND the URL input continues to work for new submissions.

### HomePage: cache-hit submit path preserves Phase 1b behavior

GIVEN the user submits a URL whose `video_id` already has cached subtitles
WHEN `createJob` resolves
THEN HomePage navigates to `/watch/${id}` immediately (Phase 1b behavior
preserved)
AND no list re-fetch is required for that flow (the list fetch runs only
on mount).

## Invariants

1. **Sort stability for with-progress group.** Within the with-progress
   group, ordering is strictly determined by `progress.updated_at` DESC.
   Newer activity is always above older activity.
2. **Sort stability for without-progress group.** Within the
   without-progress group, ordering is strictly determined by `created_at`
   DESC, matching Phase 0 / Phase 1b semantics.
3. **Click target isolation.** A click on the reset button NEVER navigates
   the user away. A click anywhere else on the card NEVER triggers reset.
4. **Reset is non-destructive to subtitles.** "重置進度" deletes only the
   `video_progress` row. The `videos`, `segments`, `jobs`, and any cached
   audio file are unchanged. A re-submit of the same URL hits the
   subtitles cache.
5. **Per-card error isolation.** A failed reset surfaces only on the
   affected card; other cards are unaffected.
6. **Progress bar is read-only and clamped.** The bar reflects
   `last_played_sec / duration_sec` clamped to `[0, 1]`. The card itself
   does not modify progress.
7. **Refetch on success only.** Reset triggers a list refetch only when
   the DELETE succeeds. A failed DELETE leaves the list state unchanged.
8. **Backward-compat field set.** A consumer that reads only the Phase 0
   fields (`video_id`, `title`, `duration_sec`, `created_at`) sees
   identical bytes to Phase 0 / Phase 1b for the same underlying state.

## Non-goals (Phase 2)

- Search / filter on the history list.
- Bulk-reset across multiple videos.
- Deletion of the video itself (hard-delete is out of scope).
- Inline edit of the title or thumbnail.
- Drag-to-reorder the list (sort is server-side and not user-customizable).
- Real-time updates of `progress.updated_at` while the list is open
  (refresh-on-reset is the only update path).
- A "completed" badge for videos played to within ε of `duration_sec` (no
  ε threshold defined; would be Phase 3 territory).
- Persisting which card the user last hovered or clicked.
