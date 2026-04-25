"""
T02 — videos_repo unit tests: publish_video (atomic), get_video, list_videos,
get_segments, atomic-publish failure simulation, and video_id regex enforcement.

T04 (Phase 1b) — additional tests for the new streaming-safe methods:
  upsert_video_clear_segments, append_segments, get_video_view.
"""

import json
import uuid
from unittest.mock import patch, call

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
    """Helper: upsert video row and append segments using the Phase 1b pair."""
    repo.upsert_video_clear_segments(
        video_id=video_id,
        title="Rick Astley — Never Gonna Give You Up",
        duration_sec=212.0,
        source="youtube",
    )
    segs = segments if segments is not None else _SAMPLE_SEGMENTS
    if segs:
        repo.append_segments(video_id, segs)


# ---------------------------------------------------------------------------
# upsert_video_clear_segments + append_segments — basic happy path
# (replaces old TestPublishVideo; same behavior contracts, new APIs)
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
        """Reprocessing: upsert_video_clear_segments wipes segments, new ones land."""
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
# Atomic operations — failure simulation
# ---------------------------------------------------------------------------

class TestAtomicPublish:
    def test_upsert_clears_segments_atomically(self, db_conn):
        """upsert_video_clear_segments atomically upserts + clears segments."""
        repo = _make_repo(db_conn)
        _publish(repo)
        assert len(repo.get_segments(VIDEO_ID)) == 2

        # Second upsert clears segments atomically
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="New", duration_sec=5.0, source="youtube"
        )
        assert repo.get_video(VIDEO_ID) is not None
        assert repo.get_segments(VIDEO_ID) == []


# ---------------------------------------------------------------------------
# video_id regex enforcement
# ---------------------------------------------------------------------------

class TestVideoIdRegexVideos:
    @pytest.mark.parametrize("bad_id", ["short", "has/slash......", "", "toolongXXXXXXX"])
    def test_upsert_rejects_bad_video_id(self, db_conn, bad_id):
        repo = _make_repo(db_conn)
        with pytest.raises(Exception):
            repo.upsert_video_clear_segments(
                video_id=bad_id,
                title="Test",
                duration_sec=10.0,
                source="youtube",
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


# ---------------------------------------------------------------------------
# T04 — upsert_video_clear_segments
# ---------------------------------------------------------------------------

def _insert_job(db_conn, video_id=VIDEO_ID, status="processing", progress=50):
    """Helper: insert a job row directly."""
    job_id = str(uuid.uuid4())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, video_id, status, progress, now, now),
    )
    db_conn.commit()
    return job_id


class TestUpsertVideoClearSegments:
    def test_upsert_video_clear_segments_creates_videos_row_and_clears_segments(
        self, db_conn
    ):
        repo = _make_repo(db_conn)
        # Pre-seed a videos row + segments via legacy publish_video
        _publish(repo)
        assert repo.get_segments(VIDEO_ID) != []

        # Act: call the new method
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID,
            title="New Title",
            duration_sec=99.0,
            source="youtube",
        )

        video = repo.get_video(VIDEO_ID)
        assert video is not None
        assert video["title"] == "New Title"
        assert video["duration_sec"] == 99.0
        # segments must be cleared
        assert repo.get_segments(VIDEO_ID) == []

    def test_upsert_is_idempotent_across_resubmission(self, db_conn):
        repo = _make_repo(db_conn)
        # Call twice; second call should succeed and clear any newly-added segments
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="First", duration_sec=10.0, source="youtube"
        )
        # Add a segment between the two calls
        repo.append_segments(VIDEO_ID, [_SAMPLE_SEGMENTS[0]])

        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="Second", duration_sec=20.0, source="youtube"
        )

        video = repo.get_video(VIDEO_ID)
        assert video["title"] == "Second"
        assert video["duration_sec"] == 20.0
        assert repo.get_segments(VIDEO_ID) == []


# ---------------------------------------------------------------------------
# T04 — append_segments
# ---------------------------------------------------------------------------

class TestAppendSegments:
    def test_append_segments_atomic_per_chunk(self, db_conn):
        """A successful batch of 3 rows is committed; an aborted batch leaves nothing."""
        repo = _make_repo(db_conn)
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="T", duration_sec=10.0, source="youtube"
        )

        # Successful batch
        batch = [
            {"idx": 0, "start": 0.0, "end": 1.0, "text_en": "A.", "text_zh": "甲。",
             "words": []},
            {"idx": 1, "start": 1.0, "end": 2.0, "text_en": "B.", "text_zh": "乙。",
             "words": []},
            {"idx": 2, "start": 2.0, "end": 3.0, "text_en": "C.", "text_zh": "丙。",
             "words": []},
        ]
        repo.append_segments(VIDEO_ID, batch)
        assert len(repo.get_segments(VIDEO_ID)) == 3

    def test_append_segments_idx_collision_raises(self, db_conn):
        repo = _make_repo(db_conn)
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="T", duration_sec=10.0, source="youtube"
        )
        seg = {"idx": 0, "start": 0.0, "end": 1.0, "text_en": "A.", "text_zh": "甲。",
               "words": []}
        repo.append_segments(VIDEO_ID, [seg])
        # Second insert with same idx should raise
        with pytest.raises(Exception):
            repo.append_segments(VIDEO_ID, [seg])

    def test_append_segments_collision_in_batch_rolls_back(self, db_conn):
        """Batch with PK collision mid-way must roll back all rows in the batch."""
        repo = _make_repo(db_conn)
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="T", duration_sec=10.0, source="youtube"
        )
        # Append idx=0 successfully first
        repo.append_segments(VIDEO_ID, [
            {"idx": 0, "start": 0.0, "end": 1.0, "text_en": "A.", "text_zh": "甲。",
             "words": []}
        ])

        # Now try a batch where the 2nd row (idx=0) collides — entire batch must roll back
        bad_batch = [
            {"idx": 1, "start": 1.0, "end": 2.0, "text_en": "B.", "text_zh": "乙。",
             "words": []},
            {"idx": 0, "start": 0.0, "end": 1.0, "text_en": "Dup.", "text_zh": "重複。",
             "words": []},  # collision
        ]
        with pytest.raises(Exception):
            repo.append_segments(VIDEO_ID, bad_batch)

        # Only the first pre-existing segment should remain
        segs = repo.get_segments(VIDEO_ID)
        assert len(segs) == 1
        assert segs[0]["idx"] == 0


# ---------------------------------------------------------------------------
# T04 — get_video_view
# ---------------------------------------------------------------------------

class TestGetVideoView:
    def test_get_video_view_returns_none_when_no_job_exists(self, db_conn):
        repo = _make_repo(db_conn)
        assert repo.get_video_view(VIDEO_ID) is None

    def test_get_video_view_reads_latest_job_by_created_at(self, db_conn):
        from datetime import datetime, timezone, timedelta
        repo = _make_repo(db_conn)

        # Insert two jobs; second one is newer
        job_id_old = str(uuid.uuid4())
        job_id_new = str(uuid.uuid4())
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        new_ts = datetime.now(timezone.utc).isoformat()
        db_conn.execute(
            "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)"
            " VALUES (?, ?, 'completed', 100, ?, ?)",
            (job_id_old, VIDEO_ID, old_ts, old_ts),
        )
        db_conn.execute(
            "INSERT INTO jobs (job_id, video_id, status, progress, created_at, updated_at)"
            " VALUES (?, ?, 'processing', 32, ?, ?)",
            (job_id_new, VIDEO_ID, new_ts, new_ts),
        )
        db_conn.commit()

        view = repo.get_video_view(VIDEO_ID)
        assert view is not None
        assert view["status"] == "processing"
        assert view["progress"] == 32

    def test_get_video_view_reads_segments_ordered_by_idx(self, db_conn):
        repo = _make_repo(db_conn)
        _insert_job(db_conn, VIDEO_ID, status="completed", progress=100)
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="T", duration_sec=10.0, source="youtube"
        )
        # Append in reverse order
        repo.append_segments(VIDEO_ID, [
            {"idx": 1, "start": 1.0, "end": 2.0, "text_en": "B.", "text_zh": "乙。",
             "words": []},
        ])
        repo.append_segments(VIDEO_ID, [
            {"idx": 0, "start": 0.0, "end": 1.0, "text_en": "A.", "text_zh": "甲。",
             "words": []},
        ])

        view = repo.get_video_view(VIDEO_ID)
        assert view is not None
        segs = view["segments"]
        assert len(segs) == 2
        assert segs[0]["idx"] == 0
        assert segs[1]["idx"] == 1

    def test_get_video_view_internal_consistency(self, db_conn):
        """Method executes in one transaction — no intermediate COMMIT."""
        from app.repositories import videos_repo as vr_mod
        repo = _make_repo(db_conn)
        _insert_job(db_conn, VIDEO_ID, status="completed", progress=100)

        execute_calls = []

        class SpyConn:
            """Thin proxy that records execute() calls."""
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                execute_calls.append(sql.strip())
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        spy = SpyConn(db_conn)
        spy_repo = vr_mod.VideosRepo(spy)
        spy_repo.get_video_view(VIDEO_ID)

        # Must have BEGIN DEFERRED and no intermediate COMMIT before final COMMIT
        assert any("BEGIN DEFERRED" in s for s in execute_calls)
        begin_idx = next(i for i, s in enumerate(execute_calls) if "BEGIN DEFERRED" in s)
        commit_idx = next(i for i, s in enumerate(execute_calls) if s == "COMMIT")
        assert begin_idx < commit_idx
        # No COMMIT between the BEGIN and the final COMMIT
        intermediate_commits = [
            i for i, s in enumerate(execute_calls)
            if s == "COMMIT" and begin_idx < i < commit_idx
        ]
        assert intermediate_commits == []

    def test_get_video_view_opens_begin_deferred(self, db_conn):
        """Spy on conn.execute: call sequence must be BEGIN DEFERRED → SELECTs → COMMIT."""
        from app.repositories import videos_repo as vr_mod
        repo = _make_repo(db_conn)
        _insert_job(db_conn, VIDEO_ID, status="processing", progress=5)

        execute_calls = []

        class SpyConn:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                execute_calls.append(sql.strip())
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        spy = SpyConn(db_conn)
        spy_repo = vr_mod.VideosRepo(spy)
        spy_repo.get_video_view(VIDEO_ID)

        # Assert BEGIN DEFERRED comes first
        assert execute_calls[0] == "BEGIN DEFERRED"
        # Assert COMMIT is last
        assert execute_calls[-1] == "COMMIT"
        # Three SELECTs in between
        select_calls = [s for s in execute_calls if s.startswith("SELECT")]
        assert len(select_calls) == 3

    def test_get_video_view_emits_rollback_on_read_error(self, db_conn):
        """Inject failure on 2nd SELECT; ROLLBACK must fire and exception re-raise."""
        from app.repositories import videos_repo as vr_mod
        _insert_job(db_conn, VIDEO_ID, status="processing", progress=5)

        call_count = 0
        execute_calls = []

        class SpyAndFailConn:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *args, **kwargs):
                nonlocal call_count
                stripped = sql.strip()
                execute_calls.append(stripped)
                if stripped.startswith("SELECT"):
                    call_count += 1
                    if call_count == 2:
                        raise RuntimeError("injected 2nd SELECT failure")
                return self._real.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        spy = SpyAndFailConn(db_conn)
        spy_repo = vr_mod.VideosRepo(spy)

        with pytest.raises(RuntimeError, match="injected"):
            spy_repo.get_video_view(VIDEO_ID)

        assert any("ROLLBACK" in s for s in execute_calls)


# ---------------------------------------------------------------------------
# T04 — get_video_view decision-table coverage (9 rows from design.md §5)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", [
    # (status, progress, has_video_row, num_segments, error_code, error_message)
    # Row 1: queued, no videos row, no segments
    dict(status="queued", progress=0, has_video=False, num_segs=0,
         error_code=None, error_message=None,
         expected_title=None, expected_duration=None, expected_segs=0),
    # Row 2: processing, no videos row, no segments (early processing)
    dict(status="processing", progress=5, has_video=False, num_segs=0,
         error_code=None, error_message=None,
         expected_title=None, expected_duration=None, expected_segs=0),
    # Row 3: processing, videos row exists, no segments yet
    dict(status="processing", progress=15, has_video=True, num_segs=0,
         error_code=None, error_message=None,
         expected_title="Test Video", expected_duration=200.0, expected_segs=0),
    # Row 4: processing, videos row exists, some segments
    dict(status="processing", progress=32, has_video=True, num_segs=2,
         error_code=None, error_message=None,
         expected_title="Test Video", expected_duration=200.0, expected_segs=2),
    # Row 5: completed, all data
    dict(status="completed", progress=100, has_video=True, num_segs=2,
         error_code=None, error_message=None,
         expected_title="Test Video", expected_duration=200.0, expected_segs=2),
    # Row 6: failed, videos row exists, some segments (partial)
    dict(status="failed", progress=32, has_video=True, num_segs=1,
         error_code="WHISPER_ERROR", error_message="字幕轉錄失敗，請稍後再試",
         expected_title="Test Video", expected_duration=200.0, expected_segs=1),
    # Row 7: failed, videos row exists, no segments
    dict(status="failed", progress=15, has_video=True, num_segs=0,
         error_code="DOWNLOAD_ERROR", error_message="無法下載影片",
         expected_title="Test Video", expected_duration=200.0, expected_segs=0),
    # Row 8: failed, no videos row, no segments
    dict(status="failed", progress=5, has_video=False, num_segs=0,
         error_code="INTERNAL_ERROR", error_message="內部錯誤",
         expected_title=None, expected_duration=None, expected_segs=0),
    # Row 9: failed, no videos row, no segments (VIDEO_TOO_LONG)
    dict(status="failed", progress=5, has_video=False, num_segs=0,
         error_code="VIDEO_TOO_LONG", error_message="影片超過 20 分鐘上限",
         expected_title=None, expected_duration=None, expected_segs=0),
], ids=[
    "queued-no-data",
    "processing-early",
    "processing-video-no-segs",
    "processing-partial-segs",
    "completed-all",
    "failed-partial",
    "failed-video-no-segs",
    "failed-no-video",
    "failed-too-long",
])
def test_get_video_view_decision_table(db_conn, scenario):
    repo = _make_repo(db_conn)

    # Insert job
    job_id = str(uuid.uuid4())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db_conn.execute(
        "INSERT INTO jobs (job_id, video_id, status, progress, error_code, error_message,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, VIDEO_ID, scenario["status"], scenario["progress"],
         scenario["error_code"], scenario["error_message"], now, now),
    )
    db_conn.commit()

    if scenario["has_video"]:
        repo.upsert_video_clear_segments(
            video_id=VIDEO_ID, title="Test Video", duration_sec=200.0, source="youtube"
        )

    if scenario["num_segs"] > 0:
        segs = [
            {"idx": i, "start": float(i), "end": float(i) + 1.0,
             "text_en": f"Seg {i}.", "text_zh": f"段 {i}。", "words": []}
            for i in range(scenario["num_segs"])
        ]
        repo.append_segments(VIDEO_ID, segs)

    view = repo.get_video_view(VIDEO_ID)
    assert view is not None
    assert view["video_id"] == VIDEO_ID
    assert view["status"] == scenario["status"]
    assert view["progress"] == scenario["progress"]
    assert view["title"] == scenario["expected_title"]
    assert view["duration_sec"] == scenario["expected_duration"]
    assert len(view["segments"]) == scenario["expected_segs"]
    assert view["error_code"] == scenario["error_code"]
    assert view["error_message"] == scenario["error_message"]
