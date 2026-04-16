"""
Collector manager — runs all enabled collectors concurrently.

Uses a ThreadPoolExecutor so that slow or stalling sources do not
block the rest of the pipeline.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from src.collectors.base import BaseCollector
from src.collectors.rss_collector import RSSCollector
from src.models.schemas import RawItem, SourceConfig, SourceType

logger = logging.getLogger(__name__)


def _build_collector(config: SourceConfig, max_items: int) -> Optional[BaseCollector]:
    """Instantiate the correct collector for the given source type."""
    if config.type == SourceType.RSS:
        return RSSCollector(config, max_items=max_items)
    logger.warning(
        "No collector implemented for source type '%s' (source: '%s'). Skipping.",
        config.type,
        config.name,
    )
    return None


class CollectorManager:
    """
    Orchestrates all configured source collectors.

    Each collector runs in its own thread.  Failures in individual
    collectors are caught and logged; the manager always returns whatever
    items were successfully collected.
    """

    def __init__(
        self,
        sources: list[SourceConfig],
        max_items_per_source: int = 50,
        max_workers: int = 8,
    ) -> None:
        self.sources = [s for s in sources if s.enabled]
        self.max_items_per_source = max_items_per_source
        self.max_workers = max_workers

    def collect_all(self) -> list[RawItem]:
        """
        Run all collectors concurrently and return the combined list of RawItems.
        """
        collectors: list[BaseCollector] = []
        for source in self.sources:
            collector = _build_collector(source, self.max_items_per_source)
            if collector:
                collectors.append(collector)

        if not collectors:
            logger.warning("No collectors configured or enabled.")
            return []

        logger.info(
            "Starting collection from %d source(s) using up to %d workers.",
            len(collectors),
            self.max_workers,
        )

        all_items: list[RawItem] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {
                pool.submit(c.safe_collect): c for c in collectors
            }
            for future in as_completed(future_map):
                collector = future_map[future]
                try:
                    items = future.result()
                    all_items.extend(items)
                except Exception as exc:
                    logger.error(
                        "Unexpected error from collector '%s': %s",
                        collector.config.name,
                        exc,
                    )

        logger.info("Collection complete — %d raw items total.", len(all_items))
        return all_items
