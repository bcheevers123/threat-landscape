"""
Transparent weighted scoring for ThreatCandidates.

Each candidate is scored across six dimensions.  The weights are
configurable in config.yaml so the ranking behaviour can be tuned
without changing code.

Dimensions
----------
recency             — how recently was the story published?
source_credibility  — credibility score of the most credible source
corroboration       — how many independent sources reported it?
severity            — keyword signals of impact severity
breadth             — keyword signals of broad / cross-sector impact
actionability       — keyword signals of patch / advisory / IOC presence
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from src.models.schemas import ScoreBreakdown, ThreatCandidate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_SEVERITY_KEYWORDS = frozenset({
    "ransomware", "critical", "zero-day", "zero day", "0-day", "exploit",
    "remote code execution", "rce", "data breach", "active exploitation",
    "emergency", "widespread", "nation-state", "supply chain", "backdoor",
    "wiper", "destructive", "apt", "extortion", "leak", "stolen",
    "compromised", "vulnerability", "patch", "advisory", "incident",
    "attack", "campaign", "malware", "trojan", "botnet", "ddos",
    "espionage", "spyware",
})

_ACTIONABILITY_KEYWORDS = frozenset({
    "patch", "update", "mitigate", "advisory", "workaround", "hotfix",
    "fix", "remediate", "urgent", "alert", "warning", "ioc",
    "indicator of compromise", "recommendation", "cvss",
})

_BREADTH_KEYWORDS = frozenset({
    "global", "worldwide", "multiple countries", "multiple sectors",
    "critical infrastructure", "healthcare", "finance", "energy",
    "government", "education", "retail", "insurance", "telecom",
    "manufacturing", "widespread", "international",
})


# ---------------------------------------------------------------------------
# Dimension scoring functions
# ---------------------------------------------------------------------------

def _score_recency(published_at: Optional[datetime]) -> float:
    """0–1 score based on age of the item."""
    if not published_at:
        return 0.30
    now = datetime.now(tz=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)
    if age_hours <= 12:
        return 1.00
    if age_hours <= 24:
        return 0.85
    if age_hours <= 48:
        return 0.65
    if age_hours <= 72:
        return 0.45
    if age_hours <= 168:
        return 0.25
    return 0.10


def _score_severity(candidate: ThreatCandidate) -> float:
    """0–1 score based on severity keyword density in title + summary + tags."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or "", " ".join(candidate.tags)])
    ).lower()
    hits = sum(1 for kw in _SEVERITY_KEYWORDS if kw in text)
    return min(1.0, hits / 5)


def _score_actionability(candidate: ThreatCandidate) -> float:
    """0–1 score based on actionability signals."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or ""])
    ).lower()
    hits = sum(1 for kw in _ACTIONABILITY_KEYWORDS if kw in text)
    cve_count = len(re.findall(r"cve-\d{4}-\d+", text))
    return min(1.0, (hits + cve_count * 0.5) / 3)


def _score_breadth(candidate: ThreatCandidate) -> float:
    """0–1 score based on cross-sector / cross-country impact signals."""
    text = " ".join(
        filter(None, [candidate.title, candidate.summary or ""])
    ).lower()
    hits = sum(1 for kw in _BREADTH_KEYWORDS if kw in text)
    return min(1.0, hits / 3)


def _score_corroboration(count: int) -> float:
    """0–1 score based on number of sources that reported the story."""
    # Saturates at 5 sources
    return min(1.0, [0.30, 0.50, 0.70, 0.85, 1.00][min(count, 5) - 1])


def _source_domain(url: str) -> str:
    """
    Return the registered domain of a URL for diversity bucketing.

    Examples
    --------
    https://arxiv.org/abs/2501.12345         → arxiv.org
    https://rss.arxiv.org/rss/cs.LG         → arxiv.org
    https://developer.nvidia.com/blog/…     → nvidia.com
    https://feeds.bbci.co.uk/news/…         → bbci.co.uk
    https://spectrum.ieee.org/…             → ieee.org
    """
    try:
        netloc = urlparse(url).netloc.lower()
        if not netloc:
            return url
        parts = netloc.split(".")
        # Two-level ccTLDs like .co.uk, .com.au: take last three parts
        if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:]) if len(parts) >= 2 else netloc
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Weights and scorer
# ---------------------------------------------------------------------------

class ScoringWeights:
    """Configurable scoring weights.  Values should sum to 1.0."""

    def __init__(
        self,
        recency: float = 0.25,
        source_credibility: float = 0.20,
        corroboration: float = 0.15,
        severity: float = 0.20,
        breadth: float = 0.10,
        actionability: float = 0.10,
    ) -> None:
        self.recency = recency
        self.source_credibility = source_credibility
        self.corroboration = corroboration
        self.severity = severity
        self.breadth = breadth
        self.actionability = actionability


class Scorer:
    """Scores and ranks ThreatCandidates using a transparent weighted model."""

    def __init__(
        self,
        weights: Optional[ScoringWeights] = None,
        diversity_cap: int = 0,
    ) -> None:
        self.weights = weights or ScoringWeights()
        # diversity_cap > 0 limits how many items from the same source domain
        # can appear in the final top-N.  0 = disabled (no cap).
        self.diversity_cap = diversity_cap

    def score(self, candidate: ThreatCandidate) -> tuple[float, ScoreBreakdown]:
        """Return (total_score, breakdown) for a single candidate."""
        w = self.weights
        dims = {
            "recency": _score_recency(candidate.published_at) * w.recency,
            "source_credibility": candidate.max_source_credibility * w.source_credibility,
            "corroboration": _score_corroboration(candidate.corroboration_count) * w.corroboration,
            "severity": _score_severity(candidate) * w.severity,
            "breadth": _score_breadth(candidate) * w.breadth,
            "actionability": _score_actionability(candidate) * w.actionability,
        }
        total = sum(dims.values())
        breakdown = ScoreBreakdown(
            recency=round(dims["recency"], 4),
            source_credibility=round(dims["source_credibility"], 4),
            corroboration=round(dims["corroboration"], 4),
            severity=round(dims["severity"], 4),
            breadth=round(dims["breadth"], 4),
            actionability=round(dims["actionability"], 4),
            total=round(total, 4),
        )
        return total, breakdown

    def score_and_rank(
        self,
        candidates: list[ThreatCandidate],
        top_n: int = 10,
    ) -> list[tuple[ThreatCandidate, float, ScoreBreakdown]]:
        """
        Score all candidates, sort descending, return top_n.

        When diversity_cap > 0, at most that many items from the same source
        domain are included in the result.  Candidates are still selected in
        score order; a candidate is skipped only if its domain is already at
        the cap, then the next best candidate is tried instead.
        """
        scored = [
            (candidate, *self.score(candidate)) for candidate in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        if self.diversity_cap > 0:
            selected: list[tuple] = []
            domain_counts: dict[str, int] = {}
            for item in scored:
                candidate = item[0]
                domain = _source_domain(candidate.primary_url or "")
                count = domain_counts.get(domain, 0)
                if count < self.diversity_cap:
                    selected.append(item)
                    domain_counts[domain] = count + 1
                    if len(selected) == top_n:
                        break
            result = selected
        else:
            result = scored[:top_n]

        if result:
            logger.info(
                "Scoring: %d candidates → top score=%.3f, #%d score=%.3f"
                + (" (diversity cap=%d/domain)" % self.diversity_cap if self.diversity_cap else "") + ".",
                len(scored),
                result[0][1],
                len(result),
                result[-1][1],
            )
        return result
