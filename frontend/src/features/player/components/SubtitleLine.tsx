import { memo } from 'react';
import type { Segment } from '../hooks/useSubtitleSync';

interface SubtitleLineProps {
  segment: Segment;
  isActive: boolean;
  currentWordIndex: number;
  onClick: () => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export const SubtitleLine = memo(function SubtitleLine({
  segment,
  isActive,
  currentWordIndex,
  onClick,
}: SubtitleLineProps) {
  return (
    <div
      onClick={onClick}
      className={`px-4 py-3 cursor-pointer transition-colors rounded-md ${
        isActive
          ? 'bg-blue-900/50 border-l-2 border-blue-400'
          : 'hover:bg-gray-700/50 border-l-2 border-transparent'
      }`}
    >
      <span className="text-xs text-gray-500 mr-2 font-mono">{formatTime(segment.start)}</span>
      <p className="text-sm leading-relaxed">
        {isActive && segment.words && segment.words.length > 0
          ? segment.words.map((w, i) => {
              let colorClass: string;
              if (currentWordIndex === -1) {
                colorClass = 'text-white';
              } else if (i < currentWordIndex) {
                colorClass = 'text-blue-200';
              } else if (i === currentWordIndex) {
                colorClass = 'text-yellow-300 font-semibold';
              } else {
                colorClass = 'text-white';
              }
              return (
                <span
                  key={i}
                  className={`${colorClass} transition-colors duration-150`}
                >
                  {i > 0 ? ' ' : ''}
                  {w.text}
                </span>
              );
            })
          : <span className="text-white">{segment.text_en}</span>
        }
      </p>
      <p className="text-gray-400 text-sm leading-relaxed mt-1">{segment.text_zh}</p>
    </div>
  );
});
