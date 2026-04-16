"""Tests for the scoring module."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.models.schemas import ThreatCandidate
from src.scoring.scorer import (
    Scorer,
    ScoringWeights,
    _score_recency,
    _score_severity,
    _score_actionability,
    _score_breadth,
    _score_corroboration,
)


def _candidate(**kwargs) -> ThreatCandidate:
    defaults = dict(
        title="Test Threat",
        primary_url="https://example.com/1",
        primary_source="Test Source",
        corroboration_count=1,
        max_source_credibility=0.8,
        published_at=datetime.now(tz=timezone.utc),
    )
    defaults.update(kwargs)
    return ThreatCandidate(**defaults)


class TestRecencyScore:
    def test_very_recent_is_high(self):
        now = datetime.now(tz=timezone.utc)
        assert _score_recency(now) == 1.0

    def test_day_old_is_lower(self):
        day_ago = datetime.now(tz=timezone.utc) - timedelta(hours=20)
        score = _score_recency(day_ago)
        assert 0.75 <= score <= 1.0

    def test_week_old_is_low(self):
        week_ago = datetime.now(tz=timezone.utc) - timedelta(days=7)
        score = _score_recency(week_ago)
        assert score <= 0.30

    def test_no_date_returns_default(self):
        score = _score_recency(None)
        assert 0.2 <= score <= 0.4


class TestSeverityScore:
    def test_no_keywords_is_zero(self):
        c = _candidate(title="A benign news item", summary="Nothing interesting here")
        assert _score_severity(c) == 0.0

    def test_ransomware_keyword_scores(self):
        c = _candidate(title="Major ransomware attack", summary="Critical breach")
        assert _score_severity(c) > 0.0

    def test_saturates_at_one(self):
        c = _candidate(
            title="ransomware critical zero-day exploit attack breach",
            summary="active exploitation of backdoor wiper malware campaign",
        )
        assert _score_severity(c) == 1.0


class TestActionabilityScore:
    def test_patch_advisory_keywords(self):
        c = _candidate(title="Advisory: patch your systems now", summary="Urgent update available")
        assert _score_actionability(c) > 0.0

    def test_cve_boosts_score(self):
        c = _candidate(title="CVE-2025-12345 exploited in the wild")
        without_cve = _candidate(title="Vulnerability exploited in the wild")
        assert _score_actionability(c) > _score_actionability(without_cve)


class TestBreadthScore:
    def test_global_keyword(self):
        c = _candidate(title="Global ransomware campaign", summary="Worldwide spread affecting multiple sectors")
        assert _score_breadth(c) > 0.0

    def test_no_keywords(self):
        c = _candidate(title="Small company breach")
        assert _score_breadth(c) == 0.0


class TestCorroborationScore:
    def test_single_source(self):
        assert _score_corroboration(1) == 0.30

    def test_five_sources_is_max(self):
        assert _score_corroboration(5) == 1.0

    def test_more_than_five_saturates(self):
        assert _score_corroboration(10) == 1.0


class TestScorer:
    def test_score_returns_float_between_zero_and_one(self):
        scorer = Scorer()
        c = _candidate()
        total, breakdown = scorer.score(c)
        assert 0.0 <= total <= 1.0
        assert 0.0 <= breakdown.total <= 1.0

    def test_higher_credibility_scores_higher(self):
        scorer = Scorer()
        low = _candidate(max_source_credibility=0.3)
        high = _candidate(max_source_credibility=0.95)
        score_low, _ = scorer.score(low)
        score_high, _ = scorer.score(high)
        assert score_high > score_low

    def test_score_and_rank_returns_correct_count(self):
        scorer = Scorer()
        candidates = [
            _candidate(title=f"Threat {i}", primary_url=f"https://example.com/{i}")
            for i in range(20)
        ]
        ranked = scorer.score_and_rank(candidates, top_n=10)
        assert len(ranked) == 10

    def test_score_and_rank_sorted_descending(self):
        scorer = Scorer()
        candidates = [
            _candidate(title=f"Threat {i}", primary_url=f"https://example.com/{i}")
            for i in range(5)
        ]
        ranked = scorer.score_and_rank(candidates, top_n=5)
        scores = [r[1] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_custom_weights(self):
        # Giving 100% weight to corroboration
        weights = ScoringWeights(
            recency=0.0,
            source_credibility=0.0,
            corroboration=1.0,
            severity=0.0,
            breadth=0.0,
            actionability=0.0,
        )
        scorer = Scorer(weights=weights)
        single = _candidate(corroboration_count=1)
        multi = _candidate(corroboration_count=5, primary_url="https://b.com/1")
        s_single, _ = scorer.score(single)
        s_multi, _ = scorer.score(multi)
        assert s_multi > s_single
