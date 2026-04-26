export interface WordTiming {
  text: string;
  start: number;
  end: number;
}

export interface SubtitleSegment {
  idx: number;
  start: number;
  end: number;
  text_en: string;
  text_zh: string;
  words: WordTiming[];
}

export interface SubtitleResponse {
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  title: string | null;
  duration_sec: number | null;
  segments: SubtitleSegment[];
  error_code: string | null;
  error_message: string | null;
}

export interface JobStatus {
  job_id: string;
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  error: { code: string; message: string; retryable: boolean } | null;
  cached: boolean;
}
