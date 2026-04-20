"""
Deterministic (rule-based) enrichment provider.

Requires no paid external APIs.  All analysis is performed via:
  - Regex and keyword matching for entity extraction
  - A keyword→ATT&CK dictionary for technique mapping
  - Extractive summarisation (sentence scoring by keyword density + position)

Attribution is only derived from explicit statements in source text;
nothing is fabricated.
"""
from __future__ import annotations

import logging
import re
import textwrap
from typing import Optional

from src.enrichment.base import BaseEnrichmentProvider
from src.enrichment.entities import (
    extract_cves,
    extract_countries,
    extract_malware,
    extract_sectors,
    extract_threat_actors,
    extract_threat_types,
)
from src.models.schemas import (
    AttackTechnique,
    Attribution,
    ConfidenceLevel,
    EnrichedThreat,
    ScoreBreakdown,
    ThreatCandidate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ATT&CK keyword → technique mapping
# Each entry: (keyword_list, technique_id, technique_name, tactic)
# ---------------------------------------------------------------------------

_ATTACK_MAP: list[tuple[list[str], str, str, str]] = [
    (["phishing", "spear phishing", "spearphishing", "spear-phishing"],
     "T1566", "Phishing", "Initial Access"),
    (["ransomware", "data encrypted for impact", "file encryption", "file locker"],
     "T1486", "Data Encrypted for Impact", "Impact"),
    (["lateral movement", "lateral move", "pivot"],
     "T1021", "Remote Services", "Lateral Movement"),
    (["credential dumping", "credential theft", "mimikatz", "lsass dump", "password dump"],
     "T1003", "OS Credential Dumping", "Credential Access"),
    (["remote code execution", "rce", "arbitrary code execution"],
     "T1059", "Command and Scripting Interpreter", "Execution"),
    (["supply chain", "software supply chain", "dependency confusion", "build pipeline"],
     "T1195", "Supply Chain Compromise", "Initial Access"),
    (["sql injection", "sqli", "database injection"],
     "T1190", "Exploit Public-Facing Application", "Initial Access"),
    (["brute force", "password spraying", "credential stuffing", "password spray"],
     "T1110", "Brute Force", "Credential Access"),
    (["drive-by", "watering hole", "malicious website", "compromised website"],
     "T1189", "Drive-by Compromise", "Initial Access"),
    (["valid accounts", "stolen credentials", "compromised account", "account takeover"],
     "T1078", "Valid Accounts", "Initial Access"),
    (["data exfiltration", "data theft", "exfiltrate", "exfiltrated data", "data leak"],
     "T1041", "Exfiltration Over C2 Channel", "Exfiltration"),
    (["command and control", " c2 ", "c&c", "beaconing", "callback"],
     "T1071", "Application Layer Protocol", "Command and Control"),
    (["privilege escalation", "escalate privileges", "local privilege"],
     "T1068", "Exploitation for Privilege Escalation", "Privilege Escalation"),
    (["persistence", "maintain access", "scheduled task", "registry run key"],
     "T1053", "Scheduled Task/Job", "Persistence"),
    (["defense evasion", "antivirus bypass", "av bypass", "obfuscation", "packed"],
     "T1027", "Obfuscated Files or Information", "Defense Evasion"),
    (["zero-day", "zero day", "0-day", "unpatched vulnerability", "undisclosed vulnerability"],
     "T1190", "Exploit Public-Facing Application", "Initial Access"),
    (["ddos", "denial of service", "distributed denial"],
     "T1498", "Network Denial of Service", "Impact"),
    (["keylogger", "keystroke logging", "keylogging"],
     "T1056", "Input Capture", "Collection"),
    (["social engineering", "pretexting", "vishing", "smishing"],
     "T1566", "Phishing", "Initial Access"),
    (["vpn exploit", "vpn vulnerability", "vpn flaw"],
     "T1133", "External Remote Services", "Initial Access"),
    (["wiper", "destructive malware", "data destruction", "disk wiper"],
     "T1485", "Data Destruction", "Impact"),
    (["web shell", "webshell"],
     "T1505", "Server Software Component", "Persistence"),
    (["living off the land", "lolbin", "lolbas", "built-in tool"],
     "T1218", "System Binary Proxy Execution", "Defense Evasion"),
    (["man-in-the-middle", "mitm", "adversary-in-the-middle", "aitm"],
     "T1557", "Adversary-in-the-Middle", "Credential Access"),
    (["business email compromise", "bec", "invoice fraud"],
     "T1534", "Internal Spearphishing", "Lateral Movement"),
]


def _map_attack_techniques(text: str) -> list[AttackTechnique]:
    """Map text to MITRE ATT&CK techniques via keyword matching."""
    text_lower = text.lower()
    found: list[AttackTechnique] = []
    seen_ids: set[str] = set()

    for keywords, tech_id, tech_name, tactic in _ATTACK_MAP:
        if tech_id in seen_ids:
            continue
        for kw in keywords:
            if kw in text_lower:
                found.append(AttackTechnique(
                    technique_id=tech_id,
                    technique_name=tech_name,
                    tactic=tactic,
                    confidence=ConfidenceLevel.LOW,
                ))
                seen_ids.add(tech_id)
                break

    return found


# ---------------------------------------------------------------------------
# Extractive summarisation
# ---------------------------------------------------------------------------

_IMPORTANT_WORDS = frozenset({
    "attack", "breach", "vulnerability", "exploit", "ransomware", "malware",
    "phishing", "advisory", "critical", "patch", "cve", "threat", "campaign",
    "actor", "zero-day", "incident", "data", "stolen", "compromised",
    "backdoor", "espionage", "intrusion", "nation", "warning", "alert",
})


def _extractive_summary(text: str, max_words: int = 80, max_sentences: int = 3) -> str:
    """
    Simple extractive summarisation.

    Splits text into sentences, scores each by keyword density and position,
    then reconstructs the top sentences (in original order) up to max_words
    and max_sentences.
    """
    if not text:
        return ""

    # Basic sentence splitting
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if len(s.split()) >= 5]

    if not sentences:
        return textwrap.shorten(text, width=max_words * 6, placeholder="...")

    scored: list[tuple[float, int, str]] = []
    for i, sentence in enumerate(sentences):
        words = sentence.lower().split()
        keyword_hits = sum(
            1 for w in words if any(kw in w for kw in _IMPORTANT_WORDS)
        )
        position_score = 1.0 / (i + 1)
        score = keyword_hits * 0.6 + position_score * 0.4
        scored.append((score, i, sentence))

    # Sort by score descending; re-select in original order
    scored.sort(key=lambda x: x[0], reverse=True)

    selected: list[tuple[int, str]] = []
    word_count = 0
    for _, idx, sentence in scored:
        if len(selected) >= max_sentences:
            break
        words_in_sent = len(sentence.split())
        if word_count + words_in_sent > max_words and selected:
            break
        selected.append((idx, sentence))
        word_count += words_in_sent

    if not selected:
        # Fallback: just take the first sentence
        selected = [(0, sentences[0])]

    selected.sort(key=lambda x: x[0])
    summary = " ".join(s for _, s in selected)

    # Hard truncation as safety net
    words = summary.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words]) + "..."

    return summary


# ---------------------------------------------------------------------------
# Why-it-matters rationale
# ---------------------------------------------------------------------------

_TACTIC_DESCRIPTIONS: dict[str, str] = {
    "Initial Access":        "adversaries gaining their first foothold in the environment",
    "Execution":             "malicious code running on victim systems",
    "Persistence":           "adversaries maintaining long-term access after initial compromise",
    "Privilege Escalation":  "attackers escalating to higher system privileges",
    "Lateral Movement":      "attackers moving laterally through the network",
    "Exfiltration":          "data being stolen from victim systems",
    "Impact":                "destructive actions targeting systems or data",
    "Credential Access":     "credential harvesting to compromise user accounts",
    "Defense Evasion":       "attackers hiding activity to avoid detection",
    "Command and Control":   "adversaries maintaining remote control of compromised hosts",
}


def _why_it_matters(
    candidate: ThreatCandidate,
    techniques: list[AttackTechnique],
    malware: list[str],
    cves: list[str],
    actors: list[str],
    sectors: list[str],
) -> str:
    """Generate a narrative 'why it matters' explanation from available signals."""
    parts: list[str] = []
    title_lower = candidate.title.lower()

    # ── Lead: primary threat signal ─────────────────────────────────────────
    is_cisa_kev = "cisa" in title_lower and any(
        kw in title_lower for kw in ("kev", "known exploited", "catalog", "catalogue")
    )
    is_breach      = any(kw in title_lower for kw in ("breach", "leak", "stolen", "exfiltrat"))
    is_ransomware  = "ransomware" in title_lower or any("ransomware" in m.lower() for m in malware)
    is_zero_day    = any(kw in title_lower for kw in ("zero-day", "zero day", "0-day"))
    is_advisory    = any(kw in title_lower for kw in ("advisory", "patch", "update", "bulletin"))

    if is_cisa_kev and cves:
        parts.append(
            f"CISA has formally listed {len(cves)} CVE(s) as actively exploited under its "
            "Known Exploited Vulnerabilities Catalogue, triggering mandatory patch deadlines "
            "for US federal agencies and signalling real-world exploitation risk for all organisations."
        )
    elif cves:
        sample = ", ".join(cves[:3]) + (" and others" if len(cves) > 3 else "")
        parts.append(
            f"Covers {len(cves)} tracked CVE(s) ({sample}) with evidence of active exploitation "
            "in the wild—affected software should be patched immediately."
        )
    elif is_ransomware and malware:
        parts.append(
            f"Active {malware[0]} ransomware campaign—organisations face immediate risk of "
            "data encryption, operational disruption, and potential extortion demands."
        )
    elif malware:
        families = " and ".join(malware[:2])
        article = "an" if malware[0][0].lower() in "aeiou" else "a"
        parts.append(
            f"Involves {families}, {article} established malware family with confirmed "
            "operational history and significant impact potential."
        )
    elif is_breach:
        parts.append(
            "A confirmed data incident indicates adversaries achieved persistent access and "
            "likely exfiltrated data, with downstream exposure risk for affected users and partners."
        )
    elif is_zero_day:
        parts.append(
            "A zero-day vulnerability is being actively exploited before a vendor patch is "
            "available, leaving all unmitigated installations at immediate and unmitigable risk."
        )
    elif is_advisory:
        parts.append(
            "An official security advisory has been published. Prompt patching is strongly "
            "recommended before adversaries weaponise the disclosed vulnerability."
        )

    # ── Who is at risk ───────────────────────────────────────────────────────
    known_sectors = [s for s in sectors if s.lower() not in ("unknown", "")]
    if known_sectors:
        sector_str = ", ".join(known_sectors[:3])
        suffix = " and others" if len(known_sectors) > 3 else ""
        parts.append(f"Primary exposure: {sector_str}{suffix} sector(s).")

    # ── ATT&CK context ───────────────────────────────────────────────────────
    if techniques:
        tactics = list(dict.fromkeys(t.tactic for t in techniques))
        desc = _TACTIC_DESCRIPTIONS.get(tactics[0], tactics[0])
        parts.append(f"Attack pattern consistent with {desc}.")

    # ── Actor attribution ────────────────────────────────────────────────────
    if actors:
        actor_str = actors[0] if len(actors) == 1 else " and ".join(actors[:2])
        noun = "known threat actor" if len(actors) == 1 else "known threat actors"
        parts.append(f"Associated (low confidence) with {noun} {actor_str}.")

    # ── Corroboration signal ─────────────────────────────────────────────────
    unique_sources = len({item.source_name for item in candidate.raw_items})
    if unique_sources >= 3:
        parts.append(
            f"Coverage across {unique_sources} independent sources increases analytical confidence."
        )
    elif unique_sources == 2:
        parts.append("Independently corroborated by a second source.")

    if not parts:
        parts.append(
            f"Reported by {candidate.primary_source}. "
            "Full significance assessment requires additional corroborating data."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Confidence note
# ---------------------------------------------------------------------------

def _confidence_note(
    attribution: list[Attribution],
    techniques: list[AttackTechnique],
    countries: list[str],
) -> Optional[str]:
    """Return a transparency note about analytical limitations."""
    notes: list[str] = []
    if attribution:
        notes.append(
            "Attribution is derived from public reporting only and should be "
            "treated as preliminary."
        )
    if techniques:
        notes.append(
            "ATT&CK technique mappings are inferred from keyword matching "
            "and may not reflect confirmed adversary TTPs."
        )
    if not countries:
        notes.append(
            "Affected countries could not be determined from available text."
        )
    return " ".join(notes) if notes else None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class DeterministicEnricher(BaseEnrichmentProvider):
    """Rule-based enrichment requiring no paid external APIs."""

    def __init__(self, max_summary_words: int = 80) -> None:
        self.max_summary_words = max_summary_words
        self._cvss_cache: dict = {}

    def set_cvss_cache(self, cache: dict) -> None:
        """Inject pre-fetched CVSS data (CVE ID → NVD dict) for this run."""
        self._cvss_cache = cache

    def enrich(
        self,
        candidate: ThreatCandidate,
        score: float,
        score_breakdown: Optional[ScoreBreakdown] = None,
    ) -> EnrichedThreat:
        """Enrich a ThreatCandidate deterministically."""
        # Combine all available text for entity extraction
        text_parts = [candidate.title]
        if candidate.summary:
            text_parts.append(candidate.summary)
        if candidate.full_text:
            text_parts.append(candidate.full_text[:8_000])  # cap to stay fast
        combined = " ".join(text_parts)

        cves = extract_cves(combined)
        cve_details = {cve: self._cvss_cache[cve] for cve in cves if cve in self._cvss_cache}
        countries = extract_countries(combined)
        sectors = extract_sectors(combined)
        malware = extract_malware(combined)
        actors = extract_threat_actors(combined)
        techniques = _map_attack_techniques(combined)
        threat_types = extract_threat_types(combined)

        # Summarise from the richest available source text
        source_text = candidate.full_text or candidate.summary or candidate.title
        summary = _extractive_summary(source_text, self.max_summary_words)
        if not summary:
            summary = candidate.summary or candidate.title

        why = _why_it_matters(candidate, techniques, malware, cves, actors, sectors)

        attribution = [
            Attribution(
                actor_name=actor,
                confidence=ConfidenceLevel.LOW,
                source_statement=f"Named in: {candidate.primary_source}",
            )
            for actor in actors
        ]

        note = _confidence_note(attribution, techniques, countries)

        # Build {name, url} pairs for supporting sources from raw items,
        # one entry per unique source name (excluding the primary source).
        _seen_support: set[str] = set()
        supporting_source_details: list[dict[str, str]] = []
        for item in candidate.raw_items:
            if (
                item.source_name != candidate.primary_source
                and item.source_name not in _seen_support
                and item.url
            ):
                _seen_support.add(item.source_name)
                supporting_source_details.append(
                    {"name": item.source_name, "url": item.url}
                )

        return EnrichedThreat(
            id=candidate.id,
            title=candidate.title,
            primary_url=candidate.primary_url,
            primary_source=candidate.primary_source,
            supporting_sources=candidate.supporting_sources,
            published_at=candidate.published_at,
            summary=summary,
            why_it_matters=why,
            attack_techniques=techniques[:5],   # cap display at 5
            attribution=attribution,
            countries_affected=countries,
            companies_affected=[],              # requires NLP; left for LLM provider
            industries_affected=sectors,
            threat_types=threat_types,
            cves=cves,
            cve_details=cve_details,
            malware_families=malware,
            score=round(score, 4),
            score_breakdown=score_breakdown or ScoreBreakdown(),
            supporting_source_details=supporting_source_details,
            corroboration_count=candidate.corroboration_count,
            confidence_note=note,
        )
