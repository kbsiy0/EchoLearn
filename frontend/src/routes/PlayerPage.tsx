import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import type { SubtitleResponse, SubtitleSegment } from '../types/subtitle';
import { useSubtitleStream } from '../features/player/hooks/useSubtitleStream';
import type { Segment } from '../features/player/hooks/useSubtitleSync';
import { LoadingSpinner } from '../features/player/components/LoadingSpinner';
import { ProcessingPlaceholder } from '../features/player/components/ProcessingPlaceholder';
import { SubtitlePanel } from '../features/player/components/SubtitlePanel';
import { CompletedLayout } from '../features/player/components/CompletedLayout';

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

// --- ProcessingLayout -------------------------------------------------------

function ProcessingLayout({ data }: { data: SubtitleResponse }) {
  const hasSegments = data.segments.length > 0;
  const segments = toSegments(data.segments);
  const noop = useCallback(() => {}, []);
  const errorForPlaceholder =
    data.status === 'failed' ? (data.error_message ?? '處理失敗') : undefined;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {data.title && (
        <span className="text-gray-400 text-sm truncate ml-4 shrink-0 py-2 px-6 bg-gray-800 border-b border-gray-700 block">
          {data.title}
        </span>
      )}
      <div className="flex-1 flex flex-col overflow-hidden">
        <ProcessingPlaceholder
          progress={data.progress}
          title={data.title}
          error={errorForPlaceholder}
        />
        {hasSegments && (
          <div className="w-full bg-gray-800 rounded-lg p-4 overflow-hidden flex flex-col max-h-64 shrink-0">
            <h2 className="text-gray-300 text-sm font-medium mb-3 shrink-0">
              已處理片段 ({segments.length} 句)
            </h2>
            <div className="flex-1 overflow-hidden">
              <SubtitlePanel
                segments={segments}
                currentIndex={-1}
                currentWordIndex={-1}
                onClickSegment={noop}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- PlayerPage ------------------------------------------------------------

export function PlayerPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const { data } = useSubtitleStream(videoId ?? null);

  // Sticky-completed guard: once we observe `completed`, lock onto that data
  // for the rest of the page lifetime. Setting state during render with an
  // identity guard is the React-canonical pattern for derived state — it
  // bails out cleanly when `data` is unchanged.
  const [lastCompletedData, setLastCompletedData] = useState<SubtitleResponse | null>(null);
  if (data?.status === 'completed' && data !== lastCompletedData) {
    setLastCompletedData(data);
  }

  // TTFS instrumentation — fires exactly once when processing first delivers a segment
  const ttfsFiredRef = useRef(false);
  useEffect(() => {
    if (
      !ttfsFiredRef.current &&
      data?.status === 'processing' &&
      data.segments.length > 0
    ) {
      window.dispatchEvent(
        new CustomEvent('el:first-segment', { detail: { t: performance.now() } }),
      );
      ttfsFiredRef.current = true;
    }
  }, [data]);

  const effectiveData = lastCompletedData ?? data;

  if (effectiveData == null) {
    return <LoadingSpinner progress={0} status="載入字幕中..." />;
  }

  if (effectiveData.status === 'completed') {
    return <CompletedLayout data={effectiveData} videoId={videoId!} />;
  }

  return <ProcessingLayout data={effectiveData} />;
}
