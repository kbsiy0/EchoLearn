interface PlayerControlsProps {
  onPrev: () => void;
  onNext: () => void;
  onRepeat: () => void;
  onTogglePlay: () => void;
  isPlaying: boolean;
  currentIndex: number;
  totalSegments: number;
}

export function PlayerControls({
  onPrev,
  onNext,
  onRepeat,
  onTogglePlay,
  isPlaying,
  currentIndex,
  totalSegments,
}: PlayerControlsProps) {
  return (
    <div className="flex items-center justify-center gap-3">
      <button
        onClick={onPrev}
        disabled={currentIndex <= 0}
        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        上一句
      </button>
      <button
        onClick={onRepeat}
        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
      >
        重複
      </button>
      <button
        onClick={onTogglePlay}
        className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors"
      >
        {isPlaying ? '暫停' : '播放'}
      </button>
      <button
        onClick={onNext}
        disabled={currentIndex >= totalSegments - 1}
        className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        下一句
      </button>
      <span className="text-gray-400 text-sm ml-4">
        第 {totalSegments > 0 ? currentIndex + 1 : 0}/{totalSegments} 句
      </span>
    </div>
  );
}
