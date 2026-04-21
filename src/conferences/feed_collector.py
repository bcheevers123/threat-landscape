"""
Conference feed collector.

Fetches conference data from external sources (JSON APIs and RSS feeds)
defined in conferences/config/feeds.yaml, converts them to ConferenceEvent
objects, and returns them for merging with the static YAML.

Design principles:
  - Fail gracefully: a broken feed never breaks the build
  - Prefer quality over quantity: skip any item missing start_date or country
  - Deduplicate against the static YAML by normalised URL
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
import yaml

from src.conferences.models import ConferenceEvent

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_FEEDS = _PROJECT_ROOT / "conferences" / "config" / "feeds.yaml"

_COST_MAP = {
    "free": "Free",
    "0": "Free",
    "paid": "Paid",
}

_TAG_NORMALISE = {
    "security": "Industry",
    "hacking": "Hacking",
    "offensive": "Offensive",
    "defensive": "Defensive",
    "research": "Research",
    "ctf": "CTF",
    "training": "Training",
    "privacy": "Privacy",
    "malware": "Malware",
    "threat intelligence": "Threat-Intel",
    "threat-intel": "Threat-Intel",
    "appsec": "AppSec",
    "academic": "Academic",
    "beginner": "Beginner-Friendly",
    "beginner-friendly": "Beginner-Friendly",
    "government": "Government",
    "enterprise": "Enterprise",
    "regional": "Regional",
    "ics": "ICS/OT",
    "ot": "ICS/OT",
}


def _normalise_url(url: str) -> str:
    """Strip scheme/www/trailing slash for dedup comparison."""
    parsed = urlparse(url.lower().strip())
    host = parsed.netloc.lstrip("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    # Try ISO-8601 with time component
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        pass
    return None


def _normalise_tags(raw_tags: list[str], defaults: list[str]) -> list[str]:
    result: set[str] = set(defaults)
    for t in raw_tags:
        normalised = _TAG_NORMALISE.get(t.lower().strip())
        if normalised:
            result.add(normalised)
        elif t.strip():
            result.add(t.strip().capitalize())
    return sorted(result)


def _fetch_json_api(feed: dict) -> list[ConferenceEvent]:
    """Fetch a JSON API endpoint that returns a list of conference objects."""
    url = feed["url"]
    field_map: dict[str, str] = feed.get("field_map", {})
    tag_defaults: list[str] = feed.get("tag_defaults", [])

    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": "ThreatLandscape/1.0 conference-collector"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Feed '%s' fetch failed: %s", feed["name"], exc)
        return []

    # Handle both top-level list and {"conferences": [...]} envelope
    if isinstance(data, dict):
        for key in ("conferences", "events", "data", "results"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
    if not isinstance(data, list):
        logger.warning("Feed '%s' returned unexpected JSON shape", feed["name"])
        return []

    events: list[ConferenceEvent] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get(field_map.get("name", "name"), "")
        url_val = item.get(field_map.get("url", "url"), "")
        if not name or not url_val:
            continue

        start = _parse_date(item.get(field_map.get("start_date", "start_date")))
        end   = _parse_date(item.get(field_map.get("end_date",   "end_date")))
        if not start:
            continue
        if not end or end < start:
            end = start

        city    = item.get(field_map.get("city",    "city"),    "") or ""
        country = item.get(field_map.get("country", "country"), "") or ""
        if not country:
            continue

        desc = item.get(field_map.get("description", "description"), "") or ""
        raw_cost = str(item.get(field_map.get("cost", "cost"), "") or "").lower()
        cost = _COST_MAP.get(raw_cost, "Paid")

        raw_tags = item.get("tags", item.get("categories", [])) or []
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        tags = _normalise_tags(raw_tags, tag_defaults)

        try:
            events.append(ConferenceEvent(
                name=str(name).strip(),
                url=str(url_val).strip(),
                start_date=start,
                end_date=end,
                city=str(city).strip(),
                country=str(country).strip(),
                tags=tags,
                description=str(desc).strip()[:500],
                cost=cost,
            ))
        except Exception as exc:
            logger.debug("Skipping malformed feed item '%s': %s", name, exc)

    logger.info("Feed '%s' yielded %d events", feed["name"], len(events))
    return events


# Patterns to extract dates from RSS titles/descriptions
_DATE_RE = re.compile(
    r"(\d{1,2}[\s\-/]\w+[\s\-/]\d{4}|\w+ \d{1,2}[-–]\d{1,2},? \d{4}|"
    r"\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})"
)
_COUNTRY_HINTS = {
    "usa": "USA", "united states": "USA", "u.s.": "USA",
    "uk": "UK", "united kingdom": "UK", "england": "UK",
    "germany": "Germany", "deutschland": "Germany",
    "france": "France", "netherlands": "Netherlands",
    "australia": "Australia", "canada": "Canada",
    "singapore": "Singapore", "india": "India",
    "ireland": "Ireland", "austria": "Austria",
    "belgium": "Belgium", "switzerland": "Switzerland",
    "spain": "Spain", "italy": "Italy", "poland": "Poland",
    "sweden": "Sweden", "norway": "Norway", "finland": "Finland",
    "denmark": "Denmark", "israel": "Israel", "japan": "Japan",
    "taiwan": "Taiwan", "south korea": "South Korea",
    "philippines": "Philippines", "kenya": "Kenya",
    "south africa": "South Africa", "online": "Online",
    "virtual": "Online",
}


def _extract_country(text: str) -> Optional[str]:
    lower = text.lower()
    for hint, country in _COUNTRY_HINTS.items():
        if hint in lower:
            return country
    return None


def _fetch_rss(feed: dict) -> list[ConferenceEvent]:
    """
    Fetch an RSS feed and attempt to extract conference events.

    RSS feeds rarely carry structured date/location data, so this parser
    does best-effort extraction and skips items it cannot reliably parse.
    """
    url = feed["url"]
    tag_defaults: list[str] = feed.get("tag_defaults", [])

    try:
        resp = requests.get(url, timeout=20,
                            headers={"User-Agent": "ThreatLandscape/1.0 conference-collector"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.warning("RSS feed '%s' fetch failed: %s", feed["name"], exc)
        return []

    ns = {}
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    events: list[ConferenceEvent] = []

    for item in items:
        def _text(tag: str) -> str:
            el = item.find(tag, ns)
            return (el.text or "").strip() if el is not None else ""

        title = _text("title")
        link  = _text("link")
        desc  = _text("description") or _text("summary")
        pub   = _text("pubDate") or _text("published")

        if not title or not link:
            continue

        combined = f"{title} {desc}"

        # Try to find a start date
        date_matches = _DATE_RE.findall(combined)
        start = None
        for dm in date_matches:
            start = _parse_date(dm)
            if start:
                break
        if not start:
            start = _parse_date(pub)
        if not start:
            continue

        end = start

        # Try to find a country
        country = _extract_country(combined)
        if not country:
            continue

        # Best-effort city extraction (word before country name)
        city = "Unknown"
        for hint in _COUNTRY_HINTS:
            idx = combined.lower().find(hint)
            if idx > 5:
                before = combined[max(0, idx - 30):idx].strip()
                words = re.findall(r"[A-Z][a-z]+", before)
                if words:
                    city = words[-1]
                break

        tags = _normalise_tags([], tag_defaults)

        try:
            events.append(ConferenceEvent(
                name=title.strip()[:120],
                url=link.strip(),
                start_date=start,
                end_date=end,
                city=city,
                country=country,
                tags=tags,
                description=re.sub(r"<[^>]+>", "", desc).strip()[:400],
                cost="Unknown",
            ))
        except Exception as exc:
            logger.debug("Skipping RSS item '%s': %s", title, exc)

    logger.info("RSS feed '%s' yielded %d parseable events", feed["name"], len(events))
    return events


def fetch_feed_events(
    feeds_file: Path = _DEFAULT_FEEDS,
    existing_urls: frozenset[str] | None = None,
    lookforward_days: int = 365,
) -> list[ConferenceEvent]:
    """
    Fetch all enabled feeds, return new ConferenceEvent objects that are not
    already in *existing_urls* (normalised) and are within *lookforward_days*.
    """
    if not feeds_file.exists():
        logger.info("No feeds config at %s — skipping feed collection", feeds_file)
        return []

    with feeds_file.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    feeds = [f for f in cfg.get("feeds", []) if f.get("enabled", True)]
    if not feeds:
        return []

    existing = existing_urls or frozenset()
    today = date.today()
    from datetime import timedelta
    cutoff = today + timedelta(days=lookforward_days)

    all_new: list[ConferenceEvent] = []
    seen_urls: set[str] = set(existing)

    for feed in feeds:
        feed_type = feed.get("type", "rss")
        try:
            if feed_type == "json_api":
                raw = _fetch_json_api(feed)
            else:
                raw = _fetch_rss(feed)
        except Exception as exc:
            logger.warning("Unexpected error in feed '%s': %s", feed.get("name"), exc)
            raw = []

        for ev in raw:
            norm = _normalise_url(ev.url)
            if norm in seen_urls:
                continue
            if ev.end_date < today or ev.start_date > cutoff:
                continue
            seen_urls.add(norm)
            all_new.append(ev)

    logger.info("Feed collection complete — %d new events found", len(all_new))
    return all_new
