"""Tests for the URL and title normalisation module."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models.schemas import RawItem, SourceType
from src.normalisers.normaliser import normalise_item, normalise_items, normalise_url, normalise_title


def _item(**kwargs) -> RawItem:
    defaults = dict(
        title="Test Title",
        url="https://example.com/article",
        source_name="Test Source",
        source_type=SourceType.RSS,
        source_credibility=0.8,
    )
    defaults.update(kwargs)
    return RawItem(**defaults)


class TestNormaliseUrl:
    def test_strips_trailing_slash(self):
        assert normalise_url("https://example.com/path/") == "https://example.com/path"

    def test_lowercases_scheme_and_host(self):
        result = normalise_url("HTTPS://EXAMPLE.COM/path")
        assert result.startswith("https://example.com")

    def test_removes_utm_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social&id=123"
        result = normalise_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=123" in result

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/search?q=ransomware&page=2"
        result = normalise_url(url)
        assert "q=ransomware" in result
        assert "page=2" in result

    def test_handles_malformed_url(self):
        # Should not raise; returns the input
        result = normalise_url("not-a-url")
        assert result == "not-a-url"


class TestNormaliseTitle:
    def test_collapses_whitespace(self):
        assert normalise_title("  Hello   World  ") == "Hello World"

    def test_decodes_html_entities(self):
        assert normalise_title("AT&amp;T Breach") == "AT&T Breach"
        assert normalise_title("&lt;script&gt;") == "<script>"

    def test_decodes_curly_quotes(self):
        assert normalise_title("It&#8217;s here") == "It\u2019s here"

    def test_removes_numeric_entities(self):
        result = normalise_title("Hello&#160;World")
        assert "&#160;" not in result


class TestNormaliseItem:
    def test_fallback_published_at(self):
        item = _item(published_at=None)
        norm = normalise_item(item)
        assert norm.published_at is not None
        # Should fall back to collected_at
        assert norm.published_at == item.collected_at

    def test_preserves_published_at_when_set(self):
        dt = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        item = _item(published_at=dt)
        norm = normalise_item(item)
        assert norm.published_at == dt

    def test_normalises_url(self):
        item = _item(url="HTTPS://Example.COM/Article/?utm_source=email")
        norm = normalise_item(item)
        assert norm.url == "https://example.com/Article"

    def test_normalises_title(self):
        item = _item(title="  AT&amp;T Hacked  ")
        norm = normalise_item(item)
        assert norm.title == "AT&T Hacked"


class TestNormaliseItems:
    def test_filters_empty_url(self):
        items = [_item(), _item(url="")]
        result = normalise_items(items)
        assert len(result) == 1

    def test_filters_empty_title(self):
        items = [_item(), _item(title="")]
        result = normalise_items(items)
        assert len(result) == 1

    def test_returns_all_valid(self):
        items = [_item(url=f"https://example.com/{i}") for i in range(5)]
        result = normalise_items(items)
        assert len(result) == 5
