export interface WordTiming {
  word: string;
  start: number;
  end: number;
}

export interface SubtitleSegment {
  index: number;
  start: number;
  end: number;
  text_en: string;
  text_zh: string;
  words: WordTiming[];
}

export interface SubtitleResponse {
  video_id: string;
  title: string;
  segments: SubtitleSegment[];
  source: string;
  created_at: string;
}

export interface JobStatus {
  job_id: string;
  video_id: string;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  progress: number;
  error: { code: string; message: string; retryable: boolean } | null;
  cached: boolean;
}
