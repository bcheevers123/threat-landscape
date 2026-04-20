"""
Cybersecurity Conferences pipeline — CLI entry point.

Usage:
  python -m src.conferences_main build    # render HTML + JSON from YAML seed data
  python -m src.conferences_main deploy   # push output/ to GitHub Pages
  python -m src.conferences_main run-all  # build + deploy
  python -m src.conferences_main preview  # serve output/ locally on port 8082
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import click
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "conferences" / "config" / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("conferences")


def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        logger.warning("Config not found at %s — using defaults.", config_path)
        return {}
    with config_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--config", default=str(_DEFAULT_CONFIG), show_default=True,
              help="Path to config.yaml")
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    ctx.ensure_object(dict)
    cfg = _load_config(Path(config))
    ctx.obj["config"] = cfg


# ---------------------------------------------------------------------------
# build command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def build(ctx: click.Context) -> None:
    """Render HTML and JSON from the conference YAML seed data."""
    from src.conferences.collector import load_events, all_tags, stats as calc_stats
    from src.conferences.renderer import ConferencesRenderer

    cfg = ctx.obj["config"]
    output_dir   = Path(cfg.get("output_dir",   "conferences/output"))
    template_dir = Path(cfg.get("template_dir", "conferences/templates"))
    static_dir   = Path(cfg.get("static_dir",   "static"))
    data_file    = Path(cfg.get("data_file",     "data/conferences.yaml"))
    lookforward  = int(cfg.get("lookforward_days", 365))
    branding     = cfg.get("branding", {})

    events = load_events(data_file=data_file, lookforward_days=lookforward)
    tags   = all_tags(events)
    s      = calc_stats(events)

    renderer = ConferencesRenderer(
        template_dir=template_dir,
        output_dir=output_dir,
        static_dir=static_dir,
        branding=branding,
    )
    paths = renderer.render_all(events, s, tags)

    # Override app.js and inject theme.css from conferences/static/
    _conf_static = _PROJECT_ROOT / "conferences" / "static"
    for _fname in ("app.js", "theme.css"):
        _src = _conf_static / _fname
        _dst = output_dir / "static" / _fname
        if _src.exists():
            import shutil
            shutil.copy2(str(_src), str(_dst))
            logger.info("Injected conferences/static/%s", _fname)

    click.echo(f"Built {len(events)} events -> {paths['html']}")


# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def deploy(ctx: click.Context) -> None:
    """Deploy generated assets to GitHub Pages."""
    cfg = ctx.obj["config"]
    output_dir  = Path(cfg.get("output_dir", "conferences/output"))
    target      = cfg.get("deploy_target", "github_pages")

    if target == "github_pages":
        _deploy_github_pages(cfg, output_dir)
    else:
        click.echo("SFTP deployment not yet configured for conferences.", err=True)

    click.echo("Deployment complete.")


def _deploy_github_pages(cfg: dict, output_dir: Path) -> None:
    from src.deploy.github_pages import GitHubPagesDeployer

    gpcfg    = cfg.get("github_pages", {})
    token    = os.environ.get("GITHUB_TOKEN", "")
    repo_url = gpcfg.get("repo_url", "")

    if token and repo_url.startswith("https://github.com/"):
        repo_url = repo_url.replace(
            "https://github.com/",
            f"https://x-access-token:{token}@github.com/",
        )

    if not repo_url:
        click.echo("Error: github_pages.repo_url not set in config.yaml.", err=True)
        return

    staging_dir = str(_PROJECT_ROOT / gpcfg.get("staging_dir", "gh-pages-staging"))

    deployer = GitHubPagesDeployer(
        repo_url=repo_url,
        branch=gpcfg.get("branch", "gh-pages"),
        staging_dir=staging_dir,
        commit_name=gpcfg.get("commit_name",  "Threat Landscape Bot"),
        commit_email=gpcfg.get("commit_email", "threatlandscape@localhost"),
        custom_domain=gpcfg.get("custom_domain") or None,
        subdir=gpcfg.get("subdir") or None,
    )
    deployer.deploy(output_dir)


# ---------------------------------------------------------------------------
# run-all command
# ---------------------------------------------------------------------------

@cli.command("run-all")
@click.pass_context
def run_all(ctx: click.Context) -> None:
    """Build then deploy."""
    ctx.invoke(build)
    ctx.invoke(deploy)


# ---------------------------------------------------------------------------
# preview command
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def preview(ctx: click.Context) -> None:
    """Serve output/ locally on port 8082."""
    import http.server
    import socketserver
    cfg        = ctx.obj["config"]
    output_dir = Path(cfg.get("output_dir", "conferences/output"))
    port       = 8082
    click.echo(f"Serving {output_dir} at http://localhost:{port}/")
    import os
    os.chdir(str(output_dir))
    with socketserver.TCPServer(("", port), http.server.SimpleHTTPRequestHandler) as httpd:
        httpd.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
