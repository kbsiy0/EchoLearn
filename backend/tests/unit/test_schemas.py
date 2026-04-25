"""Unit tests for Pydantic schemas — T05: SubtitleResponse with status/progress/error."""
import json

import pytest
from pydantic import ValidationError

from app.models.schemas import SubtitleResponse


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
