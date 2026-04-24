# Capability — Player Streaming UI (Phase 1b)

## Responsibilities
- Flip the post-submit flow: `HomePage` navigates to `/watch/:videoId` as soon as `createJob` returns; no HomePage-side polling, no loading spinner on HomePage after submit.
- Turn `PlayerPage` from "read completed subtitles" into "read the live video view": poll `GET /subtitles/{videoId}` at 1-second cadence, branch on `status`, and render one of four layouts (processing placeholder + partial subtitle panel; failed placeholder + partial subtitle panel; failed error page; full Phase 1a player).
- Guarantee that the YouTube IFrame player mounts exactly once per page load, only when `status === 'completed'`.
- Preserve every Phase 1a behavior (loop, speed, auto-pause, `?measure=1` semantics, keyboard shortcuts, localStorage, sync precision) unchanged once the player is mounted.

## Public interfaces

### Streaming hook

```ts
// frontend/src/features/player/hooks/useSubtitleStream.ts

export function useSubtitleStream(videoId: string | null): {
  data: SubtitleResponse | null;
  error: string | null;
};
```

`SubtitleResponse` matches the backend shape in `subtitles-api.md` (status, progress, segments, optional title / duration_sec / error_code / error_message).

### Processing placeholder component

```tsx
// frontend/src/features/player/components/ProcessingPlaceholder.tsx

type Props = {
  progress: number;
  error?: string | null;
  title?: string | null;
};

export function ProcessingPlaceholder(props: Props): JSX.Element;
```

### Page routing

- `HomePage` no longer imports `useJobPolling` or `LoadingSpinner`; it calls `createJob`, then `navigate('/watch/${video_id}')` on success.
- `PlayerPage` calls `useSubtitleStream(videoId)` and renders one of: `<LoadingSpinner />` (pre-first-response), `ProcessingLayout` (for `queued` / `processing`), `ProcessingLayout` with error (for `failed`), `CompletedLayout` (for `completed`).

## Behavior scenarios

### HomePage: successful submission navigates immediately

GIVEN the user enters a valid YouTube URL on HomePage and presses submit
AND the `POST /api/subtitles/jobs` call resolves successfully with `{ job_id, video_id, ... }`
WHEN the response arrives
THEN HomePage calls `navigate('/watch/${video_id}')` on the same tick
AND HomePage does not render a loading spinner
AND HomePage does not start any polling.

### HomePage: submission error keeps user on HomePage

GIVEN the user submits a URL on HomePage
AND `createJob` rejects with a network or validation error
WHEN the rejection fires
THEN HomePage surfaces the error inline (existing Phase 0 error UI)
AND HomePage does not navigate away
AND HomePage is ready to accept a new submission.

### HomePage: cache-hit short-circuit preserved

GIVEN a submission for a `video_id` that already has a `completed` record (Phase 0 cache-hit behavior)
WHEN `createJob` resolves with a synthetic completed job
THEN HomePage still navigates to `/watch/${video_id}` immediately (the `PlayerPage` will observe `status === 'completed'` on its first poll and render the full Phase 1a player).

### useSubtitleStream: initial fetch fires synchronously on mount

GIVEN `useSubtitleStream(videoId)` is mounted with a non-null `videoId`
WHEN the effect runs
THEN the hook calls `getSubtitles(videoId)` immediately (no 1-second blank)
AND subsequent polls happen every 1000ms via `setInterval`.

### useSubtitleStream: updates data on each successful response

GIVEN an active `useSubtitleStream` hook
WHEN a poll returns a `SubtitleResponse`
THEN the hook updates `data` to the latest response
AND subsequent renders of the consuming component observe the new `data`.

### useSubtitleStream: cleans up on unmount

GIVEN an active `useSubtitleStream` hook
WHEN the consuming component unmounts
THEN the interval is cleared
AND any in-flight fetch's result is discarded (no state update after unmount).

### useSubtitleStream: null videoId is inert

GIVEN `useSubtitleStream(null)` is mounted
WHEN the effect runs
THEN no fetch is issued and no interval is registered
AND `data` remains `null`.

### useSubtitleStream: transient error surfaces without stopping polling

GIVEN an active `useSubtitleStream` hook
WHEN a single poll fails (e.g., transient network error)
THEN the hook updates `error` to the error message
AND the next 1-second tick still fires a fetch
AND a successful subsequent poll clears `error` (or replaces `data` regardless of the prior error).

### useSubtitleStream: stops polling after terminal status

GIVEN an active `useSubtitleStream` hook
WHEN a poll returns `status="completed"` or `status="failed"`
THEN the hook clears its `setInterval` and does not fire additional fetches for the lifetime of this hook instance
AND subsequent user interactions that do not change `videoId` do NOT restart polling.

### useSubtitleStream: terminal-stop preserves final data

GIVEN the hook has reached a terminal status and stopped polling
WHEN the component re-renders for any reason
THEN `data` retains the last response (terminal-stop does not clear state).

### PlayerPage: pre-first-response shows loading spinner

GIVEN `PlayerPage` has just mounted and `useSubtitleStream.data` is still `null`
WHEN the page renders
THEN it shows `<LoadingSpinner progress={0} status="載入中..." />`
AND no `<VideoPlayer>` is mounted.

### PlayerPage: processing state renders placeholder + partial subtitle panel, no player

GIVEN `useSubtitleStream.data.status === 'processing'` with `progress === 45` and some partial `segments`
WHEN the page renders
THEN it renders the processing layout: on one side `ProcessingPlaceholder` showing `progress=45` and `"處理字幕中 (45%)"`; on the other side a read-only `SubtitlePanel` listing the partial `segments`
AND `<VideoPlayer>` is not mounted in the DOM
AND the player controls bar is not visible.

### PlayerPage: appended segments appear in the subtitle panel between polls

GIVEN `PlayerPage` is in `processing` state with `segments.length === K`
WHEN a subsequent poll returns `segments.length === K + M` (M > 0, same first K entries)
THEN the `SubtitlePanel` renders K + M segments
AND no re-mount of the subtitle panel is triggered by the growth (append-only diff).

### PlayerPage: failed with partial segments renders error placeholder + read-only panel

GIVEN `data.status === 'failed'` with `error_message="Whisper transient timeout"` and 12 existing segments
WHEN the page renders
THEN it renders the processing layout with the placeholder in error mode: title "處理失敗", the `error_message` body, and a "回首頁" button
AND the `SubtitlePanel` on the other side lists the 12 segments (read-only: no highlight, no click)
AND `<VideoPlayer>` is not mounted.

### PlayerPage: failed with zero segments renders error-only page

GIVEN `data.status === 'failed'` with `segments === []` and an `error_message`
WHEN the page renders
THEN the `ProcessingPlaceholder` is shown in error mode
AND the `SubtitlePanel` area is empty (or absent)
AND `<VideoPlayer>` is not mounted.

### PlayerPage: "回首頁" button navigates to the home route

GIVEN `PlayerPage` is rendering the failed placeholder
WHEN the user clicks the "回首頁" button
THEN the app navigates to `/`.

### PlayerPage: completed state renders the full Phase 1a player

GIVEN `data.status === 'completed'` with a full `segments` list
WHEN the page renders
THEN the completed layout is shown: `<VideoPlayer>`, `<SubtitlePanel>` with interactive highlight/click, and `<PlayerControls>` with loop, speed, and keyboard shortcuts all wired
AND Phase 1a behaviors are all active: auto-pause (when not `?measure=1`), loop toggle, speed buttons, keyboard shortcuts, `?measure=1` disables loop + auto-pause.

### PlayerPage: transition from processing to completed mounts the player once

GIVEN `PlayerPage` has been rendering the processing layout across several polls
WHEN the next poll returns `status === 'completed'`
THEN the processing layout is unmounted and the completed layout is mounted
AND `<VideoPlayer>` mounts exactly once in this page lifecycle
AND subsequent polls (which continue returning `status === 'completed'`) do not trigger additional mounts of `<VideoPlayer>`.

### PlayerPage: progress observed by the user is monotone

GIVEN `PlayerPage` is in `processing` state over multiple poll ticks
WHEN the `ProcessingPlaceholder` re-renders on each new `data`
THEN the displayed `progress` never regresses from one render to the next for the same page lifecycle.

### PlayerPage: Phase 1a hooks see a stable segments array

GIVEN `status` transitions `processing → completed`
WHEN the Phase 1a hooks (`useSubtitleSync`, `useAutoPause`, `useLoopSegment`, `usePlaybackRate`, `useKeyboardShortcuts`) first mount inside the completed layout
THEN they each see a non-growing, final `segments` array on their first run
AND no Phase 1a invariant is asserted against an in-flight (growing) segments array.

### PlayerPage: sticky-completed guard blocks downgrade to processing

GIVEN `PlayerPage` has observed `data.status === 'completed'` at least once during its lifecycle
WHEN a later poll returns `status="processing"` or `status="failed"` (possible when the same `video_id` is resubmitted from another tab)
THEN `PlayerPage` continues rendering `<CompletedLayout>` using the last-seen completed data
AND `<VideoPlayer>` stays mounted with the same React instance (playback position, pause state, loop state preserved).

### PlayerPage: sticky-completed resets on page reload

GIVEN the sticky-completed guard is active in one tab
WHEN the user reloads the page (or navigates away and back)
THEN the lifecycle resets: the guard's ref is back to `false`, and the page re-enters the normal `processing → completed` flow based on the first poll response.

### PlayerPage: TTFS event fires exactly once on first segment appearance

GIVEN `PlayerPage` is in `status="processing"` with `data.segments.length === 0`
WHEN a poll returns a response where `segments.length` transitions from 0 to any positive number
THEN `PlayerPage` dispatches `window.dispatchEvent(new CustomEvent('el:first-segment', { detail: { t: performance.now() } }))` exactly once for this page lifecycle
AND subsequent segment appends during the same processing session do NOT re-fire the event.

### PlayerPage: TTFS event does not fire on cache-hit completed mount

GIVEN `PlayerPage` mounts and the first poll returns `status="completed"` directly (cache-hit path from `createJob`)
WHEN the render completes
THEN no `el:first-segment` event is dispatched (TTFS is undefined for a cached video — we only instrument the streaming path).

### PlayerPage: `?measure=1` semantics unchanged

GIVEN the URL contains `?measure=1`
WHEN `PlayerPage` reaches the completed layout
THEN `computePlaybackFlags` returns `autoPauseEnabled=false, loopEnabled=false` (Phase 1a behavior preserved)
AND ui-verifier's precision measurement flow continues to work.

### ProcessingPlaceholder: renders progress bar and percentage text

GIVEN `ProcessingPlaceholder` is rendered with `progress=32` and no error
WHEN it renders
THEN it shows a progress bar with its width scaled to 32% and a label text reading `"處理字幕中 (32%)"`
AND it does not render the error elements or the "回首頁" button.

### ProcessingPlaceholder: renders error state with navigation button

GIVEN `ProcessingPlaceholder` is rendered with `error="Whisper transient timeout"`
WHEN it renders
THEN it shows the "處理失敗" heading, the error message, and a "回首頁" button
AND it does not render the progress bar.

### ProcessingPlaceholder: renders title when provided

GIVEN `ProcessingPlaceholder` is rendered with `title="How to build a spec"` and `progress=10`
WHEN it renders
THEN the title is rendered (truncated if long)
AND the progress bar and label are also rendered.

## Additional invariants

- **Sticky-completed across polls.** Once `status=completed` is observed, the render stays on the completed layout for the rest of the page lifecycle regardless of later poll responses.
- **Terminal polling stops.** `useSubtitleStream` clears its interval on first terminal response to prevent unbounded polling on long-lived tabs.
- **TTFS event fires at most once per mount.** `window.dispatchEvent('el:first-segment', ...)` is guarded by a ref that only flips on the 0→>0 segment transition.
- **Cache-hit does not fire TTFS.** The event is bound to the processing-state-first-segment transition; cache-hit pages go directly to completed and emit nothing.

## Invariants

1. **Navigate-immediately.** HomePage does not render a loading spinner nor poll after a successful `createJob`; it navigates on the same tick.
2. **Player mount-once.** `<VideoPlayer>` mounts exactly once per page lifecycle, at the `processing → completed` transition.
3. **No player during processing or failed.** `<VideoPlayer>` is never mounted while `status` is `queued`, `processing`, or `failed`.
4. **User-observed progress is monotone.** Across one page lifecycle, the `progress` displayed by `ProcessingPlaceholder` is non-decreasing.
5. **Append-only segments in processing.** The `SubtitlePanel` during processing never loses segments from a prior poll tick.
6. **Phase 1a preserved.** Once in the completed layout, all Phase 1a behaviors (loop, speed, auto-pause, `?measure=1`, keyboard shortcuts, localStorage, sync precision bar) function identically to Phase 1a.
7. **Resubmission atomicity visible to the UI.** When a backend resubmission clears prior segments via `upsert_video_clear_segments`, the next poll observed by the UI is consistent (no mixed old/new segments).

## Non-goals (Phase 1b)

- Partial-range playback (player does not mount before completion).
- SSE / WebSocket transport — polling only.
- Word-level streaming in the subtitle panel.
- Cancellation of in-flight jobs (no user-initiated cancel UI).
- Changing the `?measure=1` semantics or adding new URL flags.
- Introducing TanStack Query or similar for polling.
- Mounting the player with a ready-range and disabling seek beyond it.
- A `current_stage` string label in the UI.
