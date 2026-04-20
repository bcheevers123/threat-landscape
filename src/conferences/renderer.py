"""Render conference events to HTML and JSON output."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.conferences.models import ConferenceEvent

logger = logging.getLogger(__name__)


class ConferencesRenderer:
    def __init__(
        self,
        template_dir: Path,
        output_dir: Path,
        static_dir: Path,
        branding: dict[str, Any] | None = None,
    ) -> None:
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.static_dir = static_dir
        self.branding = branding or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render_json(self, events: list[ConferenceEvent]) -> Path:
        payload = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "event_count": len(events),
            "events": [e.to_dict() for e in events],
        }
        out = self.output_dir / "latest.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Wrote %s", out)
        return out

    def render_html(
        self,
        events: list[ConferenceEvent],
        stats: dict,
        all_tags: list[str],
    ) -> Path:
        def _fmt_date(d: "date") -> str:
            """Format a date as '1 Jan 2026' with no leading zero."""
            return f"{d.day} {d.strftime('%b %Y')}"

        env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "j2"]),
        )
        env.filters["fmt_date"] = _fmt_date
        template = env.get_template("index.html.j2")

        generated_at = datetime.now(tz=timezone.utc).strftime("%d %B %Y")
        events_json = json.dumps([e.to_dict() for e in events], ensure_ascii=False)

        html = template.render(
            events=events,
            events_json=events_json,
            all_tags=all_tags,
            stats=stats,
            generated_at=generated_at,
            branding=self.branding,
        )
        out = self.output_dir / "index.html"
        out.write_text(html, encoding="utf-8")
        logger.info("Wrote %s", out)
        return out

    def copy_static_assets(self) -> None:
        if not self.static_dir.exists():
            logger.warning("Static dir '%s' not found — skipping.", self.static_dir)
            return
        dest = self.output_dir / "static"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(str(self.static_dir), str(dest))
        logger.info("Copied static assets to %s", dest)

    def render_all(
        self,
        events: list[ConferenceEvent],
        stats: dict,
        all_tags: list[str],
    ) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        paths["html"]    = self.render_html(events, stats, all_tags)
        paths["json"]    = self.render_json(events)
        self.copy_static_assets()
        return paths
