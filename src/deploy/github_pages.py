"""
GitHub Pages deployment module.

Copies all generated assets from the local output directory into a local
git staging directory, commits them, and pushes to a GitHub Pages branch.

Expected GitHub Pages layout (at the repo root):
  index.html
  latest.json
  stix/<threat-id>.json
  static/style.css
  static/app.js
  CNAME                  (optional — written when custom_domain is set)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitHubPagesDeployer:
    """
    Deploys output files to a GitHub Pages branch via git push.

    Authentication relies on whatever git credential helper is configured on
    the machine (e.g. Windows Credential Manager, gh CLI, or a personal
    access token embedded in the repo URL).
    """

    def __init__(
        self,
        repo_url: str,
        branch: str = "gh-pages",
        staging_dir: str = "gh-pages-staging",
        commit_name: str = "Threat Landscape Bot",
        commit_email: str = "threatlandscape@localhost",
        custom_domain: Optional[str] = None,
        subdir: Optional[str] = None,
    ) -> None:
        self.repo_url = repo_url
        self.branch = branch
        self.staging_path = Path(staging_dir).resolve()
        self.commit_name = commit_name
        self.commit_email = commit_email
        self.custom_domain = custom_domain
        # If set, only the named subdirectory within the branch is cleared and
        # repopulated.  The rest of the branch is left untouched.  Useful when
        # two pipelines share the same gh-pages branch.
        self.subdir = subdir.strip("/") if subdir else None

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _git(self, *args: str, cwd: Optional[Path] = None) -> str:
        """Run a git command and return stdout. Raises on non-zero exit."""
        cmd = ["git", *args]
        logger.debug("git %s", " ".join(args))
        result = subprocess.run(
            cmd,
            cwd=str(cwd or self.staging_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        return result.stdout.strip()

    def _ensure_staging_repo(self) -> None:
        """
        Prepare the staging directory as a git repo pointing at the
        correct remote branch.

        - First call: clones the repo (shallow, branch only).
          If the branch does not yet exist, initialises an orphan branch.
        - Subsequent calls: resets to origin to discard any leftover state.
        """
        if not self.staging_path.exists():
            self.staging_path.mkdir(parents=True)

        git_dir = self.staging_path / ".git"

        if not git_dir.exists():
            # Attempt a shallow clone of the target branch.
            logger.info("Cloning %s (branch: %s) into staging dir.", self.repo_url, self.branch)
            result = subprocess.run(
                [
                    "git", "clone",
                    "--depth", "1",
                    "--branch", self.branch,
                    self.repo_url,
                    str(self.staging_path),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Branch does not exist yet — initialise an orphan branch.
                logger.info(
                    "Branch '%s' not found on remote — initialising orphan branch.", self.branch
                )
                self._git("init", cwd=self.staging_path)
                self._git("checkout", "--orphan", self.branch)
                self._git("remote", "add", "origin", self.repo_url)
        else:
            # Repo already exists — fetch and reset to match origin.
            logger.debug("Staging repo exists; resetting to origin/%s.", self.branch)
            try:
                self._git("fetch", "--depth", "1", "origin", self.branch)
                self._git("reset", "--hard", f"origin/{self.branch}")
            except RuntimeError:
                # Branch may not exist on remote yet — that is fine.
                logger.debug("Remote branch not yet present; will create on push.")

        # Ensure the remote URL is current (may have changed, e.g. token rotation).
        try:
            self._git("remote", "set-url", "origin", self.repo_url)
        except RuntimeError:
            self._git("remote", "add", "origin", self.repo_url)

        # Configure identity for commits in this repo.
        self._git("config", "user.name", self.commit_name)
        self._git("config", "user.email", self.commit_email)

    def _clear_staging(self) -> None:
        """
        Remove tracked files from the staging directory.

        If self.subdir is set, only that subdirectory is cleared so that other
        pipelines' files on the same branch are not disturbed.
        Otherwise the entire root is cleared (excluding .git).
        """
        if self.subdir:
            target = self.staging_path / self.subdir
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
        else:
            for item in list(self.staging_path.iterdir()):
                if item.name == ".git":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def deploy(self, output_dir: Path) -> None:
        """
        Copy all generated assets from output_dir to the staging repo,
        commit, and push to GitHub Pages.
        """
        output_dir = output_dir.resolve()
        if not output_dir.exists():
            raise FileNotFoundError(f"Output directory not found: {output_dir}")

        logger.info("Preparing GitHub Pages staging repo.")
        self._ensure_staging_repo()
        self._clear_staging()

        # ── Copy files ───────────────────────────────────────────────────
        files_copied = 0
        # Destination root: staging root, or a named subdirectory within it.
        dst_root = self.staging_path / self.subdir if self.subdir else self.staging_path
        dst_root.mkdir(parents=True, exist_ok=True)

        for name in ("index.html", "latest.json", "source_debug.html"):
            src = output_dir / name
            if src.exists():
                shutil.copy2(src, dst_root / name)
                files_copied += 1
            else:
                logger.warning("Expected output file not found: %s", src)

        stix_src = output_dir / "stix"
        if stix_src.exists():
            shutil.copytree(stix_src, dst_root / "stix")
            files_copied += len(list(stix_src.glob("*.json")))

        static_src = output_dir / "static"
        if static_src.exists():
            shutil.copytree(static_src, dst_root / "static")
            files_copied += sum(1 for f in static_src.rglob("*") if f.is_file())

        # ── CNAME for custom domain (root-level only, not in subdirs) ────
        if self.custom_domain and not self.subdir:
            (self.staging_path / "CNAME").write_text(
                self.custom_domain.strip(), encoding="utf-8"
            )
            files_copied += 1
            logger.debug("Wrote CNAME: %s", self.custom_domain)

        logger.info("Copied %d file(s) to staging repo.", files_copied)

        # ── Commit ───────────────────────────────────────────────────────
        self._git("add", "-A")

        # Check whether there is anything to commit.
        status = self._git("status", "--porcelain")
        if not status:
            logger.info("No changes since last deploy — nothing to commit.")
            return

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        self._git("commit", "-m", f"Update threat landscape {date_str}")

        # ── Push ─────────────────────────────────────────────────────────
        logger.info("Pushing to origin/%s.", self.branch)
        self._git("push", "origin", self.branch)
        logger.info("GitHub Pages deployment complete.")
