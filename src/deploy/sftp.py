"""
SFTP deployment module.

Uploads all generated assets from the local output directory to the
remote web host.  Uses paramiko for SFTP and tenacity for retry logic.

Expected remote layout (relative to remote_base):
  latest.json
  index.html
  stix/<threat-id>.json
  static/style.css
  static/app.js
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import paramiko
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class SFTPDeployer:
    """Deploys output files to a remote host via SFTP."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        key_path: Optional[str] = None,
        password: Optional[str] = None,
        remote_base: str = (
            "/public_html/wp-content/uploads/barry-threat-landscape"
        ),
        timeout: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.key_path = key_path
        self._password = password  # private — never logged or repr'd
        self.remote_base = remote_base.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"SFTPDeployer(host={self.host!r}, port={self.port}, "
            f"username={self.username!r})"
        )

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _open_connection(self) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """Open an SSH connection and return (ssh_client, sftp_client)."""
        ssh = paramiko.SSHClient()
        # Load known_hosts so the server's key is verified against a local
        # trust store.  RejectPolicy means an unknown host key causes a hard
        # failure rather than silently accepting it (which would allow MITM).
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

        kwargs: dict = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }
        if self.key_path:
            kwargs["key_filename"] = os.path.expanduser(self.key_path)
        if self._password:
            kwargs["password"] = self._password

        ssh.connect(**kwargs)
        return ssh, ssh.open_sftp()

    def _ensure_dir(self, sftp: paramiko.SFTPClient, remote_path: str) -> None:
        """Create remote directories recursively if they do not exist."""
        # Normalise separators
        parts = [p for p in remote_path.replace("\\", "/").split("/") if p]
        current = "/" if remote_path.startswith("/") else ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            try:
                sftp.stat(current)
            except FileNotFoundError:
                logger.debug("Creating remote directory: %s", current)
                sftp.mkdir(current)

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    def _upload(
        self, sftp: paramiko.SFTPClient, local: Path, remote: str
    ) -> None:
        """Upload a single file with retry on transient failures."""
        local_size = local.stat().st_size
        sftp.put(str(local), remote)
        remote_size = sftp.stat(remote).st_size
        if remote_size != local_size:
            raise IOError(
                f"Upload size mismatch for '{local.name}': "
                f"expected {local_size} bytes, got {remote_size}"
            )
        logger.debug("Uploaded: %s → %s (%d bytes)", local.name, remote, local_size)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def deploy(self, output_dir: Path) -> None:
        """
        Upload all generated assets from output_dir to the remote host.

        Files uploaded:
          - latest.json
          - index.html
          - stix/*.json
          - static/**
        """
        ssh, sftp = self._open_connection()
        try:
            self._ensure_dir(sftp, self.remote_base)

            uploads: list[tuple[Path, str]] = []

            for name in ("latest.json", "index.html"):
                local = output_dir / name
                if local.exists():
                    uploads.append((local, f"{self.remote_base}/{name}"))
                else:
                    logger.warning("Expected output file not found: %s", local)

            stix_dir = output_dir / "stix"
            if stix_dir.exists():
                remote_stix = f"{self.remote_base}/stix"
                self._ensure_dir(sftp, remote_stix)
                for f in sorted(stix_dir.glob("*.json")):
                    uploads.append((f, f"{remote_stix}/{f.name}"))

            static_dir = output_dir / "static"
            if static_dir.exists():
                remote_static = f"{self.remote_base}/static"
                self._ensure_dir(sftp, remote_static)
                for f in sorted(static_dir.rglob("*")):
                    if f.is_file():
                        rel = f.relative_to(static_dir).as_posix()
                        remote_path = f"{remote_static}/{rel}"
                        parent = remote_path.rsplit("/", 1)[0]
                        self._ensure_dir(sftp, parent)
                        uploads.append((f, remote_path))

            logger.info(
                "Deploying %d file(s) to %s:%s",
                len(uploads), self.host, self.remote_base,
            )
            for local, remote in uploads:
                self._upload(sftp, local, remote)

            logger.info("Deployment complete.")
        finally:
            sftp.close()
            ssh.close()
