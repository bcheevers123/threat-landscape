"""
NVD CVE severity lookup.

Fetches CVSS v3.x base scores from the NVD CVE 2.0 API.
Rate limit without an API key: 5 requests per rolling 30 seconds.
For up to ~20 CVEs per daily run, a short inter-request pause is sufficient.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_TIMEOUT = 10        # seconds per request
_PAUSE   = 0.7       # seconds between requests — stays within rate limit


def _parse_cvss(data: dict) -> dict[str, Any] | None:
    """Extract CVSS score data from one NVD API response object."""
    try:
        vuln    = data["vulnerabilities"][0]["cve"]
        metrics = vuln.get("metrics", {})
        # Prefer v3.1 > v3.0 > v2.0
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if key not in metrics:
                continue
            entry     = metrics[key][0]
            cvss_data = entry.get("cvssData", {})
            score     = cvss_data.get("baseScore")
            severity  = (
                entry.get("baseSeverity") or cvss_data.get("baseSeverity") or ""
            ).upper()
            if score is not None:
                return {
                    "score":    float(score),
                    "severity": severity,
                    "vector":   cvss_data.get("vectorString", ""),
                    "version":  cvss_data.get("version", key[-2:]),
                }
    except (KeyError, IndexError, TypeError):
        pass
    return None


def fetch_cvss_scores(cves: list[str]) -> dict[str, dict[str, Any]]:
    """
    Look up CVSS scores for a list of CVE IDs from the NVD API.

    Returns a dict mapping CVE ID → {"score": float, "severity": str, ...}.
    CVEs that cannot be fetched (network error, 404, etc.) are silently omitted.
    Never raises; all errors are caught and logged at DEBUG level.
    """
    if not cves:
        return {}

    results: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=_TIMEOUT) as client:
        for i, cve_id in enumerate(cves):
            if i > 0:
                time.sleep(_PAUSE)
            try:
                resp = client.get(_NVD_API, params={"cveId": cve_id})
                if resp.status_code != 200:
                    logger.debug("NVD returned %d for %s", resp.status_code, cve_id)
                    continue
                parsed = _parse_cvss(resp.json())
                if parsed:
                    results[cve_id] = parsed
                    logger.debug(
                        "NVD: %s → CVSS %.1f (%s)",
                        cve_id, parsed["score"], parsed["severity"],
                    )
            except Exception as exc:
                logger.debug("NVD lookup failed for %s: %s", cve_id, exc)

    return results
