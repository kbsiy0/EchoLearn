import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import type { SubtitleSegment, SubtitleResponse } from '../types/subtitle';
import { getSubtitles } from '../api/subtitles';
import { useYouTubePlayer } from '../features/player/hooks/useYouTubePlayer';
import { useSubtitleSync, type Segment } from '../features/player/hooks/useSubtitleSync';
import { useAutoPause } from '../features/player/hooks/useAutoPause';
import { useLoopSegment } from '../features/player/hooks/useLoopSegment';
import { usePlaybackRate } from '../features/player/hooks/usePlaybackRate';
import { useKeyboardShortcuts } from '../features/player/hooks/useKeyboardShortcuts';
import { computePlaybackFlags } from '../features/player/lib/flags';
import { VideoPlayer } from '../features/player/components/VideoPlayer';
import { SubtitlePanel } from '../features/player/components/SubtitlePanel';
import { PlayerControls } from '../features/player/components/PlayerControls';
import { LoadingSpinner } from '../features/player/components/LoadingSpinner';

const PLAYER_CONTAINER_ID = 'yt-player';

/** Adapt API response shape to hook-internal Segment shape. */
function toSegments(apiSegments: SubtitleSegment[]): Segment[] {
  return apiSegments.map((s) => ({
    idx: s.idx,
    start: s.start,
    end: s.end,
    text_en: s.text_en,
    text_zh: s.text_zh,
    words: s.words.map((w) => ({ text: w.text, start: w.start, end: w.end })),
  }));
}

export function PlayerPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const measure = searchParams.get('measure') === '1';

  const [loop, setLoop] = useState(false);
  const [subtitleData, setSubtitleData] = useState<SubtitleResponse | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const {
    player,
    isReady,
    playerState,
    seekTo,
    playVideo,
    pauseVideo,
  } = useYouTubePlayer(videoId ?? null, PLAYER_CONTAINER_ID);

  const { currentIndex, currentWordIndex } = useSubtitleSync(player, segments);

  const { autoPauseEnabled, loopEnabled } = computePlaybackFlags(measure, loop);
  useAutoPause(player, segments, currentIndex, autoPauseEnabled);
  useLoopSegment(player, segments, currentIndex, loopEnabled);
  const { rate, setRate } = usePlaybackRate(player);

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
        setSegments(toSegments(data.segments));
        setLoading(false);
      })
      .catch(() => {
        setError('無法載入字幕');
        setLoading(false);
      });
  }, [videoId, navigate]);

  // Navigation helpers
  const goToSegment = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= segments.length) return;
      seekTo(segments[idx].start);
      playVideo();
    },
    [segments, seekTo, playVideo],
  );

  const handlePrev = useCallback(() => goToSegment(currentIndex - 1), [goToSegment, currentIndex]);
  const handleNext = useCallback(() => goToSegment(currentIndex + 1), [goToSegment, currentIndex]);
  const handleRepeat = useCallback(() => goToSegment(currentIndex), [goToSegment, currentIndex]);
  const handleTogglePlay = useCallback(() => {
    if (isPlaying) pauseVideo();
    else playVideo();
  }, [isPlaying, playVideo, pauseVideo]);

  const handleClickSegment = useCallback((idx: number) => goToSegment(idx), [goToSegment]);
  const handleToggleLoop = useCallback(() => setLoop((v) => !v), []);

  useKeyboardShortcuts({
    onTogglePlay: handleTogglePlay,
    onPrev: handlePrev,
    onNext: handleNext,
    onRepeat: handleRepeat,
  });

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
            onToggleLoop={handleToggleLoop}
            isPlaying={isPlaying}
            loop={loop}
            currentIndex={currentIndex}
            totalSegments={segments.length}
            rate={rate}
            onSetRate={setRate}
          />
        </div>
      )}
    </>
  );
}
