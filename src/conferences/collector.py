"""
Load and filter conference events from the curated YAML seed data,
optionally supplemented by live feed collection.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import yaml

from src.conferences.models import ConferenceEvent

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA  = _PROJECT_ROOT / "data" / "conferences.yaml"
_DEFAULT_FEEDS = _PROJECT_ROOT / "conferences" / "config" / "feeds.yaml"


def _normalise_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url.lower().strip())
    host = parsed.netloc.lstrip("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def load_events(
    data_file: Path = _DEFAULT_DATA,
    feeds_file: Path = _DEFAULT_FEEDS,
    lookforward_days: int = 365,
    include_ongoing: bool = True,
    fetch_feeds: bool = True,
) -> list[ConferenceEvent]:
    """
    Load conference events from the YAML seed data, then optionally merge in
    events collected from configured external feeds.

    Events are deduplicated by normalised URL.  Static YAML events take
    precedence — a feed event whose URL already exists in the YAML is dropped.
    """
    if not data_file.exists():
        logger.warning("Conference data file not found: %s", data_file)
        return []

    with data_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    today = date.today()
    cutoff = today + timedelta(days=lookforward_days)

    events: list[ConferenceEvent] = []
    seen_urls: set[str] = set()

    for item in raw.get("events", []):
        try:
            event = ConferenceEvent(**item)
        except Exception as exc:
            logger.warning("Skipping malformed event %r: %s", item.get("name"), exc)
            continue

        if event.end_date < today:
            continue
        if event.start_date > cutoff:
            continue

        events.append(event)
        seen_urls.add(_normalise_url(event.url))

    logger.info("Loaded %d static conference events (within %d days)", len(events), lookforward_days)

    # ── Live feed collection ─────────────────────────────────────────────────
    if fetch_feeds:
        try:
            from src.conferences.feed_collector import fetch_feed_events
            feed_events = fetch_feed_events(
                feeds_file=feeds_file,
                existing_urls=frozenset(seen_urls),
                lookforward_days=lookforward_days,
            )
            if feed_events:
                logger.info("Adding %d event(s) from live feeds", len(feed_events))
                events.extend(feed_events)
        except Exception as exc:
            logger.warning("Feed collection failed (non-fatal): %s", exc)

    events.sort(key=lambda e: (e.start_date, e.name))
    logger.info("Total conference events after merge: %d", len(events))
    return events


def all_tags(events: list[ConferenceEvent]) -> list[str]:
    """Return sorted unique tag list across all events."""
    tags: set[str] = set()
    for e in events:
        tags.update(e.tags)
    return sorted(tags)


def stats(events: list[ConferenceEvent]) -> dict:
    today = date.today()
    upcoming = [e for e in events if e.start_date >= today]
    ongoing  = [e for e in events if e.start_date <= today <= e.end_date]
    countries = {e.country for e in events}
    this_month = [
        e for e in events
        if e.start_date.year == today.year and e.start_date.month == today.month
    ]
    return {
        "total":      len(events),
        "upcoming":   len(upcoming),
        "ongoing":    len(ongoing),
        "countries":  len(countries),
        "this_month": len(this_month),
    }
