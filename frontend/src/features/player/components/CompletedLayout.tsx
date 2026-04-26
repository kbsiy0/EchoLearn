import { useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { SubtitleResponse } from '../../../types/subtitle';
import { useYouTubePlayer } from '../hooks/useYouTubePlayer';
import { useSubtitleSync } from '../hooks/useSubtitleSync';
import { useAutoPause } from '../hooks/useAutoPause';
import { useLoopSegment } from '../hooks/useLoopSegment';
import { usePlaybackRate } from '../hooks/usePlaybackRate';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { computePlaybackFlags } from '../lib/flags';
import { VideoPlayer } from './VideoPlayer';
import { SubtitlePanel } from './SubtitlePanel';
import { PlayerControls } from './PlayerControls';
import { TitleBar } from './TitleBar';

const PLAYER_CONTAINER_ID = 'yt-player';

interface Props {
  data: SubtitleResponse;
  videoId: string;
}

export function CompletedLayout({ data, videoId }: Props) {
  const [searchParams] = useSearchParams();
  const measure = searchParams.get('measure') === '1';
  const [loop, setLoop] = useState(false);
  const segments = data.segments;

  const { player, isReady, playerState, seekTo, playVideo, pauseVideo } =
    useYouTubePlayer(videoId, PLAYER_CONTAINER_ID);

  const { currentIndex, currentWordIndex } = useSubtitleSync(player, segments);
  const { autoPauseEnabled, loopEnabled } = computePlaybackFlags(measure, loop);
  useAutoPause(player, segments, currentIndex, autoPauseEnabled);
  useLoopSegment(player, segments, currentIndex, loopEnabled);
  const { rate, setRate, stepUp, stepDown } = usePlaybackRate(player, isReady);

  const isPlaying = playerState === 1;

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
    onToggleLoop: handleToggleLoop,
    onSpeedDown: stepDown,
    onSpeedUp: stepUp,
  });

  return (
    <>
      <TitleBar title={data.title} />
      <main className="flex-1 flex gap-4 p-4 overflow-hidden">
        <div className="w-1/2 flex flex-col gap-4">
          <VideoPlayer videoId={videoId} containerId={PLAYER_CONTAINER_ID} />
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
