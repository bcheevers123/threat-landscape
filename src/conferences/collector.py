"""Load and filter conference events from the curated YAML data file."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import yaml

from src.conferences.models import ConferenceEvent

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA = _PROJECT_ROOT / "data" / "conferences.yaml"


def load_events(
    data_file: Path = _DEFAULT_DATA,
    lookforward_days: int = 365,
    include_ongoing: bool = True,
) -> list[ConferenceEvent]:
    """
    Load conference events from YAML, filtered to the next *lookforward_days* days.

    Events that have already ended are excluded. Ongoing events (started but not
    yet ended) are included when *include_ongoing* is True.
    """
    if not data_file.exists():
        logger.warning("Conference data file not found: %s", data_file)
        return []

    with data_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    today = date.today()
    cutoff = today + timedelta(days=lookforward_days)

    events: list[ConferenceEvent] = []
    for item in raw.get("events", []):
        try:
            event = ConferenceEvent(**item)
        except Exception as exc:
            logger.warning("Skipping malformed event %r: %s", item.get("name"), exc)
            continue

        # Skip past events whose end date has already passed
        if event.end_date < today:
            continue

        # Skip events that start after the look-forward window
        if event.start_date > cutoff:
            continue

        events.append(event)

    events.sort(key=lambda e: (e.start_date, e.name))
    logger.info("Loaded %d conference events (within %d days)", len(events), lookforward_days)
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
