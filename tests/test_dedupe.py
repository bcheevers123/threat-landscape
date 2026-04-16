"""Tests for the deduplication module."""
from __future__ import annotations

from src.models.schemas import RawItem, SourceType
from src.dedupe.deduplicator import deduplicate, _url_key, _titles_similar


def _item(title: str, url: str, source: str = "Source A", credibility: float = 0.8) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        source_name=source,
        source_type=SourceType.RSS,
        source_credibility=credibility,
    )


class TestUrlKey:
    def test_strips_trailing_slash(self):
        assert _url_key("https://example.com/path/") == _url_key("https://example.com/path")

    def test_lowercases(self):
        assert _url_key("https://EXAMPLE.com/Path") == _url_key("https://example.com/path")


class TestTitlesSimilar:
    def test_identical_titles(self):
        assert _titles_similar("Ransomware hits NHS", "Ransomware hits NHS")

    def test_reordered_words(self):
        assert _titles_similar(
            "Critical RCE Vulnerability in Apache",
            "Apache RCE Vulnerability Critical",
        )

    def test_dissimilar_titles(self):
        assert not _titles_similar(
            "Ransomware hits NHS",
            "New phishing campaign targets banks",
        )


class TestDeduplicate:
    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_single_item(self):
        items = [_item("Some threat", "https://a.com/1")]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].corroboration_count == 1

    def test_exact_url_duplicates_merged(self):
        items = [
            _item("Ransomware hits NHS", "https://a.com/story", "Source A", 0.9),
            _item("Ransomware hits NHS", "https://a.com/story", "Source B", 0.8),
        ]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].corroboration_count == 2

    def test_title_similarity_merges_different_urls(self):
        items = [
            _item("LockBit Ransomware Attacks Healthcare", "https://a.com/1", "Source A", 0.9),
            _item("LockBit Ransomware Attacks Healthcare Sector", "https://b.com/2", "Source B", 0.8),
        ]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].corroboration_count == 2
        assert "Source B" in result[0].supporting_sources

    def test_distinct_items_not_merged(self):
        items = [
            _item("Ransomware hits NHS", "https://a.com/1", "Source A"),
            _item("Chinese APT targets government", "https://b.com/2", "Source B"),
            _item("New zero-day in Windows", "https://c.com/3", "Source C"),
        ]
        result = deduplicate(items)
        assert len(result) == 3

    def test_most_credible_source_is_primary(self):
        items = [
            _item("Critical Vuln", "https://a.com/1", "Low Credibility Source", 0.5),
            _item("Critical Vuln", "https://b.com/2", "High Credibility Source", 0.95),
        ]
        result = deduplicate(items)
        assert len(result) == 1
        assert result[0].primary_source == "High Credibility Source"

    def test_summary_fallback_from_duplicate(self):
        # Titles must be similar enough to trigger merging (>= threshold)
        items = [
            _item("Critical Ransomware Attack on NHS Hospitals", "https://a.com/1", "Source A"),
            _item("Critical Ransomware Attack on NHS Hospital Systems", "https://b.com/2", "Source B"),
        ]
        # Give the second item a summary; the first has none
        items[1] = items[1].model_copy(update={"summary": "Useful summary text here."})
        result = deduplicate(items)
        assert len(result) == 1
        # Summary should be picked up from the duplicate that has one
        assert result[0].summary is not None
