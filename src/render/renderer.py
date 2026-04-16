"""
Jinja2-based renderer.

Produces:
  - output/index.html       — standalone polished HTML page
  - output/latest.json      — machine-readable JSON for the WordPress plugin
  - output/stix/<id>.json   — individual STIX 2.1 bundles
  - output/static/          — copy of CSS/JS assets
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models.schemas import EnrichedThreat, ThreatLandscapeOutput

logger = logging.getLogger(__name__)


def _safe_json_for_script(obj: Any) -> str:
    """
    Serialise obj to JSON safe for embedding inside a <script> block.

    Escapes the forward-slash in </script> sequences so that malicious feed
    content cannot break out of the script context.  This is a defence-in-depth
    measure; Jinja2 autoescape also applies to the surrounding template.
    """
    raw = json.dumps(obj, indent=2)
    # Replace </ with <\/ — valid JSON and safe inside any HTML script context.
    return raw.replace("</", "<\\/")


def _threat_to_dict(threat: EnrichedThreat) -> dict[str, Any]:
    """Convert an EnrichedThreat to a template-friendly plain dict."""
    stix_json_str = ""
    if threat.stix_bundle:
        stix_json_str = _safe_json_for_script(threat.stix_bundle)

    pub = (
        threat.published_at.strftime("%d %B %Y, %H:%M UTC")
        if threat.published_at
        else "Unknown"
    )

    return {
        "id": threat.id,
        "title": threat.title,
        "primary_url": threat.primary_url,
        "primary_source": threat.primary_source,
        "supporting_sources": threat.supporting_sources,
        "supporting_source_details": threat.supporting_source_details,
        "published_at": pub,
        "summary": threat.summary,
        "why_it_matters": threat.why_it_matters,
        "attack_techniques": [
            {
                "id": t.technique_id,
                "name": t.technique_name,
                "tactic": t.tactic,
                "confidence": t.confidence.value,
                "url": f"https://attack.mitre.org/techniques/{t.technique_id}/",
            }
            for t in threat.attack_techniques
        ],
        "attribution": [
            {
                "name": a.actor_name,
                "confidence": a.confidence.value,
                "statement": a.source_statement or "",
            }
            for a in threat.attribution
        ],
        "countries_affected": threat.countries_affected or ["Unknown"],
        "companies_affected": threat.companies_affected,
        "industries_affected": threat.industries_affected or ["Unknown"],
        "threat_types": threat.threat_types,
        "cves": threat.cves,
        "malware_families": threat.malware_families,
        "score": round(threat.score, 3),
        "score_tier": (
            "high" if threat.score >= 0.70 else
            "medium" if threat.score >= 0.55 else
            "low"
        ),
        "score_tier_label": (
            "High" if threat.score >= 0.70 else
            "Medium" if threat.score >= 0.55 else
            "Low"
        ),
        "score_breakdown": (
            threat.score_breakdown.model_dump()
            if threat.score_breakdown
            else {}
        ),
        "stix_json": stix_json_str,
        "stix_file": threat.stix_file,
        "corroboration_count": threat.corroboration_count,
        "confidence_note": threat.confidence_note or "",
    }


class Renderer:
    """Renders threat landscape output to HTML and JSON."""

    def __init__(
        self,
        template_dir: Path,
        output_dir: Path,
        static_dir: Path,
        branding: Optional[dict[str, Any]] = None,
    ) -> None:
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.static_dir = static_dir
        self.branding = branding or {}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "htm"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_html(self, output: ThreatLandscapeOutput) -> Path:
        """Render index.html from the Jinja2 template."""
        template = self._env.get_template("index.html.j2")

        # Each threat dict gets a stable list_idx used for HTML element IDs so
        # the two lists (technical / mainstream) never collide.
        threats_data = [
            {**_threat_to_dict(t), "stream": "technical", "list_idx": f"t{i + 1}"}
            for i, t in enumerate(output.threats)
        ]
        mainstream_data = [
            {**_threat_to_dict(t), "stream": "mainstream", "list_idx": f"m{i + 1}"}
            for i, t in enumerate(output.mainstream_threats)
        ]

        sources_data = [
            {
                "name": s.name,
                "credibility": s.credibility,
                "credibility_pct": int(s.credibility * 100),
                "tags": s.tags,
                "rationale": s.rationale,
                "stream": s.stream,
            }
            for s in sorted(output.sources_queried, key=lambda x: x.credibility, reverse=True)
        ]

        html = template.render(
            threats=threats_data,
            mainstream_threats=mainstream_data,
            generated_at=output.generated_at.strftime("%d %B %Y at %H:%M UTC"),
            total_collected=output.total_items_collected,
            total_after_dedupe=output.total_items_after_dedupe,
            generation_notes=output.generation_notes,
            sources_queried=sources_data,
            branding=self.branding,
        )

        path = self.output_dir / "index.html"
        path.write_text(html, encoding="utf-8")
        logger.info("HTML written to %s", path)
        return path

    def render_json(self, output: ThreatLandscapeOutput) -> Path:
        """Render latest.json for the WordPress plugin."""
        data = output.model_dump(mode="json")
        path = self.output_dir / "latest.json"
        path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        logger.info("JSON written to %s", path)
        return path

    def render_stix_files(self, output: ThreatLandscapeOutput) -> list[Path]:
        """Write one STIX JSON file per threat into output/stix/."""
        stix_dir = self.output_dir / "stix"
        stix_dir.mkdir(exist_ok=True)
        written: list[Path] = []
        for threat in output.threats:
            if threat.stix_bundle:
                path = stix_dir / f"{threat.id}.json"
                path.write_text(
                    json.dumps(threat.stix_bundle, indent=2), encoding="utf-8"
                )
                written.append(path)
        logger.info("Wrote %d STIX bundle(s).", len(written))
        return written

    def copy_static_assets(self) -> None:
        """Copy static CSS/JS assets into output/static/."""
        if not self.static_dir.exists():
            logger.warning("Static dir '%s' not found; skipping.", self.static_dir)
            return
        dest = self.output_dir / "static"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(str(self.static_dir), str(dest))
        logger.info("Static assets copied to %s", dest)

    def render_all(self, output: ThreatLandscapeOutput) -> dict[str, Path]:
        """Run all rendering steps and return a dict of output paths."""
        paths: dict[str, Path] = {}
        paths["html"] = self.render_html(output)
        paths["json"] = self.render_json(output)
        stix_files = self.render_stix_files(output)
        if stix_files:
            paths["stix_dir"] = stix_files[0].parent
        self.copy_static_assets()
        return paths
