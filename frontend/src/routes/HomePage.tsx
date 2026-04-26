import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { createJob } from '../api/subtitles';
import { extractVideoId } from '../lib/youtube';
import { URLInput } from '../features/jobs/components/URLInput';

interface VideoSummary {
  video_id: string;
  title: string;
  duration_sec: number;
  created_at: string;
}

const API_BASE = 'http://localhost:8000/api';

export function HomePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/videos`)
      .then((res) => (res.ok ? res.json() : null))
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
                    <button
                      onClick={() => navigate(`/watch/${v.video_id}`)}
                      className="w-full text-left px-4 py-3 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <p className="text-white text-sm font-medium truncate">{v.title}</p>
                      <p className="text-gray-500 text-xs mt-0.5">
                        {Math.floor(v.duration_sec / 60)}分{Math.floor(v.duration_sec % 60)}秒
                        · {new Date(v.created_at).toLocaleDateString('zh-TW')}
                      </p>
                    </button>
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
