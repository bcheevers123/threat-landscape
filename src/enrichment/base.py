"""Abstract enrichment provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.models.schemas import EnrichedThreat, ScoreBreakdown, ThreatCandidate


class BaseEnrichmentProvider(ABC):
    """
    Abstract base for enrichment providers.

    Implement this interface to add new providers (e.g. OpenAI, Anthropic)
    without changing any pipeline code.  The deterministic provider is the
    default and requires no external APIs.
    """

    @abstractmethod
    def enrich(
        self,
        candidate: ThreatCandidate,
        score: float,
        score_breakdown: Optional[ScoreBreakdown] = None,
    ) -> EnrichedThreat:
        """
        Enrich a ThreatCandidate and return a fully populated EnrichedThreat.

        Implementations must NOT fabricate facts.  Where a field cannot be
        determined from the available evidence, use ``"Unknown"`` or
        ``"Unconfirmed"`` and document the uncertainty in ``confidence_note``.
        """
        ...
