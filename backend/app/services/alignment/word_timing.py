"""Word timing utilities: segment normalization and per-word timing estimation.

These were originally in routers/subtitles.py (pre-T05 monolith). Moved here
so they can be shared by pipeline and tested without importing a router.
"""
from __future__ import annotations

import re


def normalize_segments(segments: list[dict]) -> list[dict]:
    """Merge raw transcript fragments into natural sentences.

    YouTube transcripts are often chopped into 2-3 second fragments mid-sentence.
    This merges them into complete sentences by looking for sentence-ending punctuation.

    Rules:
    - Keep merging until text ends with sentence punctuation (.!?)
    - If no punctuation found, merge until duration >= 8s then cut
    - Never exceed 15s per merged segment
    - Always merge <1s fragments into previous

    Args:
        segments: List of dicts with "start", "end" (or "duration"), and "text".

    Returns:
        List of merged segment dicts with "start", "end", "text".
    """
    if not segments:
        return []

    cleaned = []
    for seg in segments:
        start = seg["start"]
        if "end" in seg:
            end = seg["end"]
        else:
            end = start + seg.get("duration", 0)
        text = seg["text"].strip()
        if text:
            cleaned.append({"start": start, "end": end, "text": text})

    if not cleaned:
        return []

    result = []
    current = dict(cleaned[0])

    for seg in cleaned[1:]:
        current_duration = current["end"] - current["start"]
        potential_duration = seg["end"] - current["start"]

        if potential_duration > 15:
            result.append(current)
            current = dict(seg)
            continue

        seg_duration = seg["end"] - seg["start"]
        if seg_duration < 1.0:
            current["end"] = seg["end"]
            current["text"] = current["text"] + " " + seg["text"]
            continue

        ends_with_punct = bool(re.search(r'[.!?]$', current["text"]))
        if ends_with_punct and current_duration >= 3:
            result.append(current)
            current = dict(seg)
            continue

        if current_duration >= 8:
            result.append(current)
            current = dict(seg)
            continue

        current["end"] = seg["end"]
        current["text"] = current["text"] + " " + seg["text"]

    result.append(current)
    return result


def estimate_word_timings(text: str, start: float, end: float) -> list[dict]:
    """Estimate per-word timing by distributing duration proportionally by character length.

    - Punctuation-only tokens get zero weight.
    - Minimum word duration is 0.05s.
    - Precision: 3 decimal places.

    Args:
        text: The segment text.
        start: Segment start time in seconds.
        end: Segment end time in seconds.

    Returns:
        List of dicts with "word", "start", "end".
    """
    words = text.split()
    if not words:
        return []

    duration = end - start
    if duration <= 0:
        return [{"word": w, "start": round(start, 3), "end": round(end, 3)} for w in words]

    MIN_DURATION = 0.05

    weights = []
    for w in words:
        if re.match(r'^[^\w]+$', w):
            weights.append(0)
        else:
            weights.append(len(w))

    total_weight = sum(weights)
    if total_weight == 0:
        per_word = duration / len(words)
        result = []
        cursor = start
        for w in words:
            w_end = cursor + per_word
            result.append({"word": w, "start": round(cursor, 3), "end": round(w_end, 3)})
            cursor = w_end
        return result

    raw_durations = []
    for weight in weights:
        if weight == 0:
            raw_durations.append(0)
        else:
            raw_durations.append(max(MIN_DURATION, duration * weight / total_weight))

    raw_total = sum(raw_durations)
    if raw_total > 0:
        scale = duration / raw_total
        raw_durations = [d * scale for d in raw_durations]

    result = []
    cursor = start
    for i, w in enumerate(words):
        w_end = cursor + raw_durations[i]
        result.append({"word": w, "start": round(cursor, 3), "end": round(w_end, 3)})
        cursor = w_end

    if result:
        result[-1]["end"] = round(end, 3)

    return result


def assign_words_to_segment(all_words: list[dict], seg_start: float, seg_end: float) -> list[dict]:
    """Pick words from Whisper word list that fall within segment time range."""
    result = []
    for w in all_words:
        if w["start"] >= seg_start - 0.05 and w["start"] < seg_end + 0.05:
            result.append({
                "word": w["word"],
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })
    return result
