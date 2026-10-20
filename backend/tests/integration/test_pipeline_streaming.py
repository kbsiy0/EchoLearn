"""Integration tests for T06 — Pipeline.run per-chunk streaming loop.

Uses FakeWhisperClient with per-chunk scripts, FakeTranslator, mocked
subprocess.run (no real ffmpeg), and real audio_chunking.compute_schedule.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest

from app.repositories.jobs_repo import JobsRepo
from app.repositories.videos_repo import VideosRepo
from app.services.pipeline import Pipeline
from app.services.transcription.audio_chunking import compute_schedule
from app.services.transcription.whisper import WhisperTransientError
from app.services.transcription.youtube_audio import PipelineError, VideoMetadata


# ---------------------------------------------------------------------------
# Video IDs and basic fixtures
# ---------------------------------------------------------------------------

VIDEO_ID = "dQw4w9WgXcQ"   # 11-char valid


def _make_metadata(duration_sec: float = 1200.0) -> VideoMetadata:
    return VideoMetadata(
        video_id=VIDEO_ID,
        title="Test Video",
        duration_sec=duration_sec,
        source="whisper",
    )


def _create_job(db_conn, video_id: str = VIDEO_ID) -> str:
    job_id = str(uuid.uuid4())
    JobsRepo(db_conn).create(job_id, video_id)
    return job_id


# ---------------------------------------------------------------------------
# Scripted fakes for per-chunk tests
# ---------------------------------------------------------------------------

class ScriptedWhisperClient:
    """Returns different word lists for successive transcribe() calls.

    Pass a list of (words_or_exception) per chunk call. If a list element is an
    Exception it is raised; otherwise it is returned as the word list.
    Repeats the last element indefinitely once exhausted.
    """

    def __init__(self, script: list) -> None:
        self._script = script
        self._index = 0
        self.call_count = 0
        self.call_args: list[Path] = []

    def transcribe(self, audio_path: Path):
        self.call_count += 1
        self.call_args.append(audio_path)
        idx = min(self._index, len(self._script) - 1)
        item = self._script[idx]
        self._index += 1
        if isinstance(item, Exception):
            raise item
        return list(item)


class FakeTranslator:
    """Returns 'TR_<text>' for each input text."""

    def translate_batch(self, texts_en: list[str]) -> list[str]:
        return [f"TR_{t}" for t in texts_en]


# ---------------------------------------------------------------------------
# Pipeline factory helpers
# ---------------------------------------------------------------------------

def _make_pipeline(
    db_conn,
    whisper,
    translator=None,
    duration_sec: float = 1200.0,
    tmp_path: Optional[Path] = None,
    extract_chunk_fn=None,
) -> Pipeline:
    """Build a Pipeline with injected fakes and mocked download/probe."""
    if translator is None:
        translator = FakeTranslator()

    audio_path = (tmp_path or Path("/tmp")) / f"{VIDEO_ID}.mp3"

    def fake_probe(url: str) -> VideoMetadata:
        return _make_metadata(duration_sec)

    def fake_download(video_id: str) -> Path:
        # Ensure the audio file "exists" for the pipeline
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"fake-audio")
        return audio_path

    pipeline = Pipeline(
        db_conn=db_conn,
        whisper=whisper,
        translator=translator,
        probe_fn=fake_probe,
        download_fn=fake_download,
        extract_chunk_fn=extract_chunk_fn,
    )
    return pipeline


def _make_words_for_chunk(chunk_idx: int, n: int = 2) -> list[dict]:
    """Generate n words local to a chunk, properly terminated."""
    base_time = float(chunk_idx)  # local time starts near 0
    words = []
    for i in range(n - 1):
        words.append({"text": f"word{chunk_idx}_{i}", "start": base_time + i * 0.5, "end": base_time + i * 0.5 + 0.4})
    # Last word with period to terminate sentence
    words.append({"text": f"end{chunk_idx}.", "start": base_time + (n - 1) * 0.5, "end": base_time + (n - 1) * 0.5 + 0.5})
    return words


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_five_chunk_happy_path_produces_monotone_segments(
        self, db_conn, tmp_path, monkeypatch
    ):
        """1200s video → 5 chunks; final segments have monotone idx with no gaps."""
        # Build per-chunk word scripts (each chunk returns terminated words)
        specs = compute_schedule(1200.0)
        assert len(specs) == 5

        scripts = []
        for spec in specs:
            # Words local to this chunk (Whisper sees local time starting near 0)
            words = [
                {"text": f"w{spec.chunk_idx}a", "start": 0.5, "end": 1.0},
                {"text": f"end{spec.chunk_idx}.", "start": 4.0, "end": 4.5},
            ]
            scripts.append(words)

        whisper = ScriptedWhisperClient(scripts)
        monkeypatch.setattr("subprocess.run", MagicMock())

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed", f"Expected completed, got {job['status']}: {job['error_message']}"
        assert job["progress"] == 100

        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        assert len(segments) >= 5
        for i, seg in enumerate(segments):
            assert seg["idx"] == i, f"idx gap at position {i}: got {seg['idx']}"

    def test_pipeline_single_chunk_for_short_video(
        self, db_conn, tmp_path, monkeypatch
    ):
        """45s video → exactly one chunk iteration."""
        whisper = ScriptedWhisperClient([[
            {"text": "Hello", "start": 0.0, "end": 1.0},
            {"text": "world.", "start": 1.5, "end": 2.0},
        ]])
        monkeypatch.setattr("subprocess.run", MagicMock())

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=45.0, tmp_path=tmp_path).run(job_id)

        assert whisper.call_count == 1
        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"
        assert job["progress"] == 100


# ---------------------------------------------------------------------------
# Tests: progress tracking
# ---------------------------------------------------------------------------

class TestProgress:
    def test_progress_advances_through_probe_download_chunks(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Progress: probe=5, download=15, each chunk k → 15 + (k+1)*85//N."""
        n_chunks = 5
        duration_sec = 1200.0
        specs = compute_schedule(duration_sec)
        assert len(specs) == n_chunks

        scripts = []
        for spec in specs:
            scripts.append([
                {"text": f"w{spec.chunk_idx}.", "start": 0.5, "end": 4.0},
            ])

        whisper = ScriptedWhisperClient(scripts)
        progress_snapshots: list[int] = []
        real_jobs_repo_update_progress = JobsRepo.update_progress

        def spy_update_progress(self_inner, job_id, value):
            progress_snapshots.append(value)
            real_jobs_repo_update_progress(self_inner, job_id, value)

        monkeypatch.setattr(JobsRepo, "update_progress", spy_update_progress)
        monkeypatch.setattr("subprocess.run", MagicMock())

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=duration_sec, tmp_path=tmp_path).run(job_id)

        expected = [5, 15] + [
            15 + (k + 1) * 85 // n_chunks for k in range(n_chunks)
        ]
        assert progress_snapshots == expected

    def test_update_progress_is_noop_after_failed(
        self, db_conn, tmp_path, monkeypatch
    ):
        """After job is failed, update_progress must not advance the progress column."""
        # Make chunk 0 succeed but chunk 1 fail permanently
        scripts = [
            [{"text": "ok.", "start": 0.5, "end": 4.0}],  # chunk 0 success
            WhisperTransientError(),                         # chunk 1 attempt 1
            WhisperTransientError(),                         # chunk 1 attempt 2
            WhisperTransientError(),                         # chunk 1 attempt 3
        ]
        whisper = ScriptedWhisperClient(scripts)
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        job_id = _create_job(db_conn)
        # 1200s has 5 chunks; after chunk 0 fails at chunk 1 → progress from chunk 0 stays
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        progress_after_fail = job["progress"]

        # Any further update_progress should be a no-op
        JobsRepo(db_conn).update_progress(job_id, 99)
        job2 = JobsRepo(db_conn).get(job_id)
        assert job2["progress"] == progress_after_fail


# ---------------------------------------------------------------------------
# Tests: retry logic
# ---------------------------------------------------------------------------

class TestRetry:
    def test_chunk_retry_twice_then_succeeds(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Chunk 1 fails transiently twice, succeeds on attempt 3; job completes."""
        sleep_calls = []
        monkeypatch.setattr("time.sleep", lambda d: sleep_calls.append(d))
        monkeypatch.setattr("subprocess.run", MagicMock())

        scripts = [
            # chunk 0: success
            [{"text": "first.", "start": 0.5, "end": 4.0}],
            # chunk 1 attempts
            WhisperTransientError(),   # attempt 1 → sleep 1s
            WhisperTransientError(),   # attempt 2 → sleep 2s
            [{"text": "second.", "start": 0.5, "end": 4.0}],  # attempt 3 success
            # chunks 2-4: success
            [{"text": "third.", "start": 0.5, "end": 4.0}],
            [{"text": "fourth.", "start": 0.5, "end": 4.0}],
            [{"text": "fifth.", "start": 0.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"
        # Backoff should be 1s then 2s for chunk 1
        assert 1 in sleep_calls
        assert 2 in sleep_calls

    def test_chunk_three_failures_marks_job_failed_with_partial(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Chunk 1 exhausts 3 attempts → job failed; chunk 0's segments retained."""
        monkeypatch.setattr("time.sleep", lambda _: None)
        monkeypatch.setattr("subprocess.run", MagicMock())

        scripts = [
            [{"text": "chunk0.", "start": 0.5, "end": 4.0}],  # chunk 0 OK
            WhisperTransientError(),  # chunk 1 attempt 1
            WhisperTransientError(),  # chunk 1 attempt 2
            WhisperTransientError(),  # chunk 1 attempt 3
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        assert job["error_code"] == "WHISPER_ERROR"

        # chunk 0 segments must remain
        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        assert len(segments) >= 1

    def test_non_retry_eligible_error_bubbles_on_first_occurrence(
        self, db_conn, tmp_path, monkeypatch
    ):
        """HTTP 4xx non-429 (non-retry-eligible) fails immediately, no sleep."""
        sleep_calls = []
        monkeypatch.setattr("time.sleep", lambda d: sleep_calls.append(d))
        monkeypatch.setattr("subprocess.run", MagicMock())

        # ValueError is non-retry-eligible
        scripts = [
            [{"text": "chunk0.", "start": 0.5, "end": 4.0}],
            ValueError("bad audio format"),  # chunk 1: non-transient
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        # No retry sleep should occur for non-transient errors
        assert sleep_calls == []

    def test_rate_limit_with_retry_after_header_honored(
        self, db_conn, tmp_path, monkeypatch
    ):
        """RateLimitError with retry_after=5 → sleep(5), not default 1s."""
        sleep_calls = []
        monkeypatch.setattr("time.sleep", lambda d: sleep_calls.append(d))
        monkeypatch.setattr("subprocess.run", MagicMock())

        scripts = [
            [{"text": "chunk0.", "start": 0.5, "end": 4.0}],
            WhisperTransientError(retry_after=5),  # chunk 1 attempt 1
            [{"text": "chunk1.", "start": 0.5, "end": 4.0}],  # attempt 2 success
            [{"text": "chunk2.", "start": 0.5, "end": 4.0}],
            [{"text": "chunk3.", "start": 0.5, "end": 4.0}],
            [{"text": "chunk4.", "start": 0.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        assert 5 in sleep_calls, f"Expected sleep(5) for retry_after=5, got {sleep_calls}"
        assert 1 not in sleep_calls, f"Should not use default 1s backoff when retry_after is set"

    def test_rate_limit_retry_after_cap(
        self, db_conn, tmp_path, monkeypatch
    ):
        """retry_after=120 is capped to 30s."""
        sleep_calls = []
        monkeypatch.setattr("time.sleep", lambda d: sleep_calls.append(d))
        monkeypatch.setattr("subprocess.run", MagicMock())

        scripts = [
            [{"text": "chunk0.", "start": 0.5, "end": 4.0}],
            WhisperTransientError(retry_after=120),  # chunk 1 attempt 1
            [{"text": "chunk1.", "start": 0.5, "end": 4.0}],
            [{"text": "chunk2.", "start": 0.5, "end": 4.0}],
            [{"text": "chunk3.", "start": 0.5, "end": 4.0}],
            [{"text": "chunk4.", "start": 0.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        assert 30 in sleep_calls, f"Expected sleep(30) for capped retry_after=120, got {sleep_calls}"
        assert 120 not in sleep_calls


# ---------------------------------------------------------------------------
# Tests: silent chunk handling
# ---------------------------------------------------------------------------

class TestSilentChunk:
    def test_silent_chunk_empty_whisper_does_not_crash_pipeline(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Empty Whisper result on chunk 2 (no carryover) → no crash, progress advances."""
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        scripts = [
            [{"text": "chunk0.", "start": 0.5, "end": 4.0}],  # chunk 0
            [{"text": "chunk1.", "start": 0.5, "end": 4.0}],  # chunk 1
            [],  # chunk 2: silent
            [{"text": "chunk3.", "start": 0.5, "end": 4.0}],  # chunk 3
            [{"text": "chunk4.", "start": 0.5, "end": 4.0}],  # chunk 4
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"

    def test_silent_chunk_preserves_carryover(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Empty chunk 2 with non-empty carryover from chunk 1 → carryover carries through."""
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        # Chunk 1 ends without terminator (open sentence → will be in carryover)
        # Chunk 2 is empty → carryover must survive intact
        # Chunk 3 terminates the sentence
        scripts = [
            # chunk 0: fully terminated
            [{"text": "intro.", "start": 0.5, "end": 4.0}],
            # chunk 1: ends without terminator → carryover
            [{"text": "open", "start": 0.5, "end": 1.0},
             {"text": "sentence", "start": 1.5, "end": 4.0}],
            # chunk 2: silence
            [],
            # chunk 3: terminates the carried sentence
            [{"text": "ends.", "start": 0.5, "end": 4.0}],
            # chunk 4
            [{"text": "done.", "start": 0.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=1200.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"


# ---------------------------------------------------------------------------
# Tests: timestamp offset
# ---------------------------------------------------------------------------

class TestTimestampOffset:
    def test_chunk_timestamps_are_video_absolute_not_local(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Whisper chunk-local timestamps must be offset by audio_start_sec."""
        # For 90s video: chunk 1 has audio_start_sec=57
        # Whisper returns word at local start=0.5 → video-absolute should be 57.5
        monkeypatch.setattr("subprocess.run", MagicMock())

        specs = compute_schedule(90.0)
        assert len(specs) == 2
        chunk1_spec = specs[1]
        assert chunk1_spec.audio_start_sec == 57.0

        # chunk 1 has audio_start_sec=57, valid_start_sec=60, valid_end_sec=90
        # Whisper returns local word at start=3.5 → offset → 57+3.5=60.5 (> valid_start=60 ✓)
        scripts = [
            # chunk 0
            [{"text": "first.", "start": 0.5, "end": 4.0}],
            # chunk 1: local word at start=3.5 → video-absolute 57+3.5=60.5
            [{"text": "local.", "start": 3.5, "end": 7.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=90.0, tmp_path=tmp_path).run(job_id)

        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        import json
        chunk1_segs = [s for s in segments if s["start_sec"] >= 60.0]
        assert len(chunk1_segs) >= 1, "Expected segments from chunk 1 with video-absolute timestamps"
        # Find the segment with the local word
        found_words = []
        for seg in chunk1_segs:
            words = json.loads(seg["words_json"])
            found_words.extend(words)
        starts = [w["start"] for w in found_words]
        assert any(abs(s - 60.5) < 0.01 for s in starts), (
            f"Expected video-absolute start ~60.5 but got: {starts}"
        )


# ---------------------------------------------------------------------------
# Tests: sentence carryover across boundaries
# ---------------------------------------------------------------------------

class TestSentenceCarryover:
    def test_sentence_held_across_boundary_preserves_original_timestamps(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Open sentence from chunk 0 is carried; its timestamps come from chunk 0."""
        monkeypatch.setattr("subprocess.run", MagicMock())

        # 90s video → 2 chunks
        # Chunk 0: words that form an open sentence with timestamps starting at ~58s
        # (valid_start=0, valid_end=60)
        # We use words in valid range of chunk 0
        scripts = [
            # chunk 0: open sentence (no terminator)
            [{"text": "open", "start": 58.0, "end": 58.5},
             {"text": "sentence", "start": 58.8, "end": 59.5}],
            # chunk 1: terminates the sentence; local word at 3.5 → 57+3.5=60.5 absolute
            [{"text": "done.", "start": 3.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=90.0, tmp_path=tmp_path).run(job_id)

        import json
        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        # Find a segment that contains "open" word — it should have original timestamp ~58
        found_open_word = False
        for seg in segments:
            words = json.loads(seg["words_json"])
            for w in words:
                if "open" in w.get("text", ""):
                    assert abs(w["start"] - 58.0) < 0.01, (
                        f"Expected original chunk-0 timestamp ~58 but got {w['start']}"
                    )
                    found_open_word = True
        # The carryover MUST preserve the open sentence; if it didn't, the test
        # is vacuously passing on the status check alone (spec-reviewer T06 nit Q1).
        assert found_open_word, (
            "carryover did not preserve the open sentence — invariant 4 violated"
        )
        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"

    def test_no_duplicate_word_at_chunk_boundary(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Word at boundary [59.8, 60.3] appears in DB exactly once."""
        monkeypatch.setattr("subprocess.run", MagicMock())

        # 90s video → 2 chunks; boundary word at start=59.8
        # Chunk 0 valid_end=60: word at 59.8 is retained (59.8 <= 60)
        # Chunk 1 valid_start=60: word at 59.8 is excluded (59.8 not > 60) — already in chunk 0
        scripts = [
            # chunk 0: has a boundary word at 59.8 (video-absolute after offset 0)
            [{"text": "boundary", "start": 59.8, "end": 60.3},
             {"text": "next.", "start": 60.0, "end": 60.5}],
            # chunk 1: overlap region might re-transcribe the boundary word; clip removes it
            [{"text": "boundary", "start": 0.8, "end": 1.3},   # local=0.8 → abs=57.8 < 60
             {"text": "after.", "start": 4.0, "end": 4.5}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=90.0, tmp_path=tmp_path).run(job_id)

        import json
        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        boundary_count = 0
        for seg in segments:
            words = json.loads(seg["words_json"])
            for w in words:
                if "boundary" in w.get("text", "") and abs(w["start"] - 59.8) < 0.1:
                    boundary_count += 1
        assert boundary_count <= 1, (
            f"Word 'boundary' at ~59.8 should appear at most once, got {boundary_count}"
        )

    def test_end_of_stream_flushes_unterminated_final_sentence(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Final chunk ending without .!? is still appended via end-of-stream flush."""
        monkeypatch.setattr("subprocess.run", MagicMock())

        # 45s single-chunk video; words have no terminator
        scripts = [
            [{"text": "no", "start": 0.5, "end": 1.0},
             {"text": "terminator", "start": 1.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=45.0, tmp_path=tmp_path).run(job_id)

        segments = VideosRepo(db_conn).get_segments(VIDEO_ID)
        assert len(segments) >= 1, "End-of-stream flush must emit the unterminated final sentence"
        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"


# ---------------------------------------------------------------------------
# Tests: error sanitization
# ---------------------------------------------------------------------------

class TestErrorSanitization:
    def test_error_message_is_sanitized(
        self, db_conn, tmp_path, monkeypatch, caplog
    ):
        """Raw exception with sk- key fragment must NOT appear in DB; canonical string must."""
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        raw_message = "Incorrect API key provided: sk-abcd1234..."

        class ApiKeyLeakError(Exception):
            pass

        scripts = [
            ApiKeyLeakError(raw_message),  # chunk 0 attempt 1 — non-transient, bubbles
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        with caplog.at_level(logging.WARNING):
            _make_pipeline(db_conn, whisper, duration_sec=45.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        # DB must contain the safe message, NOT the raw sk- fragment
        assert "sk-" not in (job["error_message"] or ""), (
            f"Raw API key leaked into DB: {job['error_message']}"
        )
        # Canonical message must be in DB
        from app.services.errors import SAFE_MESSAGES
        assert job["error_message"] in SAFE_MESSAGES.values(), (
            f"DB error_message '{job['error_message']}' is not a canonical safe message"
        )
        # Raw message must appear in log records only
        raw_in_log = any(raw_message in r.message for r in caplog.records)
        assert raw_in_log, "Raw exception text must appear in logger output"


# ---------------------------------------------------------------------------
# Tests: chunk_dir path and cleanup
# ---------------------------------------------------------------------------

class TestChunkDirCleanup:
    def test_chunk_dir_is_under_data_audio(
        self, db_conn, tmp_path, monkeypatch
    ):
        """extract_chunk must be called with out_dir == Path('data/audio') / f'chunks_{VIDEO_ID}'."""
        chunk_dir_calls: list[Path] = []

        def fake_extract_chunk(source_audio, spec, out_dir):
            chunk_dir_calls.append(out_dir)
            # Create dummy file so pipeline can unlink it
            out_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = out_dir / f"chunk_{spec.chunk_idx:02d}.mp3"
            chunk_path.write_bytes(b"")
            return chunk_path

        monkeypatch.setattr("time.sleep", lambda _: None)

        scripts = [
            [{"text": "done.", "start": 0.5, "end": 4.0}],
        ]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(
            db_conn, whisper, duration_sec=45.0, tmp_path=tmp_path,
            extract_chunk_fn=fake_extract_chunk,
        ).run(job_id)

        from app.services.transcription.youtube_audio import AUDIO_DIR
        expected_chunk_dir = AUDIO_DIR / f"chunks_{VIDEO_ID}"
        assert all(p == expected_chunk_dir for p in chunk_dir_calls), (
            f"Expected chunk_dir={expected_chunk_dir}, got {chunk_dir_calls}"
        )

    def test_audio_files_deleted_on_completed(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Source audio is unlinked on the completed terminal state."""
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        deleted_paths: list[Path] = []
        real_unlink = Path.unlink

        def spy_unlink(self_path, *args, **kwargs):
            deleted_paths.append(self_path)
            if self_path.exists():
                real_unlink(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", spy_unlink)

        scripts = [[{"text": "ok.", "start": 0.5, "end": 4.0}]]
        whisper = ScriptedWhisperClient(scripts)

        job_id = _create_job(db_conn)
        _make_pipeline(db_conn, whisper, duration_sec=45.0, tmp_path=tmp_path).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "completed"
        assert any(str(VIDEO_ID) in str(p) for p in deleted_paths), (
            f"Source audio not deleted; unlinked: {deleted_paths}"
        )

    def test_audio_files_deleted_on_failed(
        self, db_conn, tmp_path, monkeypatch
    ):
        """Source audio is unlinked on the failed terminal state too.

        T06 spec-reviewer Q2: the original combined test only exercised the
        completed path. Failed path needs its own assertion.
        """
        monkeypatch.setattr("subprocess.run", MagicMock())
        monkeypatch.setattr("time.sleep", lambda _: None)

        deleted_paths: list[Path] = []
        real_unlink = Path.unlink

        def spy_unlink(self_path, *args, **kwargs):
            deleted_paths.append(self_path)
            if self_path.exists():
                real_unlink(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", spy_unlink)

        # Force a non-retry-eligible failure on the first chunk (raises a plain
        # Exception, not WhisperTransientError, so no retries).
        class FailingWhisper:
            def transcribe(self, _path):
                raise RuntimeError("simulated non-transient failure")

        job_id = _create_job(db_conn)
        _make_pipeline(
            db_conn, FailingWhisper(), duration_sec=45.0, tmp_path=tmp_path,
        ).run(job_id)

        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        assert any(str(VIDEO_ID) in str(p) for p in deleted_paths), (
            f"Source audio not deleted on failed path; unlinked: {deleted_paths}"
        )


# ---------------------------------------------------------------------------
# Tests: VIDEO_TOO_LONG guard
# ---------------------------------------------------------------------------

class TestVideoTooLong:
    def test_video_too_long_raises_before_download(
        self, db_conn, tmp_path, monkeypatch
    ):
        """21-minute video → probe raises VIDEO_TOO_LONG; download NOT called."""
        download_called = []

        def fake_probe_too_long(url: str) -> VideoMetadata:
            # Mimic probe_metadata raising for a 21-minute video
            raise PipelineError(
                "VIDEO_TOO_LONG",
                f"Video is 21.0 min, max is 20 min",
            )

        def spy_download(video_id: str) -> Path:
            download_called.append(video_id)
            audio = tmp_path / f"{video_id}.mp3"
            audio.write_bytes(b"")
            return audio

        whisper = ScriptedWhisperClient([[]])
        pipeline = Pipeline(
            db_conn=db_conn,
            whisper=whisper,
            translator=FakeTranslator(),
            probe_fn=fake_probe_too_long,
            download_fn=spy_download,
        )

        job_id = _create_job(db_conn)
        pipeline.run(job_id)

        assert download_called == [], "download must NOT be called when VIDEO_TOO_LONG"
        job = JobsRepo(db_conn).get(job_id)
        assert job["status"] == "failed"
        assert job["error_code"] == "VIDEO_TOO_LONG"
