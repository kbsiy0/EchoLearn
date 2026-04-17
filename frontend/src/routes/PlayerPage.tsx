import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { SubtitleSegment, SubtitleResponse } from '../types/subtitle';
import { getSubtitles } from '../api/subtitles';
import { useYouTubePlayer } from '../features/player/hooks/useYouTubePlayer';
import { useSubtitleSync } from '../features/player/hooks/useSubtitleSync';
import { VideoPlayer } from '../features/player/components/VideoPlayer';
import { SubtitlePanel } from '../features/player/components/SubtitlePanel';
import { PlayerControls } from '../features/player/components/PlayerControls';
import { LoadingSpinner } from '../features/player/components/LoadingSpinner';

const PLAYER_CONTAINER_ID = 'yt-player';
const AUTO_PAUSE_EPSILON = 0.08;

export function PlayerPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();

  const [subtitleData, setSubtitleData] = useState<SubtitleResponse | null>(null);
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const autoPausedRef = useRef(false);

  const {
    isReady,
    currentTime,
    playerState,
    seekTo,
    playVideo,
    pauseVideo,
  } = useYouTubePlayer(videoId ?? null, PLAYER_CONTAINER_ID);

  const { currentIndex, setCurrentIndex, currentWordIndex } = useSubtitleSync(
    segments,
    currentTime,
    playerState
  );

  const isPlaying = playerState === 1;

  // Fetch subtitles on mount
  useEffect(() => {
    if (!videoId) {
      navigate('/');
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    getSubtitles(videoId)
      .then((data) => {
        setSubtitleData(data);
        setSegments(data.segments);
        setLoading(false);
      })
      .catch(() => {
        setError('無法載入字幕');
        setLoading(false);
      });
  }, [videoId, navigate]);

  // Auto-pause at segment end
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

  const handleClickSegment = useCallback((idx: number) => goToSegment(idx), [goToSegment]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      switch (e.key) {
        case ' ': e.preventDefault(); handleTogglePlay(); break;
        case 'ArrowLeft': e.preventDefault(); handlePrev(); break;
        case 'ArrowRight': e.preventDefault(); handleNext(); break;
        case 'r': case 'R': e.preventDefault(); handleRepeat(); break;
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleTogglePlay, handlePrev, handleNext, handleRepeat]);

  if (loading) return <LoadingSpinner progress={0} status="載入字幕中..." />;
  if (error) return <div className="flex-1 flex items-center justify-center text-red-400">{error}</div>;

  return (
    <>
      {/* Title bar */}
      {subtitleData && (
        <span className="text-gray-400 text-sm truncate ml-4 shrink-0 py-2 px-6 bg-gray-800 border-b border-gray-700 block">
          {subtitleData.title}
        </span>
      )}

      {/* Main content */}
      <main className="flex-1 flex gap-4 p-4 overflow-hidden">
        <div className="w-1/2 flex flex-col gap-4">
          <VideoPlayer videoId={videoId!} containerId={PLAYER_CONTAINER_ID} />
          {!isReady && <p className="text-gray-500 text-sm text-center">載入播放器中...</p>}
        </div>
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
      </main>

      {/* Controls bar */}
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
    </>
  );
}
