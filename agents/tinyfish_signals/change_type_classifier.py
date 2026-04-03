"""
Change Type Classifier (Signal Quality Filter)
================================================
v1.5 addition per claude-build-spec-v1.5-financial-agents.md §Signal Quality Filter.

Classifies the nature of a detected text change to reduce archive/layout noise:

    CONTENT_CHANGE  — wording of sentences changed (only this yields high-confidence signals)
    ARCHIVE_CHANGE  — page mainly lists press releases, headlines, dates
    LAYOUT_CHANGE   — structural difference is large but text meaning is unchanged

Rules (from spec):
    ARCHIVE_CHANGE  : if page mainly lists press releases or headlines
    LAYOUT_CHANGE   : if structural difference is large but text meaning unchanged
    CONTENT_CHANGE  : if wording of sentences changed

Only CONTENT_CHANGE should propagate to high-confidence financial signal scoring.
ARCHIVE_CHANGE / LAYOUT_CHANGE reduce confidence significantly.
"""

from __future__ import annotations

import re
import logging
from collections import Counter
from difflib import SequenceMatcher
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Archive page detection heuristics
# ══════════════════════════════════════════════════════════════════════════════

# Patterns typical of archive / press-release listing pages
_DATE_PATTERNS = [
    r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b",       # 12/05/2024
    r"\b\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\b",           # 2024-01-15
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2},?\s+\d{4}\b",  # Jan 15, 2024
    r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}\b",    # 15 Jan 2024
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]

# Keywords that dominate archive pages
_ARCHIVE_INDICATORS = {
    "press release", "media release", "asx announcement", "sec filing",
    "news release", "investor update", "quarterly report", "annual report",
    "half year", "half-year", "q1", "q2", "q3", "q4", "fy20", "fy21",
    "fy22", "fy23", "fy24", "fy25", "earnings release", "financial results",
    "full year results", "interim results", "read more", "view announcement",
    "download pdf", "pdf download", "view filing",
}

# Structural markers typical of list-format archive pages
_LIST_MARKERS = [
    r"^\s*[\•\-\*▸►\+]\s+",     # bullet points
    r"^\s*\d+\.\s+",              # numbered lists
    r"\|\s*read more\s*\|",       # pipe-separated nav
]


def _count_date_density(text: str) -> float:
    """Return dates-per-100-chars as an archive density indicator."""
    total = max(len(text), 1)
    count = sum(
        len(re.findall(pat, text.lower()))
        for pat in _DATE_PATTERNS
    )
    return (count / total) * 100


def _archive_indicator_ratio(text: str) -> float:
    """Fraction of archive indicator phrases present in text."""
    text_lower = text.lower()
    hits = sum(1 for phrase in _ARCHIVE_INDICATORS if phrase in text_lower)
    return hits / len(_ARCHIVE_INDICATORS)


def _line_is_headline(line: str) -> bool:
    """Return True if line looks like a headline/title (short, capitalized, no full stop)."""
    line = line.strip()
    if not line:
        return False
    if len(line) > 150:
        return False
    if line.endswith("."):
        return False
    words = line.split()
    if len(words) < 3:
        return False
    # More than half the words start with capitals
    cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
    return cap_ratio >= 0.5


def _headline_line_ratio(text: str) -> float:
    """Fraction of non-empty lines that look like headlines."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    headlines = sum(1 for l in lines if _line_is_headline(l))
    return headlines / len(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Layout change detection heuristics
# ══════════════════════════════════════════════════════════════════════════════

def _word_overlap(text_a: str, text_b: str) -> float:
    """
    Cosine-style word overlap: shared unique words / union of unique words.
    High overlap + large character diff → likely layout change.
    """
    words_a = set(re.findall(r"\b\w+\b", text_a.lower()))
    words_b = set(re.findall(r"\b\w+\b", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union


def _char_diff_ratio(old_text: str, new_text: str) -> float:
    """
    0.0 = identical, 1.0 = completely different.
    Using difflib SequenceMatcher character-level similarity.
    """
    sim = SequenceMatcher(None, old_text[:5000], new_text[:5000]).ratio()
    return 1.0 - sim


# ══════════════════════════════════════════════════════════════════════════════
# Sentence-level content change detection
# ══════════════════════════════════════════════════════════════════════════════

def _extract_meaningful_sentences(text: str) -> List[str]:
    """Extract sentences that look like substantive prose (not headlines, dates, links)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    meaningful = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        # Skip if mostly dates or numbers
        if re.search(r"\d{4}", s) and len(s) < 50:
            continue
        meaningful.append(s)
    return meaningful


def _new_sentence_ratio(old_text: str, new_text: str) -> float:
    """
    Fraction of new_text sentences that are substantially different from anything in old_text.
    High ratio → real content change.
    """
    new_sents = _extract_meaningful_sentences(new_text)
    if not new_sents:
        return 0.0

    new_count = 0
    for s in new_sents:
        best_match = max(
            (SequenceMatcher(None, s.lower(), old_s.lower()).ratio()
             for old_s in _extract_meaningful_sentences(old_text)[:50]),
            default=0.0,
        )
        if best_match < 0.6:  # <60% similar → genuinely new sentence
            new_count += 1

    return new_count / len(new_sents)


# ══════════════════════════════════════════════════════════════════════════════
# Main classifier
# ══════════════════════════════════════════════════════════════════════════════

def classify_change_type(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
) -> Tuple[str, float, List[str]]:
    """
    Classify the nature of a text change between old and new website snapshots.

    Returns:
        change_type  : "CONTENT_CHANGE" | "ARCHIVE_CHANGE" | "LAYOUT_CHANGE"
        quality_score: 0.0–1.0 (1.0 = high-quality content change; 0.0 = pure noise)
        quality_flags: list of human-readable flags explaining the classification
    """
    flags: List[str] = []

    if not old_text and not new_text:
        return "CONTENT_CHANGE", 0.5, ["both_texts_empty"]

    # ── 1. Archive page detection ─────────────────────────────────────────────
    new_date_density   = _count_date_density(new_text)
    archive_ratio      = _archive_indicator_ratio(new_text)
    headline_ratio     = _headline_line_ratio(new_text)
    old_archive_ratio  = _archive_indicator_ratio(old_text)
    old_headline_ratio = _headline_line_ratio(old_text)

    is_archive_page = (
        archive_ratio >= 0.08
        or headline_ratio >= 0.5
        or new_date_density >= 1.5
    )

    # Also check if BOTH old and new look like archive pages
    both_archive_like = (
        (archive_ratio + old_archive_ratio) >= 0.12
        or (headline_ratio + old_headline_ratio) >= 0.8
    )

    if is_archive_page or both_archive_like:
        flags.append(
            f"archive_indicators: density={archive_ratio:.2f}, "
            f"headlines={headline_ratio:.2f}, dates/100c={new_date_density:.2f}"
        )
        quality_score = max(0.05, 0.25 - archive_ratio - headline_ratio * 0.3)
        return "ARCHIVE_CHANGE", round(quality_score, 3), flags

    # ── 2. Layout change detection ────────────────────────────────────────────
    word_sim   = _word_overlap(old_text, new_text)
    char_diff  = _char_diff_ratio(old_text, new_text)
    len_ratio  = abs(len(old_text) - len(new_text)) / max(len(old_text), len(new_text), 1)

    # Layout change: large structural diff but vocabulary highly overlapping
    is_layout_change = (
        char_diff >= 0.30       # significant character-level change
        and word_sim >= 0.75    # but same words → just restructured
        and len_ratio <= 0.25   # similar total length
    )

    if is_layout_change:
        flags.append(
            f"layout_change: char_diff={char_diff:.2f}, "
            f"word_overlap={word_sim:.2f}, len_ratio={len_ratio:.2f}"
        )
        quality_score = max(0.1, 0.4 - char_diff * 0.5)
        return "LAYOUT_CHANGE", round(quality_score, 3), flags

    # ── 3. Content change ─────────────────────────────────────────────────────
    new_sent_ratio = _new_sentence_ratio(old_text, new_text)
    quality_score  = min(1.0, 0.5 + new_sent_ratio * 0.5)

    if new_sent_ratio < 0.1:
        flags.append(f"minimal_new_content: new_sentence_ratio={new_sent_ratio:.2f}")
        quality_score = max(0.3, quality_score)

    if new_sent_ratio >= 0.3:
        flags.append(f"meaningful_content_change: new_sentence_ratio={new_sent_ratio:.2f}")

    return "CONTENT_CHANGE", round(quality_score, 3), flags


# ══════════════════════════════════════════════════════════════════════════════
# Confidence penalty multiplier for use in the signal classifier
# ══════════════════════════════════════════════════════════════════════════════

def get_confidence_multiplier(change_type: str, quality_score: float) -> float:
    """
    Return a confidence multiplier (0.0–1.0) to apply to signal confidence
    based on the change type classification.

    Per spec:
        CONTENT_CHANGE  → full confidence (1.0 × quality_score weighting)
        LAYOUT_CHANGE   → reduced confidence (0.3–0.5)
        ARCHIVE_CHANGE  → near-zero confidence (0.05–0.15)
    """
    if change_type == "CONTENT_CHANGE":
        return min(1.0, 0.7 + quality_score * 0.3)
    elif change_type == "LAYOUT_CHANGE":
        return min(0.5, 0.2 + quality_score * 0.3)
    else:  # ARCHIVE_CHANGE
        return min(0.15, quality_score * 0.5)
