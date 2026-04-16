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
        # Insert token into URL: https://<token>@github.com/...
        repo_url = repo_url.replace("https://", f"https://{token}@", 1)

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

    if total_collected == 0:
        generation_notes.append(
            "No items were collected. Check source URLs and network connectivity."
        )

    # ── 2. Normalise ─────────────────────────────────────────────────────
    normalised = normalise_items(raw_items)

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

    # ── 5. Enrich ────────────────────────────────────────────────────────
    enrichment_cfg = cfg.get("enrichment", {})
    enricher = DeterministicEnricher(
        max_summary_words=int(enrichment_cfg.get("max_summary_words", 200))
    )

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
        ms_weights = (
            ScoringWeights(**ms_weight_kwargs)
            if ms_weight_kwargs
            else ScoringWeights(
                recency=0.40,
                source_credibility=0.10,
                corroboration=0.30,
                severity=0.10,
                breadth=0.05,
                actionability=0.05,
            )
        )
        ms_diversity_cap = int(ms_scoring_cfg.get("diversity_cap", 0))
        ms_scorer = Scorer(weights=ms_weights, diversity_cap=ms_diversity_cap)
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
