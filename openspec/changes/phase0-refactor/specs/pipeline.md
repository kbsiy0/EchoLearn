# Capability — Pipeline

## Responsibilities
- Orchestrate end-to-end subtitle production for a video: metadata probe → audio acquisition → transcription → segmentation → translation → atomic persistence.
- Advance `jobs.progress` monotonically through the defined ladder.
- Translate failures from any stage into a canonical `error_code` + `error_message` on the job row.
- Clean up per-job ephemeral audio files on both success and failure.

## Public interfaces

```python
# backend/app/services/pipeline.py
def run(job_id: str) -> None: ...
```

The runner owns invocation; `pipeline.run` never creates threads of its own.

Internal collaborators (each a separate module, each unit-testable with its fake):

```python
# backend/app/services/transcription/youtube_audio.py
class VideoMetadata(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    source: str

def probe_metadata(url: str) -> VideoMetadata: ...
#   metadata-only (e.g., yt-dlp --dump-json). NO audio download.
#   raises INVALID_URL, VIDEO_UNAVAILABLE, VIDEO_TOO_LONG
#   VIDEO_TOO_LONG check uses duration_sec / 60 > MAX_VIDEO_MINUTES

def download_audio(video_id: str) -> Path: ...
#   precondition: probe_metadata already succeeded for this video_id
#   raises FFMPEG_MISSING
#   validates video_id against ^[A-Za-z0-9_-]{11}$ before composing any Path

# backend/app/services/transcription/whisper.py
class WhisperClient:
    def transcribe(self, audio_path: Path) -> list[Word]: ...
#     Word = {"text": str, "start": float, "end": float}

# backend/app/services/alignment/segmenter.py
def segment(words: list[Word]) -> list[Segment]: ...
#   raises ValueError("no speech detected") when words is empty
#   whitespace normalization rule defined in design.md Section 3

# backend/app/services/translation/translator.py
class Translator:
    def translate_batch(self, texts_en: list[str]) -> list[str]: ...
```

## Invariants
- **Single time base.** Every `Segment.start`, `Segment.end`, and per-word `start`/`end` originates from the Whisper word stream. No other timing source is mixed in.
- **Probe before download.** `probe_metadata` runs first and must succeed before `download_audio` is invoked. `VIDEO_TOO_LONG` and `VIDEO_UNAVAILABLE` are raised by probe, never by `download_audio`.
- **Progress is monotonic.** Each stage only advances `progress`; it never regresses, and each stage emits at least one update within its assigned range.
- **Atomic publish (Option A).** Translation results are held in memory until the final persist stage. The 95→100 step calls `publish_video(...)`, which performs an upsert on the `videos` row followed by insert of all `segments` rows, all within one SQLite transaction. If any prior stage fails, no `videos` or `segments` rows exist. There is no observable state where a `videos` row exists without its segments. Readers who want internals see `specs/data-layer.md`.
- **Audio cleanup is unconditional.** The audio file for a job is deleted whether the job completes, fails, or throws. Covered by the test `test_audio_deleted_on_whisper_failure`.
- **Error taxonomy.** Every failure path resolves to exactly one of: `INVALID_URL`, `VIDEO_UNAVAILABLE`, `VIDEO_TOO_LONG`, `FFMPEG_MISSING`, `WHISPER_ERROR`, `TRANSLATION_ERROR`, `INTERNAL_ERROR`.
- **`video_id` safety.** `video_id` matches `^[A-Za-z0-9_-]{11}$`. The regex is enforced at (a) HTTP intake, (b) repository writes, (c) `download_audio` before any `Path` composition. A malformed `video_id` reaching any of these layers raises before touching disk or DB.

## Non-goals
- Streaming or incremental publication of segments as they are produced (Phase 1).
- Retry logic inside the pipeline (caller/runner resubmits a new job if the user retries).
- Multi-language targets (Phase 2+).
- Any use of `youtube-transcript-api` — removed.
