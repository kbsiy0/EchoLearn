export interface WordTiming {
  text: string;
  start: number;
  end: number;
}

export interface Segment {
  idx: number;
  start: number;
  end: number;
  text_en: string;
  text_zh: string;
  words: WordTiming[];
}

export interface VideoProgress {
  last_played_sec: number;
  last_segment_idx: number;
  playback_rate: number;
  loop_enabled: boolean;
  updated_at: string;
}

export interface VideoSummary {
  video_id: string;
  title: string;
  duration_sec: number;
  created_at: string;
  progress: VideoProgress | null;
}

export interface SubtitleResponse {
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  title: string | null;
  duration_sec: number | null;
  segments: Segment[];
  error_code: string | null;
  error_message: string | null;
}
