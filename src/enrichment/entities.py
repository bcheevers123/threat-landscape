"""
Entity extraction utilities for deterministic enrichment.

All extraction is rule-based (regex + keyword lists) so no paid APIs or
large NLP models are required.  This runs comfortably on a Raspberry Pi.
"""
from __future__ import annotations

import re
from datetime import datetime

# ---------------------------------------------------------------------------
# CVE extraction
# ---------------------------------------------------------------------------

# Capture year and ID separately so we can validate the year range.
_CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.IGNORECASE)
_CVE_YEAR_MIN = 1999
_CVE_YEAR_MAX = datetime.now().year + 1  # Allow one year ahead for pre-disclosure


def extract_cves(text: str) -> list[str]:
    """Return a deduplicated list of CVE IDs found in text."""
    seen: set[str] = set()
    result: list[str] = []
    for year_str, seq_str in _CVE_RE.findall(text):
        year = int(year_str)
        if not (_CVE_YEAR_MIN <= year <= _CVE_YEAR_MAX):
            continue
        upper = f"CVE-{year_str}-{seq_str}".upper()
        if upper not in seen:
            seen.add(upper)
            result.append(upper)
    return result


# ---------------------------------------------------------------------------
# Country extraction
# ---------------------------------------------------------------------------

# Ordered by length (longest first) to prefer "United Kingdom" over "UK"
_COUNTRIES: list[tuple[str, str]] = [
    # (display_name, canonical_name)
    ("United States of America", "United States"),
    ("United States", "United States"),
    ("United Kingdom", "United Kingdom"),
    ("North Korea", "North Korea"),
    ("South Korea", "South Korea"),
    ("Saudi Arabia", "Saudi Arabia"),
    ("European Union", "European Union"),
    ("New Zealand", "New Zealand"),
    ("Netherlands", "Netherlands"),
    ("Czech Republic", "Czech Republic"),
    ("Australia", "Australia"),
    ("Singapore", "Singapore"),
    ("Indonesia", "Indonesia"),
    ("Philippines", "Philippines"),
    ("Thailand", "Thailand"),
    ("Malaysia", "Malaysia"),
    ("Pakistan", "Pakistan"),
    ("Vietnam", "Vietnam"),
    ("Germany", "Germany"),
    ("Ukraine", "Ukraine"),
    ("Belgium", "Belgium"),
    ("Romania", "Romania"),
    ("Hungary", "Hungary"),
    ("Bulgaria", "Bulgaria"),
    ("Slovakia", "Slovakia"),
    ("Sweden", "Sweden"),
    ("Finland", "Finland"),
    ("Denmark", "Denmark"),
    ("Norway", "Norway"),
    ("Israel", "Israel"),
    ("Turkey", "Turkey"),
    ("Brazil", "Brazil"),
    ("Mexico", "Mexico"),
    ("Canada", "Canada"),
    ("France", "France"),
    ("Russia", "Russia"),
    ("China", "China"),
    ("India", "India"),
    ("Japan", "Japan"),
    ("Taiwan", "Taiwan"),
    ("Spain", "Spain"),
    ("Italy", "Italy"),
    ("Poland", "Poland"),
    ("Iran", "Iran"),
    ("NATO", "NATO"),
    ("USA", "United States"),
    ("UK", "United Kingdom"),
    ("EU", "European Union"),
    ("US", "United States"),
]

# Build compiled patterns (longest first to avoid partial matches)
_COUNTRY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(display) + r"\b", re.IGNORECASE), canonical)
    for display, canonical in _COUNTRIES
]


def extract_countries(text: str) -> list[str]:
    """Return a deduplicated list of affected country names found in text."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern, canonical in _COUNTRY_PATTERNS:
        if pattern.search(text) and canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


# ---------------------------------------------------------------------------
# Sector extraction
# ---------------------------------------------------------------------------

_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Healthcare": [
        "hospital", "healthcare", "health care", "medical", "nhs",
        "clinic", "pharmaceutical", "pharma", "health service", "patient",
    ],
    "Finance": [
        "bank", "banking", "financial institution", "finance", "fintech",
        "payment", "credit union", "investment", "stock exchange",
        "cryptocurrency", "crypto", "wallet", "trading",
    ],
    "Insurance": [
        "insurance", "insurer", "underwriter",
    ],
    "Energy": [
        "energy", "power grid", "electricity", "oil and gas", "nuclear",
        "pipeline", "utility", "utilities", "renewable", "wind farm",
    ],
    "Government": [
        "government agency", "ministry", "department of", "federal",
        "municipal", "parliament", "senate", "congress", "nato",
        "defence", "defense", "military", "armed forces", "intelligence agency",
        "law enforcement", "police",
    ],
    "Technology": [
        "technology company", "tech company", "software company", "cloud provider",
        "saas", "platform provider", "microsoft", "google", "amazon aws",
        "azure", "developer", "api provider",
    ],
    "Education": [
        "university", "college", "school district", "education", "academic",
        "research institution", "student data",
    ],
    "Retail": [
        "retailer", "e-commerce", "ecommerce", "online shop",
        "supermarket", "shopping",
    ],
    "Transport": [
        "airline", "airport", "railway", "transport", "logistics",
        "shipping company", "port authority", "maritime",
    ],
    "Telecommunications": [
        "telecom", "telecommunications", "mobile network",
        "internet service provider", "isp", "broadband",
    ],
    "Critical Infrastructure": [
        "critical infrastructure", "scada", "ics system",
        "operational technology", "ot network", "industrial control",
    ],
    "Manufacturing": [
        "manufacturing", "industrial", "factory", "production line",
    ],
    "Legal": [
        "law firm", "legal sector", "judiciary",
    ],
    "Media": [
        "media organisation", "news outlet", "broadcaster", "press",
    ],
}


def extract_sectors(text: str) -> list[str]:
    """Return a list of affected sectors inferred from text keywords."""
    text_lower = text.lower()
    found: list[str] = []
    for sector, keywords in _SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(sector)
                break
    return found


# ---------------------------------------------------------------------------
# Threat actor extraction
# ---------------------------------------------------------------------------

_THREAT_ACTORS: list[str] = [
    "APT28", "APT29", "APT32", "APT33", "APT40", "APT41",
    "Fancy Bear", "Cozy Bear", "Lazarus Group", "Kimsuky",
    "Sandworm", "Turla", "Charming Kitten", "TA505",
    "REvil", "LockBit", "BlackCat", "ALPHV", "Clop", "Hive",
    "Vice Society", "Scattered Spider", "Star Blizzard",
    "Volt Typhoon", "Salt Typhoon", "Midnight Blizzard",
    "Forest Blizzard", "Mustang Panda", "Transparent Tribe",
    "FIN7", "FIN8", "Cobalt Group", "Evil Corp",
    "UNC2452", "UNC4841", "HAFNIUM", "Lapsus$", "DEV-0537",
    "TA416", "BlackBasta", "MedusaLocker", "Play", "Royal",
]

_ACTOR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(actor) + r"\b", re.IGNORECASE), actor)
    for actor in _THREAT_ACTORS
]


def extract_threat_actors(text: str) -> list[str]:
    """Return a list of known threat actor names found in text."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern, actor in _ACTOR_PATTERNS:
        if pattern.search(text) and actor not in seen:
            seen.add(actor)
            found.append(actor)
    return found


# ---------------------------------------------------------------------------
# Threat type classification
# ---------------------------------------------------------------------------

# Ordered by priority — first match wins for the primary type, but all
# matching types are returned so the UI can display and filter on them.
_THREAT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("Ransomware", [
        "ransomware", "file encryptor", "file locker", "ransom demand",
        "decryptor", "double extortion", "data encrypted for impact",
    ]),
    ("Wiper", [
        "wiper", "wiperware", "disk wiper", "destructive malware",
        "data destruction", "data erasure",
    ]),
    ("BEC", [
        "business email compromise", "bec", "invoice fraud",
        "ceo fraud", "wire transfer fraud",
    ]),
    ("Supply Chain", [
        "supply chain", "dependency confusion", "build pipeline",
        "software supply chain", "third-party compromise", "package manager",
        "malicious package", "poisoned package",
    ]),
    ("Phishing", [
        "phishing", "spear phishing", "spearphishing", "spear-phishing",
        "credential harvesting", "smishing", "vishing",
    ]),
    ("Social Engineering", [
        "social engineering", "pretexting", "whaling", "quishing",
        "qr code phishing", "voice phishing", "impersonation attack",
        "vishing", "pretext call",
    ]),
    ("DDoS", [
        "ddos", "denial of service", "distributed denial",
        "volumetric attack",
    ]),
    ("Zero-Day", [
        "zero-day", "zero day", "0-day",
        "undisclosed vulnerability", "unpatched flaw",
    ]),
    ("Exploitation", [
        "exploited in the wild", "active exploitation", "exploit kit",
        "exploit chain", "in-the-wild", "weaponised exploit",
        "weaponized exploit", "actively exploited",
    ]),
    ("APT", [
        "advanced persistent threat", "nation-state", "state-sponsored",
        "cyber espionage", "espionage", "intelligence gathering",
    ]),
    ("Insider Threat", [
        "insider threat", "malicious insider", "rogue employee",
        "insider attack", "negligent employee", "privileged user abuse",
        "employee data theft",
    ]),
    ("Credential Theft", [
        "credential theft", "credential dumping", "credential stuffing",
        "password spray", "password spraying", "brute force",
        "account takeover", "stolen credentials",
    ]),
    ("MFA Bypass", [
        "mfa bypass", "mfa fatigue", "push bombing", "sim swap",
        "ss7 attack", "authentication bypass", "2fa bypass",
        "otp bypass", "session hijacking", "adversary-in-the-middle",
    ]),
    ("Cryptojacking", [
        "cryptojacking", "cryptominer", "crypto miner",
        "coin miner", "unauthorized mining",
    ]),
    ("Data Breach", [
        "data breach", "data leak", "data exposure",
        "records exposed", "database leak", "stolen data",
    ]),
    ("Cloud Attack", [
        "cloud misconfiguration", "cloud account takeover",
        "container escape", "cloud breach", "s3 bucket exposed",
        "bucket misconfiguration", "cloud storage exposed",
        "cloud workload", "aws compromise", "azure compromise",
        "gcp compromise", "cloud intrusion",
    ]),
    ("OT/ICS", [
        "ot attack", "ics attack", "operational technology",
        "scada attack", "industrial control system", "plc compromise",
        "ot/ics", "ot network", "ics network", "industrial network",
        "industrial cyber", "critical control system",
    ]),
    ("Web Shell", [
        "web shell", "webshell",
    ]),
    ("Infostealer", [
        "infostealer", "info stealer", "stealer malware",
        "lumma", "raccoon stealer", "redline stealer",
        "vidar", "formbook", "agentTesla", "data exfiltration malware",
    ]),
    ("Botnet", [
        "botnet", "bot herder", "zombie network", "command-and-control network",
        "c2 network", "infected devices", "bot network", "mirai",
        "botmaster",
    ]),
    ("Watering Hole", [
        "watering hole", "drive-by download", "strategic web compromise",
        "drive-by attack", "compromised website attack",
    ]),
    ("Typosquatting", [
        "typosquatting", "lookalike domain", "homograph attack",
        "typosquat", "domain squatting", "malicious npm",
        "malicious pypi", "package hijacking",
    ]),
    ("Malvertising", [
        "malvertising", "malicious advertisement", "malicious ad",
        "seo poisoning", "malicious search result",
    ]),
    ("Disinformation", [
        "disinformation", "information warfare", "influence operation",
        "coordinated inauthentic", "propaganda campaign",
        "influence campaign", "cognitive warfare",
    ]),
    ("Malware", [
        "malware", "trojan", "remote access trojan",
        "rootkit", "spyware", "dropper", "loader", "backdoor",
    ]),
    ("Vulnerability", [
        "vulnerability", "security flaw", "security bug",
        "remote code execution", "rce", "buffer overflow",
        "privilege escalation", "patch tuesday", "security advisory",
    ]),
]


def extract_threat_types(text: str) -> list[str]:
    """
    Return an ordered list of threat type labels inferred from text.

    The first entry is the primary (highest-priority) type.
    Returns ["Other"] if nothing matches.
    """
    text_lower = text.lower()
    found: list[str] = []
    for label, keywords in _THREAT_TYPE_RULES:
        for kw in keywords:
            if kw in text_lower:
                found.append(label)
                break
    return found if found else ["Other"]


# ---------------------------------------------------------------------------
# Malware family extraction
# ---------------------------------------------------------------------------

_MALWARE_FAMILIES: list[str] = [
    "WannaCry", "NotPetya", "Petya", "Ryuk", "Conti", "LockBit",
    "BlackCat", "ALPHV", "REvil", "Sodinokibi", "Maze", "DoppelPaymer",
    "Emotet", "TrickBot", "Qakbot", "QBot", "Dridex", "Cobalt Strike",
    "Mimikatz", "BlackMatter", "Hive", "Clop", "AvosLocker", "Cuba",
    "BlackBasta", "MedusaLocker", "Play", "Royal", "Medusa",
    "ESXiArgs", "GootLoader", "SystemBC", "IcedID", "Bumblebee",
    "AsyncRAT", "NjRAT", "RemcosRAT", "Remcos", "AgentTesla",
    "FormBook", "RedLine Stealer", "Vidar", "Raccoon Stealer",
    "CaddyWiper", "HermeticWiper", "WhisperGate", "INDUSTROYER2",
    "Industroyer", "TRITON", "Stuxnet", "EternalBlue",
]

_MALWARE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE), name)
    for name in _MALWARE_FAMILIES
]


def extract_malware(text: str) -> list[str]:
    """Return a list of known malware family names found in text."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern, name in _MALWARE_PATTERNS:
        if pattern.search(text) and name not in seen:
            seen.add(name)
            found.append(name)
    return found
