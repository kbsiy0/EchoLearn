import { useEffect, useRef } from 'react';
import { formatPlayedAt, formatSegmentLabel } from '../lib/format';

interface ResumeToastProps {
  playedAtSec: number;
  segmentIdx: number;
  onDismiss: () => void;
  onRestart: () => void;
}

export function ResumeToast({
  playedAtSec,
  segmentIdx,
  onDismiss,
  onRestart,
}: ResumeToastProps) {
  // Track whether a button already handled dismissal so the auto-timer
  // does not double-fire after a button click.
  const handledRef = useRef(false);

  // 5-second wall-clock auto-dismiss. Timer set once on mount; cleared on
  // unmount (useEffect cleanup) and after button clicks (handledRef guard).
  useEffect(() => {
    const id = setTimeout(() => {
      if (!handledRef.current) {
        onDismiss();
      }
    }, 5000);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally empty — timer fires once on mount

  function handleDismiss() {
    handledRef.current = true;
    onDismiss();
  }

  function handleRestart() {
    handledRef.current = true;
    onRestart();
  }

  const timeLabel = formatPlayedAt(playedAtSec);
  const segLabel = formatSegmentLabel(segmentIdx);

  return (
    // Outer wrapper: fixed bottom-right, pointer-events-none so it does not
    // block clicks on the underlying player surface.
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex justify-end">
      {/* Toast bubble restores pointer events for interactive elements */}
      <div className="pointer-events-auto flex items-center gap-3 rounded-lg bg-gray-800/90 px-4 py-2 shadow-lg text-sm text-white">
        <span className="text-green-400">✓</span>
        <span>
          已恢復到 {timeLabel} ({segLabel})
        </span>
        <button
          type="button"
          onClick={handleRestart}
          className="rounded px-2 py-0.5 bg-gray-600 hover:bg-gray-500 text-white text-xs"
        >
          從頭播
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          className="rounded px-1.5 py-0.5 bg-transparent hover:bg-gray-700 text-gray-300 hover:text-white"
          aria-label="✕"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
