from __future__ import annotations

import re

# Standard English stopwords - Phase 1 is English-only by design (multi-language
# is out of scope per CLAUDE.md's phase boundaries). looking_for/offerings text
# copied verbatim from Excel may still contain non-English words (e.g. a Dutch
# event) - those simply pass through as ordinary tokens, untranslated.
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over",
    "own", "s", "same", "she", "should", "so", "some", "such", "t", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "whom", "why", "will", "with", "you", "your", "yours", "yourself",
    "yourselves",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str | None) -> set[str]:
    """Lowercase, split on non-alphanumeric boundaries, drop stopwords."""
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS}


def _overlap_coefficient(tokens_a: set[str], tokens_b: set[str]) -> float:
    """|intersection| / min(|A|, |B|) - the Szymkiewicz-Simpson coefficient.

    Chosen over Jaccard because looking_for/offerings are often very different
    lengths (a short want vs. a longer descriptive offer); overlap coefficient
    asks "how much of the shorter phrase is covered", which is the more useful
    signal here than penalizing for the longer phrase's extra words.
    """
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def token_overlap_score(
    *,
    a_looking_for: str | None,
    a_offerings: str | None,
    b_looking_for: str | None,
    b_offerings: str | None,
) -> float:
    """Intent-alignment score for a candidate pair A<->B, in [0, 1].

    overlap(A.looking_for, B.offerings) measures how well B can supply what A
    wants; overlap(B.looking_for, A.offerings) measures the reverse. Averaged
    (not summed) so the result stays in [0, 1] as specified - a straight sum
    of two [0, 1] values could reach 2, which wouldn't be a valid final score.
    """
    a_lf = tokenize(a_looking_for)
    a_of = tokenize(a_offerings)
    b_lf = tokenize(b_looking_for)
    b_of = tokenize(b_offerings)

    forward = _overlap_coefficient(a_lf, b_of)
    backward = _overlap_coefficient(b_lf, a_of)
    return (forward + backward) / 2
