import type { SubtitleResponse } from '../types/subtitle';
import { API_BASE } from './base';

export async function createJob(youtubeUrl: string): Promise<{ video_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/subtitles/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: youtubeUrl }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail?.message || err.detail || 'Failed to create job');
  }
  return res.json();
}

export async function getSubtitles(videoId: string): Promise<SubtitleResponse> {
  const res = await fetch(`${API_BASE}/subtitles/${videoId}`);
  if (!res.ok) throw new Error(`Failed to fetch subtitles: ${res.status}`);
  return res.json();
}
