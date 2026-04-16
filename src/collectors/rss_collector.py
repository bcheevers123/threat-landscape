"""
RSS/Atom feed collector.

Uses httpx with retry logic for reliable fetching and feedparser for
feed parsing.  Falls back to direct feedparser URL fetch if the HTTP
request succeeds but the response text cannot be parsed.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.collectors.base import BaseCollector
from src.models.schemas import RawItem, SourceConfig, SourceType

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "ThreatLandscape/1.0 (+https://barrycheevers.co.uk; security-research-aggregator)"
)


def _parse_entry_date(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """Extract a timezone-aware datetime from a feedparser entry."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                ts = time.mktime(value)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
    return None


def _strip_html(text: Optional[str]) -> Optional[str]:
    """Strip HTML tags and normalise whitespace."""
    if not text:
        return None
    try:
        from bs4 import BeautifulSoup
        return " ".join(
            BeautifulSoup(text, "html.parser").get_text(separator=" ").split()
        )
    except Exception:
        import re
        return re.sub(r"<[^>]+>", " ", text).strip()


class RSSCollector(BaseCollector):
    """Collects items from RSS or Atom feeds."""

    def __init__(self, config: SourceConfig, max_items: int = 50) -> None:
        super().__init__(config)
        self.max_items = max_items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)
        ),
        reraise=True,
    )
    def _fetch_feed_text(self) -> str:
        """Fetch raw feed text via httpx with retry."""
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            **self.config.headers,
        }
        with httpx.Client(
            timeout=self.config.timeout,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = client.get(self.config.url, headers=headers)
            response.raise_for_status()
            return response.text

    def collect(self) -> list[RawItem]:
        """Fetch and parse the feed, returning up to max_items RawItems."""
        try:
            text = self._fetch_feed_text()
            feed = feedparser.parse(text)
        except Exception:
            # Fall back to feedparser's own URL fetch — enforce a socket timeout
            # so a hung connection cannot block the collector thread indefinitely.
            logger.debug("Falling back to direct feedparser fetch for '%s'", self.config.name)
            import socket
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self.config.timeout)
            try:
                feed = feedparser.parse(self.config.url)
            finally:
                socket.setdefaulttimeout(old_timeout)

        if feed.bozo and not feed.entries:
            raise ValueError(
                f"Malformed feed from '{self.config.name}': {feed.bozo_exception}"
            )

        _MAX_TITLE = 500
        _MAX_SUMMARY = 5_000

        items: list[RawItem] = []
        for entry in feed.entries[: self.max_items]:
            url: str = entry.get("link", "").strip()
            title: str = entry.get("title", "").strip()
            if not url or not title:
                continue

            # Reject implausibly long titles (likely malformed/malicious entries)
            if len(title) > _MAX_TITLE:
                logger.debug("Skipping oversized title from '%s'", self.config.name)
                continue

            # Extract best available summary text
            summary_raw: Optional[str] = (
                entry.get("summary")
                or entry.get("description")
                or (entry.get("content") or [{}])[0].get("value")
            )
            summary = _strip_html(summary_raw)
            if summary and len(summary) > _MAX_SUMMARY:
                summary = summary[:_MAX_SUMMARY] + "…"

            published_at = _parse_entry_date(entry)

            # Merge source-level tags with feed entry tags
            entry_tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
            tags = list(set(filter(None, self.config.tags + entry_tags)))

            items.append(
                RawItem(
                    title=title,
                    url=url,
                    source_name=self.config.name,
                    source_type=SourceType.RSS,
                    source_credibility=self.config.credibility,
                    stream=self.config.stream,
                    published_at=published_at,
                    summary=summary,
                    tags=tags,
                    raw_data={
                        "feed_title": feed.feed.get("title", ""),
                        "entry_id": entry.get("id", ""),
                    },
                )
            )

        return items
