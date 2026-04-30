import type { SubtitleResponse } from '../types/subtitle';
import { API_BASE } from './base';
import { throwTypedError } from './errors';

export async function createJob(youtubeUrl: string): Promise<{ video_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/subtitles/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: youtubeUrl }),
  });
  if (!res.ok) await throwTypedError(res);
  return res.json();
}

export async function getSubtitles(videoId: string): Promise<SubtitleResponse> {
  const res = await fetch(`${API_BASE}/subtitles/${videoId}`);
  if (!res.ok) await throwTypedError(res);
  return res.json();
}
