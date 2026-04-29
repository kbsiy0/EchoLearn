"""Unit tests for Pydantic schemas — T05 + T03: SubtitleResponse; VideoProgress models."""
import json

import pytest
from pydantic import ValidationError

from app.models.schemas import SubtitleResponse, VideoProgress, VideoProgressIn, VideoSummary
from app.services.errors import ErrorCode


class TestSubtitleResponseCompletedByteCompat:
    """Phase 0 shape byte-compatibility test."""

    def test_subtitle_response_completed_shape_byte_compatible_phase0(self):
        """A completed response, when JSON-dumped, must expose the same Phase 0 keys
        (video_id, title, duration_sec, segments) with identical values.
        A Phase 0-blind consumer that strips unknown keys must still see the right data.
        """
        resp = SubtitleResponse(
            video_id="abc",
            title="Test",
            duration_sec=120.0,
            segments=[],
            status="completed",
            progress=100,
            error_code=None,
            error_message=None,
        )
        data = json.loads(resp.model_dump_json())
        assert data["video_id"] == "abc"
        assert data["title"] == "Test"
        assert data["duration_sec"] == 120.0
        assert data["segments"] == []


class TestSubtitleResponseOptionalFields:
    """title and duration_sec must be optional (nullable) for non-completed states."""

    def test_subtitle_response_processing_allows_null_title_and_duration(self):
        """Processing state: title and duration_sec may be None."""
        resp = SubtitleResponse(
            video_id="xyz",
            title=None,
            duration_sec=None,
            segments=[],
            status="processing",
            progress=10,
        )
        assert resp.title is None
        assert resp.duration_sec is None
        assert resp.status == "processing"


class TestSubtitleResponseFailedState:
    """Failed state with error fields."""

    def test_subtitle_response_failed_accepts_error_fields(self):
        """status='failed' with error_code and error_message is valid."""
        resp = SubtitleResponse(
            video_id="vid1",
            title=None,
            duration_sec=None,
            segments=[],
            status="failed",
            progress=45,
            error_code="WHISPER_ERROR",
            error_message="Whisper transient timeout after 3 retries",
        )
        assert resp.status == "failed"
        assert resp.error_code == "WHISPER_ERROR"
        assert resp.error_message == "Whisper transient timeout after 3 retries"


class TestSubtitleResponseStatusValidation:
    """Literal status field rejects unknown values."""

    def test_subtitle_response_rejects_unknown_status(self):
        """status='done' is not in the allowed Literal union; must raise ValidationError."""
        with pytest.raises(ValidationError):
            SubtitleResponse(
                video_id="vid2",
                title="My Video",
                duration_sec=60.0,
                segments=[],
                status="done",  # invalid
                progress=100,
            )


class TestSubtitleResponseProgressCoercion:
    """progress must be an integer.

    Pydantic v2 rejects floats with fractional parts (e.g. 10.5) even without
    strict mode enabled — the int_from_float rule only allows lossless conversions
    (e.g. 10.0 → 10). A float with a fractional part raises ValidationError.
    This is stricter than Pydantic v1 but is the correct v2 behavior.
    """

    def test_subtitle_response_progress_int_required(self):
        """Pydantic v2 rejects progress=10.5 (fractional float) with ValidationError.
        Unlike Pydantic v1, v2 does NOT silently truncate 10.5 → 10; it raises.
        We assert the rejection to document this stricter behavior.
        """
        with pytest.raises(ValidationError):
            SubtitleResponse(
                video_id="vid3",
                title="Test",
                duration_sec=60.0,
                segments=[],
                status="processing",
                progress=10.5,  # fractional float; must be rejected
            )


# ---------------------------------------------------------------------------
# T03 — VideoProgress + VideoProgressIn + VideoSummary extension
# ---------------------------------------------------------------------------

_PROGRESS_FIXTURE = dict(
    last_played_sec=42.5,
    last_segment_idx=3,
    playback_rate=1.25,
    loop_enabled=True,
    updated_at="2026-04-25T12:00:00Z",
)


class TestVideoProgressRoundTrip:
    """VideoProgress serializes and parses without data loss."""

    def test_video_progress_round_trip(self):
        """Construct, JSON-dump, then parse back — all fields identical."""
        original = VideoProgress(**_PROGRESS_FIXTURE)
        reparsed = VideoProgress.model_validate_json(original.model_dump_json())
        assert reparsed == original
        assert reparsed.last_played_sec == 42.5
        assert reparsed.last_segment_idx == 3
        assert reparsed.playback_rate == 1.25
        assert reparsed.loop_enabled is True
        assert reparsed.updated_at == "2026-04-25T12:00:00Z"


class TestVideoProgressInValidation:
    """VideoProgressIn enforces extra='forbid' and correct field types."""

    def test_video_progress_in_rejects_updated_at_field(self):
        """updated_at is server-stamped; clients must not send it.

        extra='forbid' must raise ValidationError when updated_at is supplied.
        """
        with pytest.raises(ValidationError):
            VideoProgressIn(
                last_played_sec=10.0,
                last_segment_idx=1,
                playback_rate=1.0,
                loop_enabled=False,
                updated_at="2026-04-25T12:00:00Z",  # extra field — must be rejected
            )

    def test_video_progress_in_loop_enabled_must_be_bool(self):
        """loop_enabled='invalid' (non-boolean string) must raise ValidationError.

        Pydantic v2 accepts "yes"/"no"/"true"/"false" as bool aliases but rejects
        arbitrary strings such as 'invalid'. Using 'invalid' as the test value to
        pin genuine failure behavior (spec note: 'yes' is accepted by Pydantic v2).
        """
        with pytest.raises(ValidationError):
            VideoProgressIn(
                last_played_sec=10.0,
                last_segment_idx=1,
                playback_rate=1.0,
                loop_enabled="invalid",  # arbitrary string — must be rejected
            )


class TestVideoSummaryProgressExtension:
    """VideoSummary.progress is optional with default None (Phase 0 compat)."""

    def test_video_summary_progress_defaults_to_none(self):
        """Constructing VideoSummary without 'progress' leaves it None."""
        summary = VideoSummary(
            video_id="vid-abc",
            title="Sample Video",
            duration_sec=180.0,
            created_at="2026-04-25T10:00:00Z",
        )
        assert summary.progress is None

    def test_video_summary_with_explicit_progress_serializes_correctly(self):
        """A VideoSummary constructed with a VideoProgress nests it in JSON output."""
        progress = VideoProgress(**_PROGRESS_FIXTURE)
        summary = VideoSummary(
            video_id="vid-def",
            title="Another Video",
            duration_sec=90.0,
            created_at="2026-04-25T10:00:00Z",
            progress=progress,
        )
        data = json.loads(summary.model_dump_json())
        assert data["progress"]["last_played_sec"] == 42.5
        assert data["progress"]["loop_enabled"] is True
        assert data["progress"]["updated_at"] == "2026-04-25T12:00:00Z"

    def test_video_summary_phase0_consumer_gets_progress_null_when_missing(self):
        """Phase 0 consumers see their four original fields unchanged.

        A VideoSummary with no progress serializes the four Phase 0 keys byte-for-byte
        identically — adding progress=null does not mutate the existing fields.
        """
        summary = VideoSummary(
            video_id="vid-xyz",
            title="Phase0 Video",
            duration_sec=120.0,
            created_at="2026-04-25T09:00:00Z",
        )
        data = json.loads(summary.model_dump_json())
        assert data["video_id"] == "vid-xyz"
        assert data["title"] == "Phase0 Video"
        assert data["duration_sec"] == 120.0
        assert data["created_at"] == "2026-04-25T09:00:00Z"
        assert data["progress"] is None


class TestErrorCodeValidationError:
    """ErrorCode enum must include VALIDATION_ERROR."""

    def test_error_code_validation_error_in_enum(self):
        """ErrorCode.VALIDATION_ERROR must exist and equal the string 'VALIDATION_ERROR'."""
        assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
        assert ErrorCode.VALIDATION_ERROR.value == "VALIDATION_ERROR"
