"""
Core data models for the Threat Landscape pipeline.

All pipeline stages exchange data using these pydantic models, ensuring
consistent structure and type safety throughout.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    RSS = "rss"
    HTTP = "http"
    API = "api"


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------

class SourceConfig(BaseModel):
    """Configuration for a single intelligence source."""

    name: str
    url: str
    type: SourceType = SourceType.RSS
    credibility: float = Field(0.5, ge=0.0, le=1.0)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""
    stream: str = "technical"  # "technical" | "mainstream" | "both"
    notes: str = ""             # human-readable status note, shown in source debug page
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: int = 30


# ---------------------------------------------------------------------------
# Raw collector output
# ---------------------------------------------------------------------------

class RawItem(BaseModel):
    """
    A single item returned by any collector.

    Collectors must populate at minimum: title, url, source_name, source_type,
    source_credibility.  All other fields are best-effort.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    url: str
    source_name: str
    source_type: SourceType = SourceType.RSS
    source_credibility: float = Field(0.5, ge=0.0, le=1.0)
    stream: str = "technical"  # inherited from SourceConfig.stream
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    summary: Optional[str] = None
    full_text: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Deduplication output
# ---------------------------------------------------------------------------

class ThreatCandidate(BaseModel):
    """
    A deduplicated, source-merged threat item ready for scoring and enrichment.

    Multiple RawItems covering the same story are merged into a single
    ThreatCandidate; corroboration_count reflects how many sources reported it.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    primary_url: str
    primary_source: str
    supporting_sources: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    summary: Optional[str] = None
    full_text: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    corroboration_count: int = 1
    max_source_credibility: float = 0.5
    raw_items: list[RawItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Enriched output models
# ---------------------------------------------------------------------------

class AttackTechnique(BaseModel):
    """A MITRE ATT&CK technique inferred from available evidence."""

    technique_id: str   # e.g. "T1566"
    technique_name: str
    tactic: str
    confidence: ConfidenceLevel = ConfidenceLevel.LOW


class Attribution(BaseModel):
    """Threat actor attribution derived from source reporting."""

    actor_name: str
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    source_statement: Optional[str] = None


class ScoreBreakdown(BaseModel):
    """Per-dimension contribution to the overall threat score."""

    recency: float = 0.0
    source_credibility: float = 0.0
    corroboration: float = 0.0
    severity: float = 0.0
    breadth: float = 0.0
    actionability: float = 0.0
    total: float = 0.0


class EnrichedThreat(BaseModel):
    """
    A fully enriched threat entry ready for rendering and STIX export.

    All analytical fields (ATT&CK mapping, attribution, affected countries) are
    best-effort.  Uncertain fields should use "Unknown" / "Unconfirmed" values
    and be accompanied by a confidence_note.
    """

    id: str
    title: str
    primary_url: str
    primary_source: str
    supporting_sources: list[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None

    # Enriched narrative fields
    summary: str = ""
    why_it_matters: str = ""

    # Analytical fields (all best-effort)
    attack_techniques: list[AttackTechnique] = Field(default_factory=list)
    attribution: list[Attribution] = Field(default_factory=list)

    # Affected scope
    countries_affected: list[str] = Field(default_factory=list)
    companies_affected: list[str] = Field(default_factory=list)
    industries_affected: list[str] = Field(default_factory=list)

    # Threat classification
    threat_types: list[str] = Field(default_factory=list)

    # Indicators
    cves: list[str] = Field(default_factory=list)
    malware_families: list[str] = Field(default_factory=list)

    # Scoring
    score: float = 0.0
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)

    # STIX export
    stix_bundle: Optional[dict[str, Any]] = None
    stix_file: Optional[str] = None   # relative path within output dir

    # Supporting source details (name + article URL for corroborating reports)
    supporting_source_details: list[dict[str, str]] = Field(default_factory=list)

    # Provenance and confidence
    corroboration_count: int = 1
    confidence_note: Optional[str] = None

    # NVD-enriched CVE details: CVE ID → {"score": float, "severity": str, "vector": str}
    cve_details: dict[str, Any] = Field(default_factory=dict)

    # Number of consecutive days this item appeared in the top 10
    prevalent_days: int = 0


# ---------------------------------------------------------------------------
# Pipeline output
# ---------------------------------------------------------------------------

class SourceSummary(BaseModel):
    """Lightweight record of a source that was queried during collection."""

    name: str
    credibility: float
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""
    stream: str = "technical"  # "technical" | "mainstream" | "both"


class ThreatLandscapeOutput(BaseModel):
    """The complete daily threat landscape produced by the pipeline."""

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    threats: list[EnrichedThreat] = Field(default_factory=list)
    mainstream_threats: list[EnrichedThreat] = Field(default_factory=list)
    total_items_collected: int = 0
    total_items_after_dedupe: int = 0
    generation_notes: list[str] = Field(default_factory=list)
    sources_queried: list[SourceSummary] = Field(default_factory=list)
    # Per-source item counts after collection (source_name → item count; 0 = unhealthy)
    source_health: dict[str, int] = Field(default_factory=dict)

    def to_json_safe(self) -> dict[str, Any]:
        """Return a dict suitable for JSON serialisation (datetime → str)."""
        return self.model_dump(mode="json")
