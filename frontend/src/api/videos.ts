import type { VideoSummary } from '../types/subtitle';
import { API_BASE } from './base';

/**
 * List all videos with their nested progress.
 *
 * Returns null on non-2xx (silently swallow per HomePage's "ignore history
 * fetch errors" UX policy). Network errors throw and are caller-handled.
 */
export async function listVideos(): Promise<VideoSummary[] | null> {
  const res = await fetch(`${API_BASE}/videos`);
  if (!res.ok) return null;
  return res.json() as Promise<VideoSummary[]>;
}
