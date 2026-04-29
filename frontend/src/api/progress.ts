import type { VideoProgress } from '../types/subtitle';
import { API_BASE } from './base';

// URL pattern (all three functions):
//   `${API_BASE}/videos/${videoId}/progress`

export async function getProgress(videoId: string): Promise<VideoProgress | null> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to fetch progress: ${res.status}`);
  return res.json() as Promise<VideoProgress>;
}

export interface VideoProgressIn {
  last_played_sec: number;
  last_segment_idx: number;
  playback_rate: number;
  loop_enabled: boolean;
}

export async function putProgress(videoId: string, body: VideoProgressIn): Promise<void> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 204) return;
  const parsed = await res.json().catch(() => ({})) as Record<string, string>;
  const code = parsed.error_code ?? '';
  const msg = parsed.error_message ?? `HTTP ${res.status}`;
  throw new Error(`${code}: ${msg}`);
}

export async function deleteProgress(videoId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`, {
    method: 'DELETE',
  });
  if (res.status === 204) return;
  const parsed = await res.json().catch(() => ({})) as Record<string, string>;
  const code = parsed.error_code ?? '';
  const msg = parsed.error_message ?? `HTTP ${res.status}`;
  throw new Error(`${code}: ${msg}`);
}
