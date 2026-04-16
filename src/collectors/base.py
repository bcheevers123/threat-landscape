"""Abstract base class for all source collectors."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.models.schemas import RawItem, SourceConfig

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """
    Abstract base for a single-source collector.

    Subclasses implement ``collect()``.  Callers should use
    ``safe_collect()`` which catches all exceptions and degrades gracefully.
    """

    def __init__(self, config: SourceConfig) -> None:
        self.config = config

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """Fetch items from the source.  May raise on transient errors."""
        ...

    def safe_collect(self) -> list[RawItem]:
        """
        Wrapper around ``collect()`` that logs errors and returns an empty
        list rather than propagating exceptions.

        This ensures a single failing source never blocks the full pipeline.
        """
        try:
            items = self.collect()
            logger.info(
                "Collected %d item(s) from '%s'", len(items), self.config.name
            )
            return items
        except Exception as exc:
            logger.warning(
                "Failed to collect from '%s': %s — skipping source.",
                self.config.name,
                exc,
                exc_info=True,
            )
            return []
