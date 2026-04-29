import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../api/base';
import { createJob } from '../api/subtitles';
import { deleteProgress } from '../api/progress';
import { extractVideoId } from '../lib/youtube';
import { URLInput } from '../features/jobs/components/URLInput';
import { VideoCard } from '../features/jobs/components/VideoCard';
import type { VideoSummary } from '../types/subtitle';

async function fetchVideos(): Promise<VideoSummary[] | null> {
  const res = await fetch(`${API_BASE}/videos`);
  if (!res.ok) return null;
  return res.json() as Promise<VideoSummary[]>;
}

export function HomePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchVideos()
      .then((data) => {
        if (!cancelled && data) setVideos(data);
      })
      .catch(() => {
        // silently ignore history fetch errors
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = useCallback(async (url: string) => {
    setError(null);
    setLoading(true);

    const vid = extractVideoId(url);
    if (!vid) {
      setError('無效的 YouTube URL');
      setLoading(false);
      return;
    }

    try {
      const result = await createJob(url);
      navigate(`/watch/${result.video_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '請求失敗');
      setLoading(false);
    }
  }, [navigate]);

  const handleReset = useCallback(async (videoId: string): Promise<void> => {
    await deleteProgress(videoId);
    // Refetch after successful DELETE; on failure keep local state (DELETE
    // already succeeded server-side, only the refresh failed). fetchVideos
    // returns null on non-2xx, throws only on network error — both count as
    // "refetch failed" for the staleness contract.
    let data: VideoSummary[] | null;
    try {
      data = await fetchVideos();
    } catch {
      data = null;
    }
    if (data) {
      setVideos(data);
    } else {
      console.warn('HomePage: refetch after reset failed — keeping stale list');
    }
  }, []);

  return (
    <main className="flex-1 flex flex-col overflow-hidden">
      {/* URL input */}
      <div className="px-6 py-4 bg-gray-900 border-b border-gray-800 shrink-0">
        <URLInput onSubmit={handleSubmit} disabled={loading} />
        {error && <p className="mt-2 text-red-400 text-sm">{error}</p>}
      </div>

      {!loading && (
        <div className="flex-1 overflow-y-auto p-6">
          {videos.length === 0 ? (
            <p className="text-gray-500 text-lg text-center mt-12">貼上 YouTube URL 開始學習</p>
          ) : (
            <>
              <h2 className="text-gray-300 text-sm font-medium mb-4">最近觀看</h2>
              <ul className="space-y-2">
                {videos.map((v) => (
                  <li key={v.video_id}>
                    <VideoCard
                      summary={v}
                      onClick={(id) => navigate(`/watch/${id}`)}
                      onReset={handleReset}
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </main>
  );
}
