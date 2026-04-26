import type { SubtitleSegment } from '../../../types/subtitle';
import type { Segment } from '../hooks/useSubtitleSync';

export function toSegments(apiSegments: SubtitleSegment[]): Segment[] {
  return apiSegments.map((s) => ({
    idx: s.idx,
    start: s.start,
    end: s.end,
    text_en: s.text_en,
    text_zh: s.text_zh,
    words: s.words.map((w) => ({ text: w.text, start: w.start, end: w.end })),
  }));
}
