CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  status TEXT CHECK(status IN ('queued','processing','completed','failed')),
  progress INTEGER DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id);

CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  duration_sec REAL NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
  video_id TEXT REFERENCES videos(video_id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  text_en TEXT NOT NULL,
  text_zh TEXT NOT NULL,
  words_json TEXT NOT NULL,
  PRIMARY KEY (video_id, idx)
);

CREATE TABLE IF NOT EXISTS video_progress (
  video_id          TEXT PRIMARY KEY,
  last_played_sec   REAL NOT NULL,
  last_segment_idx  INTEGER NOT NULL,
  playback_rate     REAL NOT NULL,
  loop_enabled      INTEGER NOT NULL,
  updated_at        TEXT NOT NULL,
  FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_progress_updated_at
  ON video_progress(updated_at DESC);
