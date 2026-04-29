# Capability — Player Resume (Phase 2)

## Responsibilities

- On every `/watch/:videoId` mount where `status === 'completed'`, fetch
  the per-video progress once via `useVideoProgress(videoId)`.
- When progress exists AND the YouTube IFrame player reports
  `isReady=true`, run a one-shot resume sequence: clamp / recompute
  values, seek, set rate, set loop, show `<ResumeToast>`.
- Guard the resume effect with `restoredRef` so it runs exactly once per
  page lifecycle, even under React StrictMode double-mounts or transient
  isReady flips.
- Auto-dismiss the toast after 5 seconds wall-clock; allow user to dismiss
  via ✕ or jump to t=0 via 「從頭播」.
- Map user-meaningful events (pause, seek, rate change, loop toggle) to
  debounced `progress.save(...)` calls.
- Force-flush pending saves on `visibilitychange=hidden`, `beforeunload`,
  and component unmount.
- Never block player rendering on progress availability — failures are
  silent and `value=null` is a valid path.

## Public interfaces

### Hook signature

```ts
// frontend/src/features/player/hooks/useVideoProgress.ts

export interface UseVideoProgressResult {
  value: VideoProgress | null;
  loaded: boolean;
  save: (partial: Partial<Omit<VideoProgress, 'updated_at'>>) => void;
  reset: () => Promise<void>;
}

export function useVideoProgress(videoId: string | null): UseVideoProgressResult;
```

### Toast component

```tsx
// frontend/src/features/player/components/ResumeToast.tsx

interface ResumeToastProps {
  playedAtSec: number;
  segmentIdx: number;
  onDismiss: () => void;
  onRestart: () => void;
}

export function ResumeToast(props: ResumeToastProps): JSX.Element;
```

### Layout integration

`CompletedLayout` composes `useVideoProgress(videoId)` alongside the
existing Phase 1a hooks (`useYouTubePlayer`, `useSubtitleSync`,
`useAutoPause`, `useLoopSegment`, `usePlaybackRate`,
`useKeyboardShortcuts`). Resume effect and save propagation live in
`CompletedLayout` (or in an extracted `useResumeOnce` hook if LOC budget
forces).

## Behavior scenarios

### Hook: load on mount, GET 200

GIVEN `useVideoProgress("abc...")` is mounted with a non-null videoId
WHEN the effect runs
THEN exactly one `getProgress("abc...")` call is issued
AND on resolution with a 200 body, the hook updates `value` to the parsed
object and `loaded` to `true`.

### Hook: load on mount, GET 404 → null

GIVEN `useVideoProgress("abc...")` is mounted
WHEN `getProgress` resolves with `null` (the API client converts 404 →
null per `progress-api.md`)
THEN `value` becomes `null` and `loaded` becomes `true`.

### Hook: load on mount, GET error → null, silent

GIVEN `useVideoProgress("abc...")` is mounted
WHEN `getProgress` throws (network or 5xx)
THEN the hook updates `value=null` and `loaded=true` without surfacing the
error
AND a `console.warn` is emitted (best-effort log).

### Hook: videoId=null is inert

GIVEN `useVideoProgress(null)` is mounted
WHEN the effect runs
THEN no fetch is issued
AND `loaded` stays `false`, `value` stays `null`
AND `save(...)` and `reset()` calls are no-ops.

### Hook: videoId change is not exercised in production

The hook is mounted with a single fixed `videoId` for its lifetime.
`videoId` prop change is NOT a production code path: `CompletedLayout` (the
sole consumer in Phase 2) unmounts on route param change, which triggers
the cleanup flush. No "live videoId swap" semantics are specified or
tested.

### Hook: save debounces by 1 second

GIVEN the hook is loaded with a non-null `value`
WHEN `save({last_played_sec: 67})` is called at t=0
AND no further save is called for 1000ms
THEN exactly one PUT fires at approximately t=1000ms with the merged body.

### Hook: save coalesces multiple calls within 1s

GIVEN the hook is loaded
WHEN `save(A)` is called at t=0, `save(B)` at t=400, `save(C)` at t=800
THEN exactly ONE PUT fires (after the last call's debounce expires) with
a body containing the merged values from A, B, and C.

### Hook: save merges over current cached value

GIVEN the hook has loaded `value = { last_played_sec: 30, last_segment_idx:
5, playback_rate: 1.0, loop_enabled: false, updated_at: ... }`
WHEN `save({playback_rate: 1.5})` is called
THEN the eventual PUT body is `{ last_played_sec: 30, last_segment_idx: 5,
playback_rate: 1.5, loop_enabled: false }`
AND `updated_at` is omitted from the body (server-stamped).

### Hook: save when value is null uses zero defaults

GIVEN the hook has loaded with `value=null` (no row yet)
WHEN `save({last_played_sec: 30, last_segment_idx: 5})` is called
THEN the eventual PUT body is `{ last_played_sec: 30, last_segment_idx: 5,
playback_rate: 1.0, loop_enabled: false }`
AND on success the hook updates `value` to reflect the new state.

### Hook: visibilitychange=hidden flushes immediately

GIVEN a pending debounced save is scheduled
WHEN the document fires `visibilitychange` with
`document.visibilityState === 'hidden'`
THEN the pending PUT fires immediately (does not wait for the 1s timer).

### Hook: beforeunload flushes immediately

GIVEN a pending debounced save is scheduled
WHEN the window fires `beforeunload`
THEN the pending PUT is sent immediately
AND the implementation prefers `navigator.sendBeacon` if available, else
`fetch(..., { keepalive: true })`.

### Hook: unmount flushes pending save

GIVEN a pending debounced save is scheduled
WHEN the component unmounts (e.g., user navigates away)
THEN the pending PUT fires immediately
AND no further PUTs fire after unmount.

### Hook: in-flight GET discarded on unmount

GIVEN a slow-resolving initial GET
WHEN the component unmounts before the GET resolves
THEN the resolution does NOT call setState
AND no React "state update on unmounted component" warning is emitted.

### Hook: reset calls DELETE immediately

GIVEN the hook is loaded
WHEN `reset()` is called
THEN exactly one `deleteProgress(videoId)` call is issued
AND the call does NOT wait for any debounce.

### Hook: reset on success clears value

GIVEN `reset()` is called and `deleteProgress` resolves with 204
WHEN the promise settles
THEN `value` becomes `null`
AND the next `save(...)` call writes a fresh row (defaults filled in).

### Hook: reset clears pending debounced save

GIVEN a pending debounced save is scheduled
WHEN `reset()` is called
THEN the pending PUT timer is cleared
AND the only network operation is the DELETE
AND no PUT fires for the pre-reset debounced state.

### Hook: reset rejection keeps value

GIVEN `reset()` is called and `deleteProgress` rejects
WHEN the promise settles with rejection
THEN `value` is unchanged
AND the rejection bubbles up so the caller (VideoCard) can render an
error.

### Resume: no resume when value is null

GIVEN `CompletedLayout` is mounted with `useVideoProgress` returning
`value=null, loaded=true` and `useYouTubePlayer.isReady=true`
WHEN the component renders
THEN no `seekTo` is called
AND no `<ResumeToast>` is rendered
AND `restoredRef.current` is set to `true` to suppress future re-runs.

### Resume: no resume until loaded=true

GIVEN `value` is non-null but `loaded=false` (GET still in flight)
AND `isReady=true`
WHEN the component renders
THEN the resume effect does NOT run
AND once `loaded` flips to `true`, the resume effect runs.

### Resume: no resume until isReady=true

GIVEN `value=non-null, loaded=true, isReady=false`
WHEN the component renders
THEN the resume effect does NOT run
AND once `isReady` flips to `true`, the resume effect runs.

### Resume: runs when loaded AND isReady AND value present

GIVEN `value = { last_played_sec: 67, last_segment_idx: 17,
playback_rate: 1.5, loop_enabled: true, updated_at: ... }`
AND `loaded=true, isReady=true`
WHEN the resume effect fires
THEN `seekTo(67)` is called
AND `setRate(1.5)` is called
AND the loop state is toggled to `true`
AND `<ResumeToast>` is rendered with `playedAtSec=67, segmentIdx=17`
AND `restoredRef.current` is set to `true`.

### Resume: runs exactly once via restoredRef

GIVEN the resume effect has already run (`restoredRef.current === true`)
WHEN any subsequent re-render fires (e.g., transient `isReady=false →
true`, value mutation, segment append)
THEN the resume effect does NOT run again.

### Resume: never indexes segments[] with raw stored idx

GIVEN `value.last_segment_idx = 999999` (corrupted / huge value)
AND `segments.length = 12`
WHEN the resume effect runs
THEN the seek target is `clamp(value.last_played_sec, 0, duration_sec)` —
NEVER a value derived from `segments[999999]` (which would be `undefined`
and crash on property access)
AND the segment-idx recompute (binary search on `last_played_sec`) yields
a valid idx for the toast label
AND the component does NOT throw.

### Resume: negative segment idx is treated as invalid

GIVEN `value.last_segment_idx = -1` (defensive; should never reach the
client because backend repo rejects it)
WHEN the resume effect runs
THEN the recompute path runs (treating the stored idx as out-of-range)
AND the toast falls back to recomputed idx (or idx=0 + suppressed toast if
recompute fails)
AND `seekTo(value.last_played_sec)` is still called.

### Resume: state-arrival orderings (6 permutations)

The resume effect's correctness is independent of the order in which the
six "ready inputs" arrive: `loaded`, `progress.value` (non-null),
`isReady`, `data.status === "completed"`, `segments[]` (non-empty), and a
transient stream-reconnect that appends new segments. The effect's
`restoredRef.current` guard ensures the resume sequence runs **at most
once** in every permutation; the dep array `[progress.loaded,
progress.value, isReady, segments]` ensures the recompute path uses the
latest `segments` reference.

GIVEN any of the six arrival orderings (the most non-obvious cases below)
WHEN the resume effect's effect runs through every render
THEN `seekTo` is called exactly once (the call corresponding to the
first render where `loaded && value && isReady` all hold).

#### Resume: cache-hit completed before useVideoProgress GET resolves

GIVEN `useSubtitleStream`'s first poll returns `status="completed"`
synchronously
AND `CompletedLayout` mounts
AND `useYouTubePlayer.isReady` flips to `true` BEFORE
`useVideoProgress`'s GET resolves
WHEN the GET eventually resolves with non-null progress
THEN the resume effect runs once (on the render after GET resolves)
AND `seekTo(value.last_played_sec)` is called once.

#### Resume: stream-reconnect appends segments after resume

GIVEN the resume effect has already run (`restoredRef.current === true`)
WHEN a stream reconnect appends new segments to `segments[]` (causing the
dep array to fire)
THEN the resume effect re-runs but is a no-op (guarded by `restoredRef`)
AND `seekTo` is NOT called a second time.

### Resume: clamps last_played_sec to data.duration_sec

GIVEN `value.last_played_sec = 200`, `data.duration_sec = 180`
WHEN the resume effect fires
THEN `seekTo(180)` is called (clamped)
AND the toast's `playedAtSec` is `180`.

### Resume: recomputes last_segment_idx when out of range

GIVEN `value.last_segment_idx = 99`, `segments.length = 20`,
`value.last_played_sec = 67`
WHEN the resume effect fires
THEN the effect recomputes the segment index via binary search on
`last_played_sec` against the `segments` array (same algorithm as
`useSubtitleSync`)
AND `seekTo(67)` is called
AND the toast's `segmentIdx` is the recomputed value (e.g., 7 if segment
7 contains time 67).

### Resume: recompute falls back to 0 when no segment matches

GIVEN `value.last_played_sec = -5` (defensive; should not occur due to
backend validation)
WHEN the resume effect fires
THEN the recompute falls back to `idx=0`
AND the toast does NOT render (per `design.md` §13: "no toast" for the
no-match fallback).

### Resume: clamps playback_rate below 0.5

GIVEN `value.playback_rate = 0.1`
WHEN the resume effect fires
THEN `setRate(0.5)` is called.

### Resume: clamps playback_rate above 2.0

GIVEN `value.playback_rate = 3.0`
WHEN the resume effect fires
THEN `setRate(2.0)` is called.

### Resume: cache-hit + null progress shows no toast

GIVEN HomePage submits a URL whose subtitles are cached
AND the first poll of `useSubtitleStream` already returns
`status="completed"`
AND `useVideoProgress` returns `value=null, loaded=true`
WHEN the page renders
THEN the resume effect runs and is a no-op (no seek, no setRate, no toast)
AND `restoredRef.current` is set to `true`
AND the user sees the player at t=0 with default rate, no toast flash.

### Toast: renders played-at in m:ss format

GIVEN `<ResumeToast playedAtSec={67.3} segmentIdx={17} ... />`
WHEN the toast renders
THEN it shows the text `"已恢復到 1:07 (第 18 句)"` (or equivalent
arrangement using `formatPlayedAt` and `formatSegmentLabel`).

### Toast: 0 seconds renders 0:00

GIVEN `playedAtSec=0`
WHEN the toast renders
THEN the formatted time shows `"0:00"`.

### Toast: long-form time stays m:ss (20-minute cap)

GIVEN `playedAtSec=1199.9`
WHEN the toast renders
THEN the formatted time shows `"19:59"` (no hours; videos cap at 20min).

### Toast: auto-dismiss after 5 seconds wall-clock

GIVEN `<ResumeToast>` is mounted
WHEN 5 seconds elapse on the wall clock
THEN `onDismiss` is called once.

### Toast: dismiss button cancels auto-dismiss

GIVEN `<ResumeToast>` mounted at t=0
WHEN the user clicks ✕ at t=2s
THEN `onDismiss` is called immediately
AND no second `onDismiss` fires at t=5s.

### Toast: 從頭播 button calls onRestart

GIVEN `<ResumeToast onRestart=spyR>` is mounted
WHEN the user clicks 「從頭播」
THEN `spyR` is called once.

### Toast: 從頭播 path: parent calls seekTo(0) and dismisses

GIVEN `CompletedLayout` is rendering `<ResumeToast>`
WHEN the user clicks 「從頭播」
THEN the parent's `onRestart` handler calls `seekTo(0)` (or equivalently
`goToSegment(0)`)
AND the toast unmounts (parent sets `showToast=false`).

### Toast: subsequent save event after 從頭播 overwrites progress

GIVEN the user clicked 「從頭播」 and the player is at t=0, idx=0
WHEN the user pauses (or any save trigger fires)
THEN the next debounced PUT writes `{last_played_sec: 0, last_segment_idx:
0, playback_rate: <current>, loop_enabled: <current>}` to the backend
AND on subsequent reload, the resume effect would seek to 0 again (or
skip if it equals defaults — but the row exists, so resume runs and the
toast shows `"已恢復到 0:00 (第 1 句)"`).

### Toast: never renders for first-time view

GIVEN `value=null` (first-time view)
WHEN the resume effect runs (with `restoredRef` flipping to `true`)
THEN `<ResumeToast>` is NEVER rendered for this page lifecycle.

### Toast: pointer-events-none on backdrop

GIVEN `<ResumeToast>` is mounted
WHEN the user clicks anywhere outside the toast bubble
THEN the click reaches the underlying player surface (toast does not
intercept clicks via its backdrop).

### Save propagation: pause event saves position and segment idx

GIVEN `CompletedLayout` is mounted, `restoredRef.current=true`, and the
player is in state `playing`
WHEN the player transitions to state `paused` via the IFrame state
listener
AND the player's `getCurrentTime()` returns 42 and the current segment
index is 10
THEN the layout calls `progress.save({last_played_sec: 42,
last_segment_idx: 10})`.

### Save propagation: explicit seek (prev/next/click-segment) saves

GIVEN any of the explicit seek paths fires (`handlePrev`, `handleNext`,
`handleRepeat`, `handleClickSegment(k)`)
WHEN the seek lands at segment `k` with `start = T_k`
THEN the layout calls `progress.save({last_played_sec: T_k,
last_segment_idx: k})`.

### Save propagation: rate change saves

GIVEN `restoredRef.current=true`
WHEN `setRate(1.5)` is invoked from `usePlaybackRate`
THEN the layout calls `progress.save({playback_rate: 1.5})`.

### Save propagation: loop toggle saves

GIVEN `restoredRef.current=true`
WHEN `setLoop(true)` is invoked
THEN the layout calls `progress.save({loop_enabled: true})`.

### Save propagation: NOT called before isReady

GIVEN `isReady=false` and the user has not yet interacted
WHEN any incidental render fires (e.g., subtitles update)
THEN no `save(...)` is called.

### Save propagation: NOT called during the resume effect

GIVEN the resume effect is firing
AND the effect calls `setRate(stored)` and `setLoop(stored)` internally
WHEN those internal calls run
THEN they do NOT trigger a self-save loop (the save propagation is
gated on `restoredRef.current` AND on user-driven event sources, not on
state-set calls from inside the resume effect).

### Save propagation: continuous playback does not save

GIVEN the user presses play and the player ticks for 30 seconds without
pausing or seeking
WHEN no user-meaningful event fires
THEN no `save(...)` is called for those 30 seconds.

### Save propagation: visibilityHidden during playback flushes any pending save

GIVEN the user paused at t=42 (debounced save scheduled)
AND within 500ms the user backgrounds the tab
WHEN `visibilitychange=hidden` fires
THEN the pending PUT fires immediately (per the hook flush-trigger
behavior).

### Crash survivability path

GIVEN the user paused at t=30 (debounced save scheduled)
WHEN within 200ms the tab is closed (`beforeunload` fires)
THEN the hook's `beforeunload` listener flushes the pending PUT via
`sendBeacon`
AND on a subsequent navigation back to `/watch/${id}`, the GET returns the
flushed values
AND the resume effect seeks to t=30 (within ±5s of the original pause
point per `design.md` §14).

## Invariants

1. **Resume runs exactly once per page lifecycle.** The `restoredRef` ref
   is initialized to `false` on every mount and set to `true` after the
   first effect that satisfies `(loaded && isReady)`. Subsequent effect
   runs are no-ops.

   **INV-REF:** All `restoredRef.current = true` mutations occur inside
   `useEffect` callbacks. The ref is NEVER written during render. (Per
   project React 19 hook rules — `react-hooks/refs` lint rule.) The lint
   rule failing constitutes a green-test regression.

   **INV-OOB (out-of-bounds defense):** The seek target is always
   `clamp(stored.last_played_sec, 0, duration_sec)`. `last_segment_idx`
   is used **only** for the toast display label, and only after
   validation OR recompute via binary search. The resume effect MUST NOT
   index into `segments[]` using the raw stored `last_segment_idx` before
   validation. Even a corrupted `last_segment_idx = 999999` is safe: the
   seek uses `last_played_sec`; the toast uses the recomputed idx.
2. **No toast for null progress.** The toast renders if and only if the
   resume effect actually applied stored values from a non-null
   `progress.value`.
3. **Toast 5-second timer is wall-clock.** The timer is a single
   `setTimeout(onDismiss, 5000)` set on toast mount; player-state changes
   do not pause it (per proposal Open question 2).
4. **Save propagation is event-driven, not tick-driven.** Continuous
   playback alone does not trigger `save(...)`. Saves fire only on pause
   / seek / rate-change / loop-toggle / unmount-flush triggers.
5. **Save propagation is gated by `restoredRef`.** No save fires before
   the resume effect has completed (or determined that no resume is
   needed). This prevents the initial `setRate(default=1.0)` and
   `setLoop(default=false)` calls from overwriting a stored progress row
   before resume reads it.
6. **Coalesce within 1-second window.** N `save(...)` calls within a
   sliding 1-second window produce exactly one PUT.
7. **Force-flush on tab loss / unmount.** `visibilitychange=hidden`,
   `beforeunload`, and component unmount each force the pending PUT to
   fire immediately (best-effort; uses `sendBeacon` on `beforeunload`
   when available).
8. **Reset cancels pending debounced PUT.** Calling `reset()` clears the
   debounce timer before issuing the DELETE; no pre-reset PUT fires
   afterwards.
9. **Out-of-range stored values are tolerated.** The frontend clamps
   `playback_rate` to `[0.5, 2.0]` and recomputes `last_segment_idx` via
   binary search when out of range. The backend additionally clamps
   `last_played_sec` to `duration_sec` on read; the frontend does not
   re-clamp.
10. **Failure of progress operations never blocks the player.** GET 5xx,
    PUT non-204, network errors — all are silent (`console.warn` only).
    The player mounts and plays as normal.
11. **Player mount-once invariant preserved.** Phase 1b's "VideoPlayer
    mounts exactly once per page lifecycle" continues to hold; resume
    runs after mount and does not re-mount the player.
12. **INV-LOOP-TRANSIENT.** The resume effect's `setLoop(stored)` call
    schedules a re-render; `useLoopSegment` re-arms only after that
    re-render. The transient (resume-effect-render → next-render) is
    bounded by one React commit and is not user-visible because the
    IFrame is not yet playing — `useYouTubePlayer.isReady=true` does not
    imply `playerState === 1` (playing). The first user "play" click
    happens after the loop state has settled.

## Non-goals (Phase 2)

- Real-time progress sync across tabs of the same video (eventual
  consistency on next mount only).
- Per-segment marks or "I've practiced this sentence" — Phase 3.
- Resume across different videos (e.g., "continue where you left off in
  any video") — out of scope; resume is per-`video_id`.
- Persisting watched-time totals or per-session play history.
- A confirmation dialog before resume — auto-resume is the default UX
  per Decision #3.
- A user toggle to disable auto-resume globally.
- Pausing the toast timer when the player is paused (proposal Open
  question 2).
- Auto-recording defaults on first ready (proposal Open question 3).
- Persisting the keyboard-shortcuts state, captions toggle, fullscreen
  state, or any other player preference outside the four progress
  fields.
