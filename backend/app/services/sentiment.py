"""Transparent headline sentiment heuristic.

Used only when the news provider does not supply its own sentiment. It counts finance-specific
positive/negative terms in the headline and summary. It is a rough signal - every article
shows which method produced its label, and the matched terms, so users can judge it.
"""
from __future__ import annotations

import re

POSITIVE = {
    "beat", "beats", "surge", "surges", "surged", "soar", "soars", "soared", "record", "upgrade", "upgrades",
    "upgraded", "growth", "gain", "gains", "rally", "rallies", "strong", "stronger", "outperform", "outperforms",
    "approval", "approved", "wins", "win", "expands", "expansion", "buyback", "jump", "jumps", "jumped",
    "rise", "rises", "rose", "higher", "profit", "profits", "boost", "boosts", "bullish", "raises", "raised",
    "upbeat", "robust", "milestone", "partnership", "acquires", "dividend",
}
NEGATIVE = {
    "miss", "misses", "missed", "plunge", "plunges", "plunged", "fall", "falls", "fell", "drop", "drops",
    "dropped", "downgrade", "downgrades", "downgraded", "loss", "losses", "weak", "weaker", "lawsuit", "probe",
    "investigation", "fraud", "penalty", "fine", "fined", "cut", "cuts", "layoffs", "layoff", "decline",
    "declines", "declined", "slump", "slumps", "warning", "warns", "recall", "default", "bankruptcy", "resigns",
    "lower", "bearish", "slowdown", "selloff", "sell-off", "tumble", "tumbles", "crash", "scandal", "raid",
}
NEGATORS = {"not", "no", "without", "fails", "failed"}
_WORD = re.compile(r"[a-z][a-z\-']*")


def score_text(text: str) -> dict:
    words = _WORD.findall((text or "").lower())
    pos, neg = [], []
    for i, w in enumerate(words):
        negated = i > 0 and words[i - 1] in NEGATORS
        if w in POSITIVE:
            (neg if negated else pos).append(w)
        elif w in NEGATIVE:
            (pos if negated else neg).append(w)
    total = len(pos) + len(neg)
    score = 0.0 if total == 0 else (len(pos) - len(neg)) / total
    label = "neutral"
    if total and score >= 0.34:
        label = "positive"
    elif total and score <= -0.34:
        label = "negative"
    return {
        "label": label,
        "score": round(score, 2),
        "method": "keyword heuristic",
        "matched_positive": sorted(set(pos)),
        "matched_negative": sorted(set(neg)),
    }


def label_from_score(score: float) -> str:
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"
