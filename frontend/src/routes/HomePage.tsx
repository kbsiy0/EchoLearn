import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { createJob } from '../api/subtitles';
import { extractVideoId } from '../lib/youtube';
import { useJobPolling } from '../features/jobs/hooks/useJobPolling';
import { URLInput } from '../features/jobs/components/URLInput';
import { LoadingSpinner } from '../features/player/components/LoadingSpinner';

interface VideoSummary {
  video_id: string;
  title: string;
  duration_sec: number;
  created_at: string;
}

const API_BASE = 'http://localhost:8000/api';

export function HomePage() {
  const navigate = useNavigate();
  const [jobId, setJobId] = useState<string | null>(null);
  const [pendingVideoId, setPendingVideoId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoSummary[]>([]);

  const { job } = useJobPolling(jobId);

  // Navigate when job completes
  useEffect(() => {
    if (job?.status === 'completed' && pendingVideoId) {
      navigate(`/watch/${pendingVideoId}`);
    }
    if (job?.status === 'failed') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setError(job.error_message || '處理失敗');
      setLoading(false);
      setJobId(null);
    }
  }, [job, pendingVideoId, navigate]);

  // Fetch video history
  const fetchVideos = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/videos`);
      if (res.ok) setVideos(await res.json());
    } catch {
      // silently ignore history fetch errors
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchVideos();
  }, [fetchVideos]);

  const handleSubmit = useCallback(async (url: string) => {
    setError(null);
    setLoading(true);
    setJobId(null);
    setPendingVideoId(null);

    const vid = extractVideoId(url);
    if (!vid) {
      setError('無效的 YouTube URL');
      setLoading(false);
      return;
    }

    try {
      const result = await createJob(url);
      setPendingVideoId(result.video_id);

      if (result.cached || result.status === 'completed') {
        navigate(`/watch/${result.video_id}`);
        return;
      }

      if (result.job_id) {
        setJobId(result.job_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '請求失敗');
      setLoading(false);
    }
  }, [navigate]);

  const progressText =
    job?.status === 'queued' ? '排隊中...' :
    job?.status === 'processing' ? `處理中 (${job.progress}%)...` :
    '提交中...';

  return (
    <main className="flex-1 flex flex-col overflow-hidden">
      {/* URL input */}
      <div className="px-6 py-4 bg-gray-900 border-b border-gray-800 shrink-0">
        <URLInput onSubmit={handleSubmit} disabled={loading} />
        {error && <p className="mt-2 text-red-400 text-sm">{error}</p>}
      </div>

      {loading && <LoadingSpinner progress={job?.progress ?? 0} status={progressText} />}

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
