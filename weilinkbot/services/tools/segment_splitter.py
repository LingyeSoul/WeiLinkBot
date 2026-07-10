"""Reply splitter — heuristic segmentation for fallback multi-message sending.

When the LLM doesn't call `send_messages` but `segment_fallback` is enabled,
this module splits the plain-text reply into multiple segments so the bot can
still send them one-by-one (simulating human typing rhythm).

Splitting strategy (by priority):
  1. Explicit newlines  → split on them (respect the LLM's own layout)
  2. Sentence-ending punctuation (。！？.!?) → split per sentence
  3. Clause punctuation (；;，,) → only if a segment still exceeds max_chars
  4. Hard truncate at max_chars (last resort)

Constraints:
  - Each segment ≤ max_chars
  - Segment count ≤ max_count (excess tail gets merged back)
  - Always returns at least 1 non-empty segment

This is a pure module (no side effects) for easy testing.
"""

from __future__ import annotations

import re

# Sentence-ending punctuation: CJK + Latin. We keep the delimiter attached to
# the preceding sentence (regex lookbehind-free: capture + re-insert).
# Matches a run of sentence-enders optionally followed by whitespace/quotes.
_SENTENCE_END = re.compile(r"([。！？!?]+[」』\)\)]*)")

# Clause-level punctuation for fine-grained fallback splitting.
_CLAUSE_END = re.compile(r"([；;，,]+)")

# Markdown list / bullet prefixes (don't strip them — they're meaningful layout)
_BULLET_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•·])\s+")


def _strip_empty(segments: list[str]) -> list[str]:
    """Drop whitespace-only segments and strip trailing whitespace per segment."""
    return [s.strip() for s in segments if s and s.strip()]


def _merge_long_segments(segments: list[str], max_chars: int) -> list[str]:
    """Hard-split any single segment longer than max_chars into chunks."""
    result: list[str] = []
    for seg in segments:
        if len(seg) <= max_chars:
            result.append(seg)
            continue
        # Greedy chunk — cut at max_chars (last resort, no nicer boundary).
        for i in range(0, len(seg), max_chars):
            chunk = seg[i:i + max_chars].strip()
            if chunk:
                result.append(chunk)
    return result


def _cap_segment_count(segments: list[str], max_count: int) -> list[str]:
    """Merge the tail to respect max_count.

    If we have more segments than allowed, the overflow is joined (with a
    space) into the last slot rather than discarded.
    """
    if len(segments) <= max_count:
        return segments
    head = segments[:max_count - 1]
    tail = " ".join(segments[max_count - 1:])
    return head + [tail]


def _split_by_clauses(text: str) -> list[str]:
    """Split a single long sentence by clause punctuation (；;，,)."""
    if not text:
        return []
    parts = _CLAUSE_END.split(text)
    # Reassemble: split() interleaves [text, delim, text, delim, ...]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        buf += part
        if _CLAUSE_END.fullmatch(part):
            chunks.append(buf)
            buf = ""
    if buf.strip():
        chunks.append(buf)
    return _strip_empty(chunks)


def split_reply_into_segments(
    text: str,
    max_count: int = 10,
    max_chars: int = 3000,
) -> list[str]:
    """Split a reply into segments for multi-message sending.

    Args:
        text: The full reply text. Must be non-empty (caller checks).
        max_count: Maximum number of segments. Excess gets merged into the tail.
        max_chars: Maximum characters per segment. Over-long segments get split.

    Returns:
        List of non-empty segment strings (at least 1). If the text is too
        short to split meaningfully, returns a single-element list.
    """
    if not text or not text.strip():
        return []

    stripped = text.strip()
    candidates: list[str] = []

    # Strategy 1: explicit newlines — respect the LLM's own line breaks.
    if "\n" in stripped:
        candidates = _strip_empty(stripped.split("\n"))
    else:
        # Strategy 2: sentence-ending punctuation.
        # Keep the delimiter with its sentence (split + reassemble).
        raw_parts = _SENTENCE_END.split(stripped)
        sentences: list[str] = []
        buf = ""
        for part in raw_parts:
            buf += part
            if _SENTENCE_END.fullmatch(part):
                sentences.append(buf)
                buf = ""
        if buf.strip():
            sentences.append(buf)
        candidates = _strip_empty(sentences)

    # Fallback: if neither strategy produced >1 segment, return as-is (single).
    if len(candidates) <= 1:
        candidates = [stripped]

    # Strategy 3: if any candidate still exceeds max_chars, sub-split by clauses.
    refined: list[str] = []
    for seg in candidates:
        if len(seg) <= max_chars:
            refined.append(seg)
            continue
        clause_chunks = _split_by_clauses(seg)
        if len(clause_chunks) > 1:
            refined.extend(clause_chunks)
        else:
            refined.append(seg)  # will be hard-split next

    # Strategy 4: hard-split anything still too long (last resort).
    refined = _merge_long_segments(refined, max_chars)

    # Respect max_count by merging overflow into the tail.
    refined = _cap_segment_count(refined, max_count)

    return refined if refined else [stripped]
