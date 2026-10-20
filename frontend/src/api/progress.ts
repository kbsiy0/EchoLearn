import type { VideoProgress } from '../types/subtitle';
import { API_BASE } from './base';
import { throwTypedError } from './errors';

// URL pattern (all three functions):
//   `${API_BASE}/videos/${videoId}/progress`

export async function getProgress(videoId: string): Promise<VideoProgress | null> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`);
  if (res.status === 404) return null;
  if (!res.ok) await throwTypedError(res);
  return res.json() as Promise<VideoProgress>;
}

export interface VideoProgressIn {
  last_played_sec: number;
  last_segment_idx: number;
  playback_rate: number;
  loop_enabled: boolean;
}

export interface PutProgressOptions {
  /**
   * Set true on the unload-flush path (visibilitychange=hidden / beforeunload
   * / unmount). Adds `keepalive: true` so the browser does not cancel the
   * in-flight PUT when the tab closes — crash-survivability gate.
   */
  unload?: boolean;
}

export async function putProgress(
  videoId: string,
  body: VideoProgressIn,
  options: PutProgressOptions = {},
): Promise<void> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    keepalive: options.unload === true,
  });
  if (res.status === 204) return;
  await throwTypedError(res);
}

export async function deleteProgress(videoId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/videos/${videoId}/progress`, {
    method: 'DELETE',
  });
  if (res.status === 204) return;
  await throwTypedError(res);
}
