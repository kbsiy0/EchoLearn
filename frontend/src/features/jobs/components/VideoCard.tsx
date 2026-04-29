import { useState } from 'react';
import type { VideoSummary } from '../../../types/subtitle';

interface VideoCardProps {
  summary: VideoSummary;
  onClick: (videoId: string) => void;
  onReset: (videoId: string) => Promise<void>;
}

export function VideoCard({ summary, onClick, onReset }: VideoCardProps) {
  const [error, setError] = useState<string | null>(null);

  const { video_id, title, duration_sec, created_at, progress } = summary;

  const durationLabel = `${Math.floor(duration_sec / 60)}分${Math.floor(duration_sec % 60)}秒`;
  const dateLabel = new Date(created_at).toLocaleDateString('zh-TW');

  const widthPct = progress
    ? `${(Math.min(1, Math.max(0, progress.last_played_sec / duration_sec)) * 100).toFixed(1)}%`
    : '0.0%';

  const progressPct = progress
    ? Math.round(Math.min(1, Math.max(0, progress.last_played_sec / duration_sec)) * 100)
    : 0;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter') {
      onClick(video_id);
    } else if (e.key === ' ') {
      e.preventDefault();
      onClick(video_id);
    }
  };

  const handleReset = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    setError(null);
    onReset(video_id).catch(() => setError('重置失敗，請稍後再試'));
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onClick(video_id)}
      onKeyDown={handleKeyDown}
      className="w-full text-left px-4 py-3 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors cursor-pointer"
    >
      <p className="text-white text-sm font-medium truncate">{title}</p>
      <p className="text-gray-500 text-xs mt-0.5">
        {durationLabel} · {dateLabel}
      </p>
      {progress && (
        <>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-1 bg-gray-700 rounded">
              <div style={{ width: widthPct }} className="h-1 bg-blue-500 rounded" />
            </div>
            <span className="text-gray-400 text-xs">{progressPct}%</span>
          </div>
          <button
            type="button"
            onClick={handleReset}
            className="mt-1 text-xs text-gray-400 hover:text-white transition-colors"
          >
            重置進度
          </button>
        </>
      )}
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
    </div>
  );
}
