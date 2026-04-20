"""
Threat Landscape Pipeline — CLI entry point.

Usage:
  python -m src.main collect        # collect raw items and save raw_items.json
  python -m src.main build          # run full pipeline (collect -> render)
  python -m src.main deploy         # upload output/ to remote host via SFTP
  python -m src.main run-all        # build + deploy
  python -m src.main preview        # serve output/ locally on HTTP

Configuration is loaded from config/config.yaml and config/sources.yaml by
default.  Override with --config / --sources flags.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _get_config(path: Optional[str]) -> dict[str, Any]:
    p = Path(path) if path else _PROJECT_ROOT / "config" / "config.yaml"
    return _load_yaml(p)


def _get_sources(path: Optional[str]) -> list[dict[str, Any]]:
    p = Path(path) if path else _PROJECT_ROOT / "config" / "sources.yaml"
    data = _load_yaml(p)
    return data.get("sources", [])


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--config", default=None, metavar="PATH", help="Path to config.yaml")
@click.option("--sources", default=None, metavar="PATH", help="Path to sources.yaml")
@click.option("--verbose", is_flag=True, help="Enable DEBUG logging")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[str],
    sources: Optional[str],
    verbose: bool,
) -> None:
    """Threat Landscape Pipeline CLI."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    ctx.ensure_object(dict)
    ctx.obj["config"] = _get_config(config)
    ctx.obj["sources"] = _get_sources(sources)


# ---------------------------------------------------------------------------
# collect command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def collect(ctx: click.Context) -> None:
    """Collect raw items from all enabled sources and save to output/raw_items.json."""
    from src.collectors.manager import CollectorManager
    from src.models.schemas import SourceConfig

    cfg = ctx.obj["config"]
    sources = [SourceConfig(**s) for s in ctx.obj["sources"]]

    manager = CollectorManager(
        sources=sources,
        max_items_per_source=cfg.get("max_items_per_source", 50),
    )
    items = manager.collect_all()

    out_dir = Path(cfg.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_items.json"
    raw_path.write_text(
        json.dumps(
            [i.model_dump(mode="json") for i in items], indent=2, default=str
        ),
        encoding="utf-8",
    )
    click.echo(f"Collected {len(items)} items -> {raw_path}")


# ---------------------------------------------------------------------------
# build command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def build(ctx: click.Context) -> None:
    """Run the full pipeline: collect -> normalise -> dedupe -> score -> enrich -> render."""
    _run_pipeline(ctx.obj["config"], ctx.obj["sources"])


# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def deploy(ctx: click.Context) -> None:
    """Deploy generated assets to GitHub Pages (or SFTP if configured)."""
    cfg = ctx.obj["config"]
    output_dir = Path(cfg.get("output_dir", "output"))
    target = cfg.get("deploy_target", "github_pages")

    if target == "github_pages":
        _deploy_github_pages(cfg, output_dir)
    else:
        _deploy_sftp(cfg, output_dir)

    click.echo("Deployment complete.")


def _deploy_github_pages(cfg: dict, output_dir: Path) -> None:
    from src.deploy.github_pages import GitHubPagesDeployer

    gpcfg = cfg.get("github_pages", {})

    # Support optional GITHUB_TOKEN in .env for HTTPS authentication.
    # If present, embed it in the repo URL so git push authenticates without
    # prompting for a password.
    repo_url: str = gpcfg.get("repo_url", "").strip()
    if not repo_url:
        click.echo(
            "Error: github_pages.repo_url is not set in config.yaml.",
            err=True,
        )
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and repo_url.startswith("https://github.com/"):
        # Insert token into URL: https://x-access-token:<token>@github.com/...
        repo_url = repo_url.replace("https://", f"https://x-access-token:{token}@", 1)

    staging_dir = str(
        _PROJECT_ROOT / gpcfg.get("staging_dir", "gh-pages-staging")
    )

    deployer = GitHubPagesDeployer(
        repo_url=repo_url,
        branch=gpcfg.get("branch", "gh-pages"),
        staging_dir=staging_dir,
        commit_name=gpcfg.get("commit_name", "Threat Landscape Bot"),
        commit_email=gpcfg.get("commit_email", "threatlandscape@localhost"),
        custom_domain=gpcfg.get("custom_domain") or None,
    )
    deployer.deploy(output_dir)


def _deploy_sftp(cfg: dict, output_dir: Path) -> None:
    from src.deploy.sftp import SFTPDeployer

    dcfg = cfg.get("deploy", {})
    host = dcfg.get("sftp_host") or os.environ.get("SFTP_HOST", "")
    if not host:
        click.echo(
            "Error: SFTP host not configured. "
            "Set deploy.sftp_host in config.yaml or the SFTP_HOST environment variable.",
            err=True,
        )
        sys.exit(1)

    deployer = SFTPDeployer(
        host=host,
        port=int(dcfg.get("sftp_port", 22)),
        username=dcfg.get("sftp_user") or os.environ.get("SFTP_USER", ""),
        key_path=dcfg.get("sftp_key_path") or os.environ.get("SFTP_KEY_PATH"),
        password=os.environ.get("SFTP_PASSWORD"),
        remote_base=dcfg.get(
            "remote_base_path",
            "/public_html/wp-content/uploads/barry-threat-landscape",
        ),
    )
    deployer.deploy(output_dir)


# ---------------------------------------------------------------------------
# run-all command
# ---------------------------------------------------------------------------

@cli.command("run-all")
@click.pass_context
def run_all(ctx: click.Context) -> None:
    """Run the full pipeline then deploy."""
    cfg = ctx.obj["config"]
    _run_pipeline(cfg, ctx.obj["sources"])
    ctx.invoke(deploy)


# ---------------------------------------------------------------------------
# preview command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--port", default=8080, show_default=True, help="Local HTTP port")
@click.pass_context
def preview(ctx: click.Context, port: int) -> None:
    """Serve the output directory locally for browser preview."""
    import functools
    import http.server

    cfg = ctx.obj["config"]
    out_dir = Path(cfg.get("output_dir", "output"))

    if not (out_dir / "index.html").exists():
        click.echo("No index.html found. Run 'build' first.", err=True)
        sys.exit(1)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(out_dir)
    )
    click.echo(f"Preview server running at http://localhost:{port}")
    click.echo("Press Ctrl+C to stop.")
    with http.server.HTTPServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nStopped.")


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mainstream-aware scorer
# Replaces cyber-specific severity/actionability dimensions with consumer-
# relevant signals: scale of impact on the public, and public interest/
# enforcement signals.  Breadth and recency remain unchanged.
# ---------------------------------------------------------------------------

_MS_CONSUMER_IMPACT_KWS: frozenset[str] = frozenset({
    "millions", "billion", "customers", "users", "subscribers",
    "personal data", "personal information", "private data",
    "identity theft", "financial loss", "bank account", "credit card",
    "social security", "national insurance", "date of birth",
    "breach", "data breach", "leak", "data leak", "exposed", "compromised",
    "stolen", "ransomware", "cyber attack", "hacked",
    "scam", "fraud", "phishing",
    "nhs", "hospital", "government", "council", "police",
    "bank", "retailer", "insurer",
    "widespread", "nationwide", "national",
})

_MS_PUBLIC_INTEREST_KWS: frozenset[str] = frozenset({
    "warning", "urged", "advised", "consumer warning", "public warning",
    "alert", "watchdog", "regulator", "fine", "penalty", "lawsuit",
    "major", "significant", "serious", "large-scale",
    "arrested", "charged", "convicted", "sentenced",
    "fined", "ico", "ftc", "gdpr", "investigation", "probe",
    "class action", "settlement",
})


def _score_consumer_impact(candidate) -> float:
    """0–1 score: scale and severity of impact on everyday consumers."""
    text = " ".join(filter(None, [candidate.title, candidate.summary or ""])).lower()
    hits = sum(1 for kw in _MS_CONSUMER_IMPACT_KWS if kw in text)
    return min(1.0, hits / 4)


def _score_public_interest(candidate) -> float:
    """0–1 score: public interest signals — enforcement, warnings, media attention."""
    text = " ".join(filter(None, [candidate.title, candidate.summary or ""])).lower()
    hits = sum(1 for kw in _MS_PUBLIC_INTEREST_KWS if kw in text)
    return min(1.0, hits / 3)


class MainstreamScorer:
    """
    Scorer tailored for consumer-facing mainstream cyber stories.

    Replaces technical severity/actionability with:
      severity     → consumer_impact  (scale of effect on the public)
      actionability→ public_interest  (enforcement, warnings, media attention)
    Recency, credibility, corroboration, and breadth behave identically to
    the base Scorer.
    """

    def __init__(self, weights=None, diversity_cap: int = 0) -> None:
        from src.scoring.scorer import ScoringWeights
        self.weights = weights or ScoringWeights(
            recency=0.32,
            source_credibility=0.15,
            corroboration=0.25,
            severity=0.15,
            breadth=0.08,
            actionability=0.05,
        )
        self.diversity_cap = diversity_cap

    def score(self, candidate) -> tuple:
        from src.models.schemas import ScoreBreakdown
        from src.scoring.scorer import (
            _score_recency,
            _score_corroboration,
            _score_breadth,
        )
        w = self.weights
        dims = {
            "recency":            _score_recency(candidate.published_at) * w.recency,
            "source_credibility": candidate.max_source_credibility * w.source_credibility,
            "corroboration":      _score_corroboration(candidate.corroboration_count) * w.corroboration,
            "severity":           _score_consumer_impact(candidate) * w.severity,
            "breadth":            _score_breadth(candidate) * w.breadth,
            "actionability":      _score_public_interest(candidate) * w.actionability,
        }
        total = sum(dims.values())
        breakdown = ScoreBreakdown(
            recency=round(dims["recency"], 4),
            source_credibility=round(dims["source_credibility"], 4),
            corroboration=round(dims["corroboration"], 4),
            severity=round(dims["severity"], 4),
            breadth=round(dims["breadth"], 4),
            actionability=round(dims["actionability"], 4),
            total=round(total, 4),
        )
        return total, breakdown

    def score_and_rank(self, candidates, top_n=10):
        from urllib.parse import urlparse
        scored = [(c, *self.score(c)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        if self.diversity_cap > 0:
            from src.scoring.scorer import _source_domain
            selected, domain_counts = [], {}
            for item in scored:
                domain = _source_domain(item[0].primary_url or "")
                count = domain_counts.get(domain, 0)
                if count < self.diversity_cap:
                    selected.append(item)
                    domain_counts[domain] = count + 1
                    if len(selected) == top_n:
                        break
            return selected
        return scored[:top_n]


def _filter_by_age(
    items: list,
    lookback_hours: int,
) -> list:
    """Discard items published more than lookback_hours ago."""
    from datetime import datetime, timezone
    cutoff = datetime.now(tz=timezone.utc).timestamp() - lookback_hours * 3600
    kept = []
    for item in items:
        pub = item.published_at
        if pub is None:
            kept.append(item)
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub.timestamp() >= cutoff:
            kept.append(item)
    logger.info(
        "Age filter (%dh): %d/%d items retained.", lookback_hours, len(kept), len(items)
    )
    return kept


def _run_pipeline(cfg: dict[str, Any], source_dicts: list[dict[str, Any]]) -> None:
    """
    Execute the full collect -> normalise -> dedupe -> score -> enrich -> render
    pipeline.  Called by both ``build`` and ``run-all`` commands.
    """
    from src.collectors.manager import CollectorManager
    from src.dedupe.deduplicator import deduplicate
    from src.enrichment.deterministic import DeterministicEnricher
    from src.models.schemas import SourceConfig, SourceSummary, ThreatLandscapeOutput
    from src.normalisers.normaliser import normalise_items
    from src.render.renderer import Renderer
    from src.scoring.scorer import Scorer, ScoringWeights
    from src.stix.builder import build_stix_bundle

    sources = [SourceConfig(**s) for s in source_dicts]
    output_dir = Path(cfg.get("output_dir", "output"))
    template_dir = Path(cfg.get("template_dir", "templates"))
    static_dir = Path(cfg.get("static_dir", "static"))
    top_n: int = cfg.get("top_n", 10)

    generation_notes: list[str] = []

    # ── 1. Collect ──────────────────────────────────────────────────────
    manager = CollectorManager(
        sources=sources,
        max_items_per_source=cfg.get("max_items_per_source", 50),
    )
    raw_items = manager.collect_all()
    total_collected = len(raw_items)

    # Source health: count items returned per enabled source
    from collections import Counter
    counts = Counter(item.source_name for item in raw_items)
    source_health = {s.name: counts.get(s.name, 0) for s in sources if s.enabled}
    healthy = sum(1 for v in source_health.values() if v > 0)
    logger.info("Source health: %d/%d sources returned items.", healthy, len(source_health))

    if total_collected == 0:
        generation_notes.append(
            "No items were collected. Check source URLs and network connectivity."
        )

    # ── 2. Normalise ─────────────────────────────────────────────────────
    normalised = normalise_items(raw_items)

    # ── 2b. Age filter — drop items older than lookback_hours ────────────
    lookback_hours: int = cfg.get("lookback_hours", 168)
    normalised = _filter_by_age(normalised, lookback_hours)

    # ── 3. Deduplicate ───────────────────────────────────────────────────
    candidates = deduplicate(normalised)
    total_after_dedupe = len(candidates)

    # ── 4. Score ─────────────────────────────────────────────────────────
    # Filter candidates to those sourced from technical/both-stream sources
    # before running the technical scoring pass.  This prevents mainstream-only
    # outlets (Engadget, NYT Tech, etc.) from appearing in the expert view.
    technical_source_names = {
        s.name for s in sources if s.enabled and s.stream in ("technical", "both")
    }
    technical_candidates = [
        c for c in candidates
        if any(item.source_name in technical_source_names for item in c.raw_items)
    ]
    logger.info(
        "Technical candidates (from technical/both sources): %d", len(technical_candidates)
    )

    scoring_cfg = cfg.get("scoring", {})
    weight_kwargs = {
        k: float(v)
        for k, v in scoring_cfg.items()
        if isinstance(v, (int, float)) and k != "diversity_cap"
    }
    weights = ScoringWeights(**weight_kwargs) if weight_kwargs else ScoringWeights()
    diversity_cap = int(scoring_cfg.get("diversity_cap", 0))
    scorer = Scorer(weights=weights, diversity_cap=diversity_cap)
    scored = scorer.score_and_rank(technical_candidates, top_n=top_n)

    if len(scored) < top_n:
        generation_notes.append(
            f"Only {len(scored)} items met the quality threshold "
            f"(target: {top_n}). The page will display fewer entries."
        )

    # ── 4b. History: load past runs to compute prevalent_days ────────────
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    from datetime import date, timedelta
    today = date.today()
    historical: list[dict] = []
    for days_ago in range(1, 7):
        day_path = history_dir / f"{(today - timedelta(days=days_ago)).isoformat()}.json"
        if day_path.exists():
            try:
                historical.append(json.loads(day_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    def _prevalent_days(title: str, pool_key: str) -> int:
        from rapidfuzz import fuzz as _fuzz
        title_l = title.lower()
        days = 0
        for day_data in historical:
            prev_titles = day_data.get(pool_key, [])
            if any(_fuzz.WRatio(title_l, pt.lower()) >= 82 for pt in prev_titles):
                days += 1
            else:
                break
        return days

    # ── 5. Enrich ────────────────────────────────────────────────────────
    # Pre-fetch CVSS scores for all CVEs in the technical top-N (one NVD batch)
    from src.enrichment.entities import extract_cves as _extract_cves
    from src.enrichment.nvd import fetch_cvss_scores
    all_cves: list[str] = []
    for _cand, _, _ in scored:
        _txt = " ".join(filter(None, [_cand.title, _cand.summary or "", _cand.full_text or ""]))[:8000]
        all_cves.extend(_extract_cves(_txt))
    all_cves = list(dict.fromkeys(all_cves))[:25]  # cap to stay within NVD rate limit
    cvss_cache: dict = {}
    if all_cves:
        logger.info("Fetching CVSS scores for %d CVE(s) from NVD.", len(all_cves))
        cvss_cache = fetch_cvss_scores(all_cves)
        logger.info("NVD returned data for %d/%d CVE(s).", len(cvss_cache), len(all_cves))

    enrichment_cfg = cfg.get("enrichment", {})
    enricher = DeterministicEnricher(
        max_summary_words=int(enrichment_cfg.get("max_summary_words", 200))
    )
    enricher.set_cvss_cache(cvss_cache)

    threats = []
    for candidate, score, breakdown in scored:
        threat = enricher.enrich(candidate, score, breakdown)
        try:
            threat.stix_bundle = build_stix_bundle(threat)
            threat.stix_file = f"stix/{threat.id}.json"
        except Exception as exc:
            logger.warning("STIX build failed for '%s': %s", threat.title, exc)
        threats.append(threat)

    # ── 5b. Mainstream: separate score + enrich pass ──────────────────────
    # Candidates are filtered to those covered by mainstream/both-stream sources.
    # A separate weight profile emphasises recency and corroboration over
    # technical severity/credibility — surfacing big consumer news stories.
    mainstream_source_names = {
        s.name for s in sources if s.enabled and s.stream in ("mainstream", "both")
    }

    # Keywords matched against the **title only** to decide whether a candidate
    # is a genuine security/privacy story worth surfacing in the mainstream view.
    #
    # Title-only matching is intentional: general tech RSS feeds (Engadget,
    # TechCrunch, NYT Tech) publish gadget reviews and acquisition news whose
    # summaries incidentally mention "security" or "privacy".  Restricting to
    # the title prevents off-topic stories from passing through.
    #
    # Broad single words like "arrested", "warning", or "patch" are omitted
    # because they produce too many false positives even in titles (crime
    # stories, weather warnings, software update announcements).  More specific
    # multi-word phrases are included instead.
    _MAINSTREAM_SECURITY_KEYWORDS = {
        # Incidents and attacks
        "hack", "hacked", "hacking", "hacker", "hackers",
        "breach", "breached", "data breach", "data leak", "data theft",
        "stolen data", "leaked data", "personal data exposed", "customer data",
        "cyberattack", "cyber attack", "cyber incident", "cyber threat",
        "ransomware", "malware", "spyware", "adware", "trojan", "worm",
        "backdoor", "zero-day", "exploit", "exploited",
        "account takeover", "account compromise",
        # Tactics/crimes
        "phishing", "smishing", "vishing",
        "online scam", "phone scam", "cyber scam", "scam warning",
        "identity theft", "fraud alert", "cyber fraud",
        "extortion", "blackmail",
        # Privacy and surveillance
        "data privacy", "privacy breach", "surveillance", "wiretap", "spying",
        "personal data", "facial recognition", "location tracking",
        # Credentials and authentication
        "password leak", "password breach", "credential", "credentials",
        "two-factor", "2fa",
        # Infrastructure and national security
        "critical infrastructure", "power grid", "water supply",
        "national security", "espionage", "state-sponsored", "nation-state",
        "cyber espionage", "cyber warfare",
        # Actors and enforcement
        "cybercrime", "cybercriminal", "cybersecurity", "cyber security",
        "hacker arrested", "hacker charged", "hacker sentenced",
        "cybercriminal arrested", "cybercriminal charged",
        "indicted for hacking", "convicted of hacking",
        # Encryption and dark web
        "encryption", "dark web", "darkweb", "dark net", "darknet",
        # Institutions
        "nsa", "gchq", "cisa",
        # Disinformation
        "disinformation", "deepfake",
        # Specific security advisories (multi-word, avoids generic "warning")
        "security warning", "security alert", "security advisory",
        "cyber warning", "cyber alert",
        # Security flaws
        "security flaw", "security bug", "security vulnerability",
        "security patch", "security update",
    }

    def _is_mainstream_security_story(candidate) -> bool:
        # Match only on title — summaries are too noisy for general keywords.
        title = (candidate.title or "").lower()
        return any(kw in title for kw in _MAINSTREAM_SECURITY_KEYWORDS)

    mainstream_candidates = [
        c for c in candidates
        if any(item.source_name in mainstream_source_names for item in c.raw_items)
        and _is_mainstream_security_story(c)
    ]
    logger.info(
        "Mainstream candidates after security keyword filter: %d", len(mainstream_candidates)
    )

    mainstream_threats = []
    if mainstream_candidates:
        ms_scoring_cfg = cfg.get("scoring_mainstream", {})
        ms_weight_kwargs = {
            k: float(v)
            for k, v in ms_scoring_cfg.items()
            if isinstance(v, (int, float)) and k != "diversity_cap"
        }
        ms_diversity_cap = int(ms_scoring_cfg.get("diversity_cap", 2))
        # Use consumer-oriented MainstreamScorer; ScoringWeights from config if set
        if ms_weight_kwargs:
            ms_weights = ScoringWeights(**ms_weight_kwargs)
            ms_scorer = MainstreamScorer(weights=ms_weights, diversity_cap=ms_diversity_cap)
        else:
            ms_scorer = MainstreamScorer(diversity_cap=ms_diversity_cap)
        ms_scored = ms_scorer.score_and_rank(mainstream_candidates, top_n=top_n)
        logger.info(
            "Mainstream scoring: %d candidates -> top %d", len(mainstream_candidates), len(ms_scored)
        )

        for candidate, score, breakdown in ms_scored:
            threat = enricher.enrich(candidate, score, breakdown)
            try:
                threat.stix_bundle = build_stix_bundle(threat)
                threat.stix_file = f"stix/{threat.id}.json"
            except Exception as exc:
                logger.warning("STIX build failed (mainstream) for '%s': %s", threat.title, exc)
            mainstream_threats.append(threat)

    # ── 5c. Apply prevalent_days ─────────────────────────────────────────
    for t in threats:
        t.prevalent_days = _prevalent_days(t.title, "technical")
    for t in mainstream_threats:
        t.prevalent_days = _prevalent_days(t.title, "mainstream")

    landscape = ThreatLandscapeOutput(
        generated_at=datetime.now(tz=timezone.utc),
        threats=threats,
        mainstream_threats=mainstream_threats,
        total_items_collected=total_collected,
        total_items_after_dedupe=total_after_dedupe,
        generation_notes=generation_notes,
        sources_queried=[
            SourceSummary(name=s.name, credibility=s.credibility, tags=s.tags, rationale=s.rationale, stream=s.stream)
            for s in sources
            if s.enabled
        ],
        source_health=source_health,
    )

    # ── 6. Render ────────────────────────────────────────────────────────
    branding = cfg.get("branding", {})
    renderer = Renderer(
        template_dir=template_dir,
        output_dir=output_dir,
        static_dir=static_dir,
        branding=branding,
    )
    paths = renderer.render_all(landscape)

    # ── 7. Save history snapshot for prevalent-days tracking ─────────────
    history_snapshot = {
        "technical":  [t.title for t in threats],
        "mainstream": [t.title for t in mainstream_threats],
    }
    today_path = history_dir / f"{today.isoformat()}.json"
    try:
        today_path.write_text(
            json.dumps(history_snapshot, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("History snapshot written to %s", today_path)
    except Exception as exc:
        logger.warning("Failed to write history snapshot: %s", exc)

    click.echo(
        f"Build complete — {len(threats)} threat(s) rendered.\n"
        f"  HTML : {paths.get('html')}\n"
        f"  JSON : {paths.get('json')}\n"
        f"\nRun 'preview' to view locally:\n"
        f"  python -m src.main preview\n"
        f"  -> http://localhost:8080"
    )


if __name__ == "__main__":
    cli()
