"""
STIX 2.1 bundle builder.

Produces a valid STIX 2.1 JSON bundle for each EnrichedThreat.
Only objects supported by available evidence are included; partial bundles
are explicitly allowed when data is incomplete.

Bundle structure per threat:
  - report           (always present)
  - threat-actor     (one per attribution entry)
  - malware          (one per malware family)
  - vulnerability    (one per CVE)
  - attack-pattern   (one per ATT&CK technique)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.models.schemas import EnrichedThreat

logger = logging.getLogger(__name__)


def _stix_id(object_type: str) -> str:
    """Generate a valid STIX 2.1 identifier."""
    return f"{object_type}--{uuid.uuid4()}"


def _now() -> str:
    """Current time as a STIX timestamp string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _to_stix_ts(dt: datetime | None) -> str:
    if dt is None:
        return _now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _confidence_int(level: str) -> int:
    """Map a confidence label to the STIX 0–100 integer scale."""
    return {"High": 85, "Medium": 50, "Low": 25, "Unknown": 0}.get(level, 0)


def build_stix_bundle(threat: EnrichedThreat) -> dict[str, Any]:
    """
    Build and return a STIX 2.1 bundle dict for a single enriched threat.

    The bundle is returned as a plain dict so it can be serialised by the
    standard json module without requiring the stix2 library at runtime.
    (Using stix2 for validation is recommended during development but would
    add a heavy dependency for Raspberry Pi deployment.)
    """
    now = _now()
    published = _to_stix_ts(threat.published_at)

    objects: list[dict[str, Any]] = []
    object_refs: list[str] = []

    external_refs: list[dict[str, Any]] = [
        {
            "source_name": threat.primary_source,
            "url": threat.primary_url,
            "description": threat.title,
        }
    ]

    # ── Threat-actor objects ──────────────────────────────────────────────
    for attr in threat.attribution:
        actor_id = _stix_id("threat-actor")
        objects.append({
            "type": "threat-actor",
            "spec_version": "2.1",
            "id": actor_id,
            "created": now,
            "modified": now,
            "name": attr.actor_name,
            "threat_actor_types": ["unknown"],
            "confidence": _confidence_int(attr.confidence.value),
        })
        object_refs.append(actor_id)

    # ── Malware objects ───────────────────────────────────────────────────
    for family in threat.malware_families:
        mal_id = _stix_id("malware")
        objects.append({
            "type": "malware",
            "spec_version": "2.1",
            "id": mal_id,
            "created": now,
            "modified": now,
            "name": family,
            "malware_types": ["unknown"],
            "is_family": True,
        })
        object_refs.append(mal_id)

    # ── Vulnerability objects (CVEs) ──────────────────────────────────────
    for cve in threat.cves:
        vuln_id = _stix_id("vulnerability")
        objects.append({
            "type": "vulnerability",
            "spec_version": "2.1",
            "id": vuln_id,
            "created": now,
            "modified": now,
            "name": cve,
            "external_references": [
                {
                    "source_name": "cve",
                    "external_id": cve,
                    "url": f"https://cve.mitre.org/cgi-bin/cvename.cgi?name={cve}",
                }
            ],
        })
        object_refs.append(vuln_id)

    # ── Attack-pattern objects (ATT&CK techniques) ────────────────────────
    for technique in threat.attack_techniques:
        ap_id = _stix_id("attack-pattern")
        objects.append({
            "type": "attack-pattern",
            "spec_version": "2.1",
            "id": ap_id,
            "created": now,
            "modified": now,
            "name": technique.technique_name,
            "external_references": [
                {
                    "source_name": "mitre-attack",
                    "external_id": technique.technique_id,
                    "url": (
                        f"https://attack.mitre.org/techniques/"
                        f"{technique.technique_id}/"
                    ),
                }
            ],
            "kill_chain_phases": [
                {
                    "kill_chain_name": "mitre-attack",
                    "phase_name": technique.tactic.lower().replace(" ", "-"),
                }
            ],
        })
        object_refs.append(ap_id)

    # ── Report object (always present) ───────────────────────────────────
    # Self-reference if no other objects were created
    report_id = _stix_id("report")
    report: dict[str, Any] = {
        "type": "report",
        "spec_version": "2.1",
        "id": report_id,
        "created": now,
        "modified": now,
        "name": threat.title,
        "description": threat.summary or threat.title,
        "published": published,
        "report_types": ["threat-report"],
        "object_refs": object_refs if object_refs else [report_id],
        "external_references": external_refs,
        "labels": threat.industries_affected or [],
    }
    # Insert report at the front
    objects.insert(0, report)

    return {
        "type": "bundle",
        "id": _stix_id("bundle"),
        "objects": objects,
    }
