import { useState, useEffect, useCallback, useRef } from 'react';
import type { SubtitleSegment, SubtitleResponse } from './types/subtitle';
import { createJob, pollJobStatus, getSubtitles } from './api/subtitles';
import { extractVideoId } from './lib/youtube';
import { useYouTubePlayer } from './hooks/useYouTubePlayer';
import { useSubtitleSync } from './hooks/useSubtitleSync';
import { URLInput } from './components/URLInput';
import { LoadingSpinner } from './components/LoadingSpinner';
import { VideoPlayer } from './components/VideoPlayer';
import { SubtitlePanel } from './components/SubtitlePanel';
import { PlayerControls } from './components/PlayerControls';

const PLAYER_CONTAINER_ID = 'yt-player';
const AUTO_PAUSE_EPSILON = 0.08;

function App() {
  const [videoId, setVideoId] = useState<string | null>(null);
  const [subtitleData, setSubtitleData] = useState<SubtitleResponse | null>(null);
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoPausedRef = useRef(false);

  const {
    isReady,
    currentTime,
    playerState,
    seekTo,
    playVideo,
    pauseVideo,
  } = useYouTubePlayer(videoId, PLAYER_CONTAINER_ID);

  const { currentIndex, setCurrentIndex, currentWordIndex } = useSubtitleSync(
    segments,
    currentTime,
    playerState
  );

  const isPlaying = playerState === 1;

  // Auto-pause at segment end — only if segment ends with sentence-ending punctuation
  useEffect(() => {
    if (!isPlaying || segments.length === 0) return;

    const seg = segments[currentIndex];
    if (!seg) return;

    if (currentTime >= seg.end - AUTO_PAUSE_EPSILON && !autoPausedRef.current) {
      const endsWithPunctuation = /[.!?]$/.test(seg.text_en.trim());
      if (endsWithPunctuation) {
        autoPausedRef.current = true;
        pauseVideo();
      }
    }
  }, [currentTime, currentIndex, isPlaying, segments, pauseVideo]);

  // Reset auto-pause flag when segment changes
  useEffect(() => {
    autoPausedRef.current = false;
  }, [currentIndex]);

  // Poll job status
  const startPolling = useCallback(
    (jobId: string, vidId: string) => {
      const poll = async () => {
        try {
          const status = await pollJobStatus(jobId);
          setProgress(status.progress);
          setStatusText(
            status.status === 'queued'
              ? '排隊中...'
              : status.status === 'processing'
              ? `處理中 (${status.progress}%)...`
              : status.status === 'completed'
              ? '完成!'
              : '失敗'
          );

          if (status.status === 'completed') {
            const data = await getSubtitles(vidId);
            setSubtitleData(data);
            setSegments(data.segments);
            setLoading(false);
            return;
          }

          if (status.status === 'failed') {
            setError(status.error?.message || '處理失敗');
            setLoading(false);
            return;
          }

          pollTimerRef.current = setTimeout(poll, 1500);
        } catch (err) {
          setError(err instanceof Error ? err.message : '輪詢失敗');
          setLoading(false);
        }
      };

      poll();
    },
    []
  );

  // Handle URL submit
  const handleSubmit = useCallback(
    async (url: string) => {
      setError(null);
      setLoading(true);
      setProgress(0);
      setStatusText('提交中...');
      setSubtitleData(null);
      setSegments([]);
      setCurrentIndex(0);

      const vid = extractVideoId(url);
      if (!vid) {
        setError('無效的 YouTube URL');
        setLoading(false);
        return;
      }

      setVideoId(vid);

      try {
        const result = await createJob(url);

        if (result.cached || result.status === 'completed') {
          // Subtitles already available
          const data = await getSubtitles(result.video_id);
          setSubtitleData(data);
          setSegments(data.segments);
          setLoading(false);
          return;
        }

        if (result.job_id) {
          startPolling(result.job_id, result.video_id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '請求失敗');
        setLoading(false);
      }
    },
    [startPolling, setCurrentIndex]
  );

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  // Navigation helpers
  const goToSegment = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= segments.length) return;
      setCurrentIndex(idx);
      autoPausedRef.current = false;
      seekTo(segments[idx].start);
      playVideo();
    },
    [segments, seekTo, playVideo, setCurrentIndex]
  );

  const handlePrev = useCallback(() => goToSegment(currentIndex - 1), [goToSegment, currentIndex]);
  const handleNext = useCallback(() => goToSegment(currentIndex + 1), [goToSegment, currentIndex]);
  const handleRepeat = useCallback(() => goToSegment(currentIndex), [goToSegment, currentIndex]);
  const handleTogglePlay = useCallback(() => {
    if (isPlaying) {
      pauseVideo();
    } else {
      autoPausedRef.current = false;
      playVideo();
    }
  }, [isPlaying, playVideo, pauseVideo]);

  const handleClickSegment = useCallback(
    (idx: number) => {
      goToSegment(idx);
    },
    [goToSegment]
  );

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't capture if user is typing in an input
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      switch (e.key) {
        case ' ':
          e.preventDefault();
          handleTogglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          handlePrev();
          break;
        case 'ArrowRight':
          e.preventDefault();
          handleNext();
          break;
        case 'r':
        case 'R':
          e.preventDefault();
          handleRepeat();
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleTogglePlay, handlePrev, handleNext, handleRepeat]);

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 px-6 py-3 flex items-center justify-between shrink-0">
        <h1 className="text-xl font-bold tracking-wide">EchoLearn</h1>
        {subtitleData && (
          <span className="text-gray-400 text-sm truncate ml-4">
            {subtitleData.title}
          </span>
        )}
      </header>

      {/* URL Input Row */}
      <div className="px-6 py-4 bg-gray-900 border-b border-gray-800 shrink-0">
        <URLInput onSubmit={handleSubmit} disabled={loading} />
        {error && (
          <p className="mt-2 text-red-400 text-sm">{error}</p>
        )}
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {loading && (
          <LoadingSpinner progress={progress} status={statusText} />
        )}

        {!loading && videoId && segments.length > 0 && (
          <div className="flex-1 flex gap-4 p-4 overflow-hidden">
            {/* Video - left 50% */}
            <div className="w-1/2 flex flex-col gap-4">
              <VideoPlayer videoId={videoId} containerId={PLAYER_CONTAINER_ID} />
              {!isReady && (
                <p className="text-gray-500 text-sm text-center">載入播放器中...</p>
              )}
            </div>

            {/* Subtitles - right 50% */}
            <div className="w-1/2 bg-gray-800 rounded-lg p-4 overflow-hidden flex flex-col">
              <h2 className="text-gray-300 text-sm font-medium mb-3 shrink-0">
                字幕 ({segments.length} 句)
              </h2>
              <div className="flex-1 overflow-hidden">
                <SubtitlePanel
                  segments={segments}
                  currentIndex={currentIndex}
                  currentWordIndex={currentWordIndex}
                  onClickSegment={handleClickSegment}
                />
              </div>
            </div>
          </div>
        )}

        {!loading && !videoId && segments.length === 0 && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-gray-500 text-lg">貼上 YouTube URL 開始學習</p>
          </div>
        )}
      </main>

      {/* Controls Bar */}
      {segments.length > 0 && (
        <div className="bg-gray-800 border-t border-gray-700 px-6 py-3 shrink-0">
          <PlayerControls
            onPrev={handlePrev}
            onNext={handleNext}
            onRepeat={handleRepeat}
            onTogglePlay={handleTogglePlay}
            isPlaying={isPlaying}
            currentIndex={currentIndex}
            totalSegments={segments.length}
          />
        </div>
      )}
    </div>
  );
}

export default App;
