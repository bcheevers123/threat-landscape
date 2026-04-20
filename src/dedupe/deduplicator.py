"""
Deduplication of normalised RawItems into ThreatCandidates.

Strategy
--------
1. Group items that share the same canonical URL (exact duplicates).
2. Among URL-unique representatives, group items whose titles score above a
   fuzzy-match threshold (same story covered by multiple sources).
3. In each group, elect the most credible source as the primary item and
   fold the rest into ``supporting_sources``.

The result is a list of ThreatCandidates where each candidate represents
a distinct story, with ``corroboration_count`` indicating how many independent
sources reported it.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from rapidfuzz import fuzz

from src.models.schemas import RawItem, ThreatCandidate

logger = logging.getLogger(__name__)

# Fuzzy match threshold (0–100).
# WRatio combines partial_ratio, token_sort_ratio, and token_set_ratio, making
# it better at catching paraphrased headlines than token_sort_ratio alone.
TITLE_SIMILARITY_THRESHOLD = 82


def _url_key(url: str) -> str:
    """Canonical URL key for exact-duplicate detection."""
    parsed = urlparse(url.lower())
    return f"{parsed.netloc}{parsed.path}".rstrip("/")


def _titles_similar(a: str, b: str) -> bool:
    """Return True when two titles are similar enough to be the same story."""
    score = fuzz.WRatio(a.lower(), b.lower())
    return score >= TITLE_SIMILARITY_THRESHOLD


def _build_candidate(primary: RawItem, duplicates: list[RawItem]) -> ThreatCandidate:
    """Merge a primary item and its duplicates into a ThreatCandidate."""
    all_items = [primary] + duplicates

    supporting = list(
        {item.source_name for item in all_items if item.source_name != primary.source_name}
    )
    max_credibility = max(item.source_credibility for item in all_items)

    # Use the richest available summary
    summary = primary.summary
    if not summary:
        for item in duplicates:
            if item.summary:
                summary = item.summary
                break

    # Use the richest available full text
    full_text = primary.full_text
    if not full_text:
        for item in duplicates:
            if item.full_text:
                full_text = item.full_text
                break

    tags = list({tag for item in all_items for tag in item.tags})

    return ThreatCandidate(
        id=primary.id,
        title=primary.title,
        primary_url=primary.url,
        primary_source=primary.source_name,
        supporting_sources=supporting,
        published_at=primary.published_at,
        collected_at=primary.collected_at,
        summary=summary,
        full_text=full_text,
        tags=tags,
        corroboration_count=len({item.source_name for item in all_items}),
        max_source_credibility=max_credibility,
        raw_items=all_items,
    )


def deduplicate(items: list[RawItem]) -> list[ThreatCandidate]:
    """
    Deduplicate normalised RawItems and return a list of ThreatCandidates.

    Items are processed in descending source-credibility order so that the
    highest-quality source is always elected as the primary representative.
    """
    if not items:
        return []

    # Highest credibility first — used as primary in merged groups
    sorted_items = sorted(items, key=lambda x: x.source_credibility, reverse=True)

    # --- Pass 1: group by canonical URL ---
    url_groups: dict[str, list[RawItem]] = {}
    for item in sorted_items:
        key = _url_key(item.url)
        url_groups.setdefault(key, []).append(item)

    # Representative (most credible) per URL group
    url_reps: list[RawItem] = []
    url_dups: list[list[RawItem]] = []
    for group in url_groups.values():
        url_reps.append(group[0])
        url_dups.append(group[1:])

    # --- Pass 2: merge representatives by title similarity ---
    merged: list[tuple[RawItem, list[RawItem]]] = []
    used = [False] * len(url_reps)

    for i, primary in enumerate(url_reps):
        if used[i]:
            continue
        used[i] = True
        combined_dups: list[RawItem] = list(url_dups[i])

        for j in range(i + 1, len(url_reps)):
            if used[j]:
                continue
            if _titles_similar(primary.title, url_reps[j].title):
                used[j] = True
                combined_dups.append(url_reps[j])
                combined_dups.extend(url_dups[j])

        merged.append((primary, combined_dups))

    candidates = [_build_candidate(primary, dups) for primary, dups in merged]
    logger.info(
        "Deduplication: %d items → %d candidates.", len(items), len(candidates)
    )
    return candidates
