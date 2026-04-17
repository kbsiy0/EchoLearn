"""
T02 — videos_repo unit tests: publish_video (atomic), get_video, list_videos,
get_segments, atomic-publish failure simulation, and video_id regex enforcement.
"""

import json

import pytest


VIDEO_ID = "dQw4w9WgXcQ"
JOB_ID = "job-test-vid01"

_SAMPLE_SEGMENTS = [
    {
        "idx": 0,
        "start": 0.0,
        "end": 3.5,
        "text_en": "Hello world.",
        "text_zh": "你好世界。",
        "words": [
            {"text": "Hello", "start": 0.0, "end": 0.5},
            {"text": "world.", "start": 0.6, "end": 1.0},
        ],
    },
    {
        "idx": 1,
        "start": 4.0,
        "end": 8.0,
        "text_en": "This is a test.",
        "text_zh": "這是一個測試。",
        "words": [
            {"text": "This", "start": 4.0, "end": 4.3},
            {"text": "is", "start": 4.4, "end": 4.6},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(db_conn):
    from app.repositories.videos_repo import VideosRepo
    return VideosRepo(db_conn)


def _publish(repo, video_id=VIDEO_ID, segments=None):
    repo.publish_video(
        video_id=video_id,
        title="Rick Astley — Never Gonna Give You Up",
        duration_sec=212.0,
        source="youtube",
        segments=segments or _SAMPLE_SEGMENTS,
    )


# ---------------------------------------------------------------------------
# publish_video — happy path
# ---------------------------------------------------------------------------

class TestPublishVideo:
    def test_publish_creates_video_row(self, db_conn):
        repo = _make_repo(db_conn)
        _publish(repo)
        video = repo.get_video(VIDEO_ID)
        assert video is not None
        assert video["video_id"] == VIDEO_ID
        assert video["title"] == "Rick Astley — Never Gonna Give You Up"
        assert video["duration_sec"] == 212.0

    def test_publish_creates_segment_rows(self, db_conn):
        repo = _make_repo(db_conn)
        _publish(repo)
        segs = repo.get_segments(VIDEO_ID)
        assert len(segs) == 2
        assert segs[0]["idx"] == 0
        assert segs[0]["text_en"] == "Hello world."
        assert segs[1]["idx"] == 1

    def test_publish_segments_ordered_by_idx(self, db_conn):
        repo = _make_repo(db_conn)
        reversed_segs = list(reversed(_SAMPLE_SEGMENTS))
        _publish(repo, segments=reversed_segs)
        segs = repo.get_segments(VIDEO_ID)
        assert segs[0]["idx"] == 0
        assert segs[1]["idx"] == 1

    def test_publish_words_json_roundtrip(self, db_conn):
        repo = _make_repo(db_conn)
        _publish(repo)
        segs = repo.get_segments(VIDEO_ID)
        words = json.loads(segs[0]["words_json"])
        assert words[0]["text"] == "Hello"
        assert words[0]["start"] == 0.0

    def test_publish_replaces_existing_segments(self, db_conn):
        """Reprocessing: publish twice should replace, not duplicate segments."""
        repo = _make_repo(db_conn)
        _publish(repo)
        new_seg = [{
            "idx": 0,
            "start": 0.0,
            "end": 5.0,
            "text_en": "Updated sentence.",
            "text_zh": "更新的句子。",
            "words": [{"text": "Updated", "start": 0.0, "end": 1.0}],
        }]
        _publish(repo, segments=new_seg)
        segs = repo.get_segments(VIDEO_ID)
        assert len(segs) == 1
        assert segs[0]["text_en"] == "Updated sentence."


# ---------------------------------------------------------------------------
# get_video / list_videos / get_segments
# ---------------------------------------------------------------------------

class TestReadMethods:
    def test_get_video_returns_none_for_unknown(self, db_conn):
        repo = _make_repo(db_conn)
        assert repo.get_video(VIDEO_ID) is None

    def test_list_videos_empty(self, db_conn):
        repo = _make_repo(db_conn)
        assert repo.list_videos() == []

    def test_list_videos_ordered_by_created_at_desc(self, db_conn):
        repo = _make_repo(db_conn)
        vid_a = "aaaaaaaaaaa"
        vid_b = "bbbbbbbbbbb"
        _publish(repo, video_id=vid_a)
        _publish(repo, video_id=vid_b)
        videos = repo.list_videos()
        # Most recently inserted is first
        assert videos[0]["video_id"] == vid_b
        assert videos[1]["video_id"] == vid_a

    def test_get_segments_empty_for_unknown(self, db_conn):
        repo = _make_repo(db_conn)
        assert repo.get_segments(VIDEO_ID) == []


# ---------------------------------------------------------------------------
# Atomic publish — failure simulation via subclass injection
# ---------------------------------------------------------------------------

class TestAtomicPublish:
    def test_failure_mid_publish_leaves_no_rows(self, db_conn):
        """Simulate exception during segment insert.

        We subclass VideosRepo and override _insert_segments to raise after
        the videos upsert.  Because everything is in a single transaction,
        the videos row must also be rolled back.
        """
        from app.repositories.videos_repo import VideosRepo

        class BoomRepo(VideosRepo):
            def _insert_segments(self, conn, video_id, segments):
                raise RuntimeError("simulated segment insert failure")

        repo = BoomRepo(db_conn)
        with pytest.raises(RuntimeError, match="simulated"):
            _publish(repo)

        # Nothing should be persisted
        assert repo.get_video(VIDEO_ID) is None
        assert repo.get_segments(VIDEO_ID) == []


# ---------------------------------------------------------------------------
# video_id regex enforcement
# ---------------------------------------------------------------------------

class TestVideoIdRegexVideos:
    @pytest.mark.parametrize("bad_id", ["short", "has/slash......", "", "toolongXXXXXXX"])
    def test_publish_rejects_bad_video_id(self, db_conn, bad_id):
        repo = _make_repo(db_conn)
        with pytest.raises(Exception):
            repo.publish_video(
                video_id=bad_id,
                title="Test",
                duration_sec=10.0,
                source="youtube",
                segments=[],
            )

    @pytest.mark.parametrize("bad_id", ["short", "has/slash......", "", "toolongXXXXXXX"])
    def test_get_video_rejects_bad_video_id(self, db_conn, bad_id):
        repo = _make_repo(db_conn)
        with pytest.raises(Exception):
            repo.get_video(bad_id)

    @pytest.mark.parametrize("bad_id", ["short", "has/slash......", "", "toolongXXXXXXX"])
    def test_get_segments_rejects_bad_video_id(self, db_conn, bad_id):
        repo = _make_repo(db_conn)
        with pytest.raises(Exception):
            repo.get_segments(bad_id)
