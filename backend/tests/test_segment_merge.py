import pytest

from app.services.alignment.word_timing import normalize_segments, estimate_word_timings


class TestNormalizeSegments:
    def test_empty_input(self):
        assert normalize_segments([]) == []

    def test_single_segment(self):
        segments = [{"start": 0.0, "end": 5.0, "text": "Hello world."}]
        result = normalize_segments(segments)
        assert len(result) == 1
        assert result[0]["text"] == "Hello world."

    def test_short_fragments_merged(self):
        """Fragments <1s should always be merged into previous segment."""
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Hello world"},
            {"start": 3.0, "end": 3.5, "text": "yeah"},
            {"start": 3.5, "end": 6.0, "text": "how are you"},
        ]
        result = normalize_segments(segments)
        # "yeah" is <1s, merged into first; then "how are you" merges too (no punctuation, <8s)
        assert len(result) == 1
        assert "yeah" in result[0]["text"]

    def test_sentence_punctuation_splits(self):
        """Segments ending with .!? should split when >= 3s."""
        segments = [
            {"start": 0.0, "end": 4.0, "text": "This is a sentence."},
            {"start": 4.0, "end": 8.0, "text": "Another sentence."},
            {"start": 8.0, "end": 12.0, "text": "Third one."},
        ]
        result = normalize_segments(segments)
        assert len(result) == 3
        assert result[0]["text"] == "This is a sentence."
        assert result[1]["text"] == "Another sentence."
        assert result[2]["text"] == "Third one."

    def test_no_punctuation_merges_until_8s(self):
        """Without punctuation, segments merge until current >= 8s, then force cut on next."""
        segments = [
            {"start": 0.0, "end": 3.0, "text": "so what we are"},
            {"start": 3.0, "end": 6.0, "text": "going to do is"},
            {"start": 6.0, "end": 9.0, "text": "build something cool"},
            {"start": 9.0, "end": 12.0, "text": "and have fun"},
        ]
        result = normalize_segments(segments)
        # After merging first 3, current = 9s (>=8s). Fourth triggers force cut.
        assert len(result) == 2
        assert result[0]["text"] == "so what we are going to do is build something cool"
        assert result[1]["text"] == "and have fun"

    def test_cap_at_15_seconds(self):
        """No merged segment should exceed 15 seconds."""
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Long segment one"},
            {"start": 10.0, "end": 18.0, "text": "Long segment two"},
        ]
        result = normalize_segments(segments)
        # Merging would be 18s which exceeds 15s cap
        assert len(result) == 2

    def test_duration_format_with_duration_key(self):
        """Segments with 'duration' instead of 'end' should work."""
        segments = [
            {"start": 0.0, "duration": 4.0, "text": "Hello."},
            {"start": 4.0, "duration": 4.0, "text": "World."},
        ]
        result = normalize_segments(segments)
        assert len(result) == 2
        assert result[0]["end"] == 4.0
        assert result[1]["end"] == 8.0

    def test_whitespace_only_segments_skipped(self):
        """Segments with only whitespace should be ignored."""
        segments = [
            {"start": 0.0, "end": 3.0, "text": "Hello"},
            {"start": 3.0, "end": 5.0, "text": "   "},
            {"start": 5.0, "end": 8.0, "text": "world"},
        ]
        result = normalize_segments(segments)
        # No punctuation, so they merge into one
        assert all("Hello" in seg["text"] or "world" in seg["text"] for seg in result)

    def test_youtube_style_fragments(self):
        """Typical YouTube transcript fragments should merge into sentences."""
        segments = [
            {"start": 0.0, "end": 2.0, "text": "so today we're going to"},
            {"start": 2.0, "end": 4.0, "text": "talk about something really"},
            {"start": 4.0, "end": 6.5, "text": "important."},
            {"start": 6.5, "end": 9.0, "text": "Let me show you how"},
            {"start": 9.0, "end": 11.0, "text": "it works."},
        ]
        result = normalize_segments(segments)
        # First sentence ends at "important." (6.5s, has punct, >=3s) → split
        # Second sentence "Let me show you how it works." → split
        assert len(result) == 2
        assert result[0]["text"] == "so today we're going to talk about something really important."
        assert result[1]["text"] == "Let me show you how it works."


class TestEstimateWordTimings:
    def test_single_word(self):
        result = estimate_word_timings("Hello", 0.0, 1.0)
        assert len(result) == 1
        assert result[0]["word"] == "Hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 1.0

    def test_multiple_words(self):
        result = estimate_word_timings("Hello world", 0.0, 2.0)
        assert len(result) == 2
        assert result[0]["word"] == "Hello"
        assert result[1]["word"] == "world"
        assert result[0]["end"] == result[1]["start"]
        assert result[1]["end"] == 2.0

    def test_empty_text(self):
        result = estimate_word_timings("", 0.0, 1.0)
        assert result == []

    def test_zero_duration(self):
        result = estimate_word_timings("Hello world", 5.0, 5.0)
        assert len(result) == 2
        assert all(w["start"] == 5.0 and w["end"] == 5.0 for w in result)

    def test_punctuation_token(self):
        """Punctuation-only tokens should get zero weight."""
        result = estimate_word_timings("Hello , world", 0.0, 3.0)
        assert len(result) == 3
        comma = result[1]
        assert comma["word"] == ","
        assert comma["end"] - comma["start"] < 0.01

    def test_precision_three_decimals(self):
        result = estimate_word_timings("The quick brown fox", 0.0, 1.0)
        for w in result:
            assert w["start"] == round(w["start"], 3)
            assert w["end"] == round(w["end"], 3)

    def test_last_word_ends_at_segment_end(self):
        result = estimate_word_timings("This is a test sentence", 1.5, 4.7)
        assert result[-1]["end"] == round(4.7, 3)

    def test_all_punctuation(self):
        """All punctuation tokens should distribute evenly."""
        result = estimate_word_timings("... !!!", 0.0, 1.0)
        assert len(result) == 2
        assert result[-1]["end"] == 1.0
