import { useEffect, useRef } from 'react';
import type { Segment } from '../hooks/useSubtitleSync';
import { SubtitleLine } from './SubtitleLine';

interface SubtitlePanelProps {
  segments: Segment[];
  currentIndex: number;
  currentWordIndex: number;
  onClickSegment: (index: number) => void;
}

export function SubtitlePanel({ segments, currentIndex, currentWordIndex, onClickSegment }: SubtitlePanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const active = activeRef.current;
    if (!container || !active) return;

    const containerRect = container.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    const offsetInContainer = activeRect.top - containerRect.top + container.scrollTop;
    const targetScroll = offsetInContainer - containerRect.height / 2 + activeRect.height / 2;

    container.scrollTo({ top: targetScroll, behavior: 'smooth' });
  }, [currentIndex]);

  return (
    <div ref={containerRef} className="h-full overflow-y-auto space-y-1 pr-2">
      {segments.map((segment, idx) => (
        <div key={segment.idx} ref={idx === currentIndex ? activeRef : undefined}>
          <SubtitleLine
            segment={segment}
            isActive={idx === currentIndex}
            currentWordIndex={idx === currentIndex ? currentWordIndex : -1}
            onClick={() => onClickSegment(idx)}
          />
        </div>
      ))}
    </div>
  );
}
