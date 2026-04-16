"""
Normalisation pass for raw collected items.

Converts all RawItems into a consistent canonical form before deduplication
and scoring.  Handles URL canonicalisation, HTML entity decoding, and
whitespace normalisation.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from src.models.schemas import RawItem

logger = logging.getLogger(__name__)

# Query-string parameters that carry no semantic value
_STRIP_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "ref", "referer", "fbclid", "gclid", "mc_cid", "mc_eid",
})

# HTML entity map for common entities that appear in feed titles/summaries
_HTML_ENTITIES: dict[str, str] = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
    "&apos;": "'", "&#8217;": "\u2019", "&#8216;": "\u2018",
    "&#8220;": "\u201c", "&#8221;": "\u201d", "&#8230;": "\u2026",
    "&#8211;": "\u2013", "&#8212;": "\u2014", "&nbsp;": " ",
}


def normalise_url(url: str) -> str:
    """
    Return a canonical form of a URL.

    - Lowercases scheme and host
    - Strips trailing slash from path
    - Removes known tracking query parameters
    """
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        filtered_params = {
            k: v
            for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
            if k.lower() not in _STRIP_PARAMS
        }
        query = urlencode(filtered_params, doseq=True)
        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.strip()


def normalise_title(title: str) -> str:
    """Strip excess whitespace, decode HTML entities, and trim."""
    for entity, replacement in _HTML_ENTITIES.items():
        title = title.replace(entity, replacement)
    # Remove any remaining numeric entities
    title = re.sub(r"&#\d+;", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


def normalise_item(item: RawItem) -> RawItem:
    """Return a copy of item with normalised title, URL, and published_at."""
    return item.model_copy(
        update={
            "title": normalise_title(item.title),
            "url": normalise_url(item.url),
            # Ensure published_at is always set; fall back to collected_at
            "published_at": item.published_at or item.collected_at,
        }
    )


def normalise_items(items: list[RawItem]) -> list[RawItem]:
    """
    Normalise a list of raw items.

    Items missing a title or URL are silently discarded.
    Any item that raises during normalisation is logged and skipped.
    """
    normalised: list[RawItem] = []
    for item in items:
        try:
            norm = normalise_item(item)
            # Reject empty titles and URLs that reduced to just "/" or empty
            if norm.title and norm.url and norm.url not in ("", "/"):
                normalised.append(norm)
            else:
                logger.debug("Discarding item with empty title or URL: %s", item.url)
        except Exception as exc:
            logger.warning(
                "Normalisation failed for item '%s': %s", item.url, exc
            )
    logger.info(
        "Normalisation: %d/%d items retained.", len(normalised), len(items)
    )
    return normalised
