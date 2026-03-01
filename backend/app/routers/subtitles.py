from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.cache.store import get_cached, save_cache
from app.models.schemas import (
    ErrorResponse,
    JobCreate,
    JobStatus,
    SubtitleResponse,
    SubtitleSegment,
    WordTiming,
)
from app.services.transcript import fetch_transcript
from app.services.translator import translate_segments
from app.services.url_validator import VIDEO_ID_REGEX, validate_youtube_url
from app.services.whisper import check_ffmpeg, get_word_timestamps, transcribe_audio
from app.services.youtube_audio import download_audio
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])

# In-memory job store
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def normalize_segments(segments: list[dict]) -> list[dict]:
    """Merge raw transcript fragments into natural sentences.

    YouTube transcripts are often chopped into 2-3 second fragments mid-sentence.
    This merges them into complete sentences by looking for sentence-ending punctuation.

    Rules:
    - Keep merging until text ends with sentence punctuation (.!?)
    - If no punctuation found, merge until duration >= 8s then cut
    - Never exceed 15s per merged segment
    - Always merge <1s fragments into previous

    Args:
        segments: List of dicts with "start", "end" (or "duration"), and "text".

    Returns:
        List of merged segment dicts with "start", "end", "text".
    """
    if not segments:
        return []

    # Ensure all segments have "end"
    cleaned = []
    for seg in segments:
        start = seg["start"]
        if "end" in seg:
            end = seg["end"]
        else:
            end = start + seg.get("duration", 0)
        text = seg["text"].strip()
        if text:
            cleaned.append({"start": start, "end": end, "text": text})

    if not cleaned:
        return []

    result = []
    current = dict(cleaned[0])

    for seg in cleaned[1:]:
        current_duration = current["end"] - current["start"]
        potential_duration = seg["end"] - current["start"]

        # Would merging exceed 15s cap? Finalize current and start new.
        if potential_duration > 15:
            result.append(current)
            current = dict(seg)
            continue

        # Always absorb <1s fragments
        seg_duration = seg["end"] - seg["start"]
        if seg_duration < 1.0:
            current["end"] = seg["end"]
            current["text"] = current["text"] + " " + seg["text"]
            continue

        # If current ends with sentence punctuation and is long enough, finalize
        ends_with_punct = bool(re.search(r'[.!?]$', current["text"]))
        if ends_with_punct and current_duration >= 3:
            result.append(current)
            current = dict(seg)
            continue

        # If no punctuation but already >= 8s, force cut
        if current_duration >= 8:
            result.append(current)
            current = dict(seg)
            continue

        # Otherwise keep merging
        current["end"] = seg["end"]
        current["text"] = current["text"] + " " + seg["text"]

    result.append(current)
    return result


def estimate_word_timings(text: str, start: float, end: float) -> list[dict]:
    """Estimate per-word timing by distributing duration proportionally by character length.

    - Punctuation-only tokens get zero weight.
    - Minimum word duration is 0.05s.
    - Precision: 3 decimal places.

    Args:
        text: The segment text.
        start: Segment start time in seconds.
        end: Segment end time in seconds.

    Returns:
        List of dicts with "word", "start", "end".
    """
    words = text.split()
    if not words:
        return []

    duration = end - start
    if duration <= 0:
        # Zero-duration segment: all words get the same timestamp
        return [{"word": w, "start": round(start, 3), "end": round(end, 3)} for w in words]

    MIN_DURATION = 0.05

    # Calculate weights: character length for real words, 0 for punctuation-only tokens
    weights = []
    for w in words:
        if re.match(r'^[^\w]+$', w):
            weights.append(0)
        else:
            weights.append(len(w))

    total_weight = sum(weights)
    if total_weight == 0:
        # All tokens are punctuation — distribute evenly
        per_word = duration / len(words)
        result = []
        cursor = start
        for w in words:
            w_end = cursor + per_word
            result.append({"word": w, "start": round(cursor, 3), "end": round(w_end, 3)})
            cursor = w_end
        return result

    # First pass: allocate proportionally, enforce minimum
    raw_durations = []
    for weight in weights:
        if weight == 0:
            raw_durations.append(0)
        else:
            raw_durations.append(max(MIN_DURATION, duration * weight / total_weight))

    # Scale to fit total duration
    raw_total = sum(raw_durations)
    if raw_total > 0:
        scale = duration / raw_total
        raw_durations = [d * scale for d in raw_durations]

    # Build result
    result = []
    cursor = start
    for i, w in enumerate(words):
        w_end = cursor + raw_durations[i]
        result.append({"word": w, "start": round(cursor, 3), "end": round(w_end, 3)})
        cursor = w_end

    # Fix last word end to match segment end exactly
    if result:
        result[-1]["end"] = round(end, 3)

    return result


def assign_words_to_segment(all_words: list[dict], seg_start: float, seg_end: float) -> list[dict]:
    """Pick words from Whisper word list that fall within segment time range."""
    result = []
    for w in all_words:
        # Word belongs to this segment if its start time falls within range
        if w["start"] >= seg_start - 0.05 and w["start"] < seg_end + 0.05:
            result.append({
                "word": w["word"],
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })
    return result


def _update_job(job_id: str, **kwargs) -> None:
    """Thread-safe update of job fields."""
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _process_video(job_id: str, video_id: str) -> None:
    """Background processing pipeline for a video.

    Steps:
      1. (progress 10) Fetch transcript via youtube-transcript-api
      2. (progress 30) If no transcript, try whisper fallback
      3. (progress 50) Merge short segments into sentences
      4. (progress 70) Translate via GPT
      5. (progress 90) Save to cache
      6. (progress 100) Done
    """
    source = "youtube_captions"
    whisper_words: list[dict] | None = None

    try:
        _update_job(job_id, status="processing", progress=10)

        # Step 1: Try fetching transcript from YouTube
        raw_segments = None
        title = video_id
        try:
            raw_segments, title = fetch_transcript(video_id)
            logger.info(f"Fetched {len(raw_segments)} transcript segments for {video_id}")
        except ValueError as e:
            error_msg = str(e)
            if "NO_CAPTIONS" in error_msg or "VIDEO_PRIVATE" in error_msg:
                logger.info(f"No YouTube captions for {video_id}, will try Whisper")
                raw_segments = None
            else:
                raise

        _update_job(job_id, progress=20)

        # Step 2: Download audio for Whisper word timestamps
        audio_dir = os.path.join(settings.CACHE_DIR, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = None

        if raw_segments is None:
            # No YouTube captions — full Whisper transcription
            source = "whisper"

            if not check_ffmpeg():
                raise ValueError("NO_CAPTIONS: ffmpeg is required for Whisper fallback but is not installed")

            try:
                audio_path = download_audio(video_id, audio_dir)
                raw_segments, whisper_words = transcribe_audio(video_id, audio_path)
            finally:
                audio_file = os.path.join(audio_dir, f"{video_id}.mp3")
                if os.path.exists(audio_file):
                    os.remove(audio_file)
        else:
            # Have YouTube captions — download audio just for word-level timing
            if check_ffmpeg():
                try:
                    _update_job(job_id, progress=30)
                    audio_path = download_audio(video_id, audio_dir)
                    whisper_words = get_word_timestamps(video_id, audio_path)
                except Exception as e:
                    logger.warning(f"Word timestamp enrichment failed for {video_id}, using estimates: {e}")
                    whisper_words = None
                finally:
                    audio_file = os.path.join(audio_dir, f"{video_id}.mp3")
                    if os.path.exists(audio_file):
                        os.remove(audio_file)

        if not raw_segments:
            raise ValueError("NO_CAPTIONS: No transcript segments could be extracted")

        _update_job(job_id, progress=50)

        # Step 3: Normalize segments (merge fragments into sentences)
        merged = normalize_segments(raw_segments)
        logger.info(f"Normalized {len(raw_segments)} segments into {len(merged)} for {video_id}")

        _update_job(job_id, progress=70)

        # Step 4: Translate via GPT
        translated = translate_segments(merged)

        _update_job(job_id, progress=90)

        # Step 5: Build response and save to cache
        subtitle_segments = []
        for i, seg in enumerate(translated):
            seg_start = round(seg["start"], 3)
            seg_end = round(seg["end"], 3)

            if whisper_words:
                word_timings = assign_words_to_segment(whisper_words, seg_start, seg_end)
            else:
                word_timings = estimate_word_timings(seg["text"], seg_start, seg_end)

            subtitle_segments.append(
                SubtitleSegment(
                    index=i,
                    start=seg_start,
                    end=seg_end,
                    text_en=seg["text"],
                    text_zh=seg.get("text_zh", ""),
                    words=[WordTiming(**wt) for wt in word_timings],
                )
            )

        response = SubtitleResponse(
            video_id=video_id,
            title=title,
            segments=subtitle_segments,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        save_cache(video_id, response)

        _update_job(job_id, status="completed", progress=100)
        logger.info(f"Completed processing for {video_id}")

    except ValueError as e:
        error_msg = str(e)
        # Parse error code from message
        if ":" in error_msg:
            code, message = error_msg.split(":", 1)
            code = code.strip()
            message = message.strip()
        else:
            code = "NO_CAPTIONS"
            message = error_msg

        retryable = code in ("OPENAI_ERROR",)
        error = ErrorResponse(code=code, message=message, retryable=retryable)
        _update_job(job_id, status="failed", error=error.model_dump())
        logger.error(f"Processing failed for {video_id}: {code}: {message}")

    except Exception as e:
        error = ErrorResponse(
            code="OPENAI_ERROR",
            message=f"Unexpected error: {e}",
            retryable=True,
        )
        _update_job(job_id, status="failed", error=error.model_dump())
        logger.error(f"Unexpected error processing {video_id}: {e}", exc_info=True)


@router.post("/jobs", status_code=202)
def create_job(body: JobCreate):
    """Create a subtitle extraction job.

    Validates the URL, checks cache, and starts background processing.
    Returns 200 with cached data or 202 with job info.
    """
    try:
        video_id = validate_youtube_url(body.youtube_url)
    except ValueError as e:
        error_msg = str(e)
        if ":" in error_msg:
            code, message = error_msg.split(":", 1)
        else:
            code, message = "INVALID_URL", error_msg
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=code.strip(), message=message.strip(), retryable=False
            ).model_dump(),
        )

    # Check cache first
    cached = get_cached(video_id)
    if cached is not None:
        job_id = str(uuid.uuid4())
        return JobStatus(
            job_id=job_id,
            video_id=video_id,
            status="completed",
            progress=100,
            cached=True,
        ).model_dump()

    # Create job
    job_id = str(uuid.uuid4())
    job_data = {
        "job_id": job_id,
        "video_id": video_id,
        "status": "queued",
        "progress": 0,
        "error": None,
        "cached": False,
    }

    with _jobs_lock:
        _jobs[job_id] = job_data

    # Start background processing
    thread = threading.Thread(
        target=_process_video,
        args=(job_id, video_id),
        daemon=True,
    )
    thread.start()

    return JobStatus(**job_data).model_dump()


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str):
    """Get the status of a subtitle extraction job."""
    with _jobs_lock:
        job_data = _jobs.get(job_id)

    if job_data is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Reconstruct ErrorResponse if error exists
    error = None
    if job_data.get("error"):
        error = ErrorResponse(**job_data["error"])

    return JobStatus(
        job_id=job_data["job_id"],
        video_id=job_data["video_id"],
        status=job_data["status"],
        progress=job_data["progress"],
        error=error,
        cached=job_data.get("cached", False),
    ).model_dump()


@router.get("/{video_id}")
def get_cached_subtitles(video_id: str):
    """Get cached subtitles for a video ID."""
    if not re.match(VIDEO_ID_REGEX, video_id):
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code="INVALID_URL",
                message="Invalid video ID format",
                retryable=False,
            ).model_dump(),
        )

    cached = get_cached(video_id)
    if cached is None:
        raise HTTPException(status_code=404, detail="No cached subtitles found")

    return cached.model_dump()
