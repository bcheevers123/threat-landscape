"""
setup_pc.py — Daily threat landscape service for Windows.

Runs the full pipeline (build + deploy) immediately on start, then repeats
every day at 07:00 GMT (UTC).  Runs as a detached background process with
no console window so it does not interrupt normal PC use.

Commands
--------
  python setup_pc.py start      Launch the background service (default).
  python setup_pc.py stop       Stop the running service.
  python setup_pc.py status     Show whether the service is running.
  python setup_pc.py run-now    Run the pipeline once in the foreground.
  python setup_pc.py install    Register a Task Scheduler task so the service
                                  starts automatically when you log in.
  python setup_pc.py uninstall  Remove the Task Scheduler task.

Logs are written to:  logs/pc_service.log
PID file is at:       logs/pc_service.pid
"""
from __future__ import annotations

import ctypes
import datetime
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
VENV_PYTHON  = PROJECT_DIR / "venv" / "Scripts" / "python.exe"
VENV_PYTHONW = PROJECT_DIR / "venv" / "Scripts" / "pythonw.exe"
LOG_DIR      = PROJECT_DIR / "logs"
LOG_FILE     = LOG_DIR / "pc_service.log"
PID_FILE     = LOG_DIR / "pc_service.pid"

TASK_NAME    = "ThreatLandscapePipeline"
RUN_HOUR_UTC = 7   # 07:00 GMT / UTC

# ---------------------------------------------------------------------------
# Logging (file + stderr)
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(parents=True, exist_ok=True)

_handler_file   = logging.FileHandler(LOG_FILE, encoding="utf-8")
_handler_stderr = logging.StreamHandler(sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S GMT",
    handlers=[_handler_file, _handler_stderr],
)
# Use UTC timestamps throughout
logging.Formatter.converter = time.gmtime

logger = logging.getLogger("setup_pc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pipeline_python() -> Path:
    """Return the Python executable to use for pipeline invocations."""
    if VENV_PYTHON.exists():
        return VENV_PYTHON
    # Fallback: use whichever Python is running this script
    return Path(sys.executable)


def _next_run_time() -> datetime.datetime:
    """Return the next 07:00 UTC datetime (tomorrow if today's has passed)."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    target = now.replace(hour=RUN_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    return target


def _seconds_until(dt: datetime.datetime) -> float:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return max(0.0, (dt - now).total_seconds())


def _run_pipeline() -> bool:
    """
    Invoke the pipeline via 'python -m src.main run-all'.

    Returns True on success, False on failure.
    """
    python = _pipeline_python()
    logger.info("Starting pipeline: %s -m src.main run-all", python.name)
    try:
        result = subprocess.run(
            [str(python), "-m", "src.main", "run-all"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=600,   # 10-minute hard timeout
        )
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                logger.info("  %s", line)
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                logger.warning("  %s", line)
        if result.returncode == 0:
            logger.info("Pipeline completed successfully.")
            return True
        else:
            logger.error("Pipeline exited with code %d.", result.returncode)
            return False
    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 10 minutes.")
        return False
    except Exception as exc:
        logger.error("Pipeline raised an exception: %s", exc)
        return False


# ---------------------------------------------------------------------------
# PID file management
# ---------------------------------------------------------------------------

def _write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid), encoding="utf-8")


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _clear_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def _process_alive(pid: int) -> bool:
    """Return True if a process with *pid* is currently running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Daemon loop (runs inside the background process)
# ---------------------------------------------------------------------------

def _daemon_loop() -> None:
    """
    Main service loop.

    1. Run the pipeline immediately.
    2. Calculate the next 07:00 UTC.
    3. Sleep in short intervals (to stay responsive to signals).
    4. Wake at 07:00 UTC and repeat.
    """
    _write_pid(os.getpid())
    logger.info("=" * 60)
    logger.info("Threat Landscape service started  (PID %d)", os.getpid())
    logger.info("Daily run time: %02d:00 GMT", RUN_HOUR_UTC)
    logger.info("Project dir:    %s", PROJECT_DIR)
    logger.info("=" * 60)

    # Graceful shutdown on SIGTERM / SIGINT
    _shutdown = False

    def _handle_signal(signum, _frame):
        nonlocal _shutdown
        logger.info("Received signal %d — shutting down after current sleep.", signum)
        _shutdown = True

    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        signal.signal(signal.SIGINT, _handle_signal)
    except (OSError, ValueError):
        pass  # SIGINT not always available on Windows subprocesses

    # --- First run immediately ---
    _run_pipeline()

    while not _shutdown:
        next_run = _next_run_time()
        wait_secs = _seconds_until(next_run)
        logger.info(
            "Next run scheduled at %s GMT (in %.0f minutes).",
            next_run.strftime("%Y-%m-%d %H:%M"),
            wait_secs / 60,
        )

        # Sleep in 60-second chunks so we can honour shutdown signals promptly
        elapsed = 0.0
        while elapsed < wait_secs and not _shutdown:
            chunk = min(60.0, wait_secs - elapsed)
            time.sleep(chunk)
            elapsed += chunk

        if not _shutdown:
            logger.info("Wake-up: running scheduled pipeline.")
            _run_pipeline()

    logger.info("Service stopped cleanly.")
    _clear_pid()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start() -> None:
    """Launch the service as a detached background process."""
    existing_pid = _read_pid()
    if existing_pid and _process_alive(existing_pid):
        print(f"Service is already running (PID {existing_pid}).")
        print(f"  Logs: {LOG_FILE}")
        return

    _clear_pid()

    # Use pythonw.exe so no console window appears
    launcher = VENV_PYTHONW if VENV_PYTHONW.exists() else Path(sys.executable)

    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — Windows-specific flags
    # that fully decouple the child from this console session.
    DETACHED_PROCESS        = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [str(launcher), str(Path(__file__).resolve()), "_daemon"],
        cwd=str(PROJECT_DIR),
        creationflags=creationflags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Brief pause to let the child write its PID file
    time.sleep(1.5)
    pid = _read_pid() or proc.pid
    print(f"Service started in the background (PID {pid}).")
    print(f"  Logs:    {LOG_FILE}")
    print(f"  Stop:    python setup_pc.py stop")
    print(f"  Status:  python setup_pc.py status")


def cmd_stop() -> None:
    """Stop the running background service."""
    pid = _read_pid()
    if pid is None:
        print("Service does not appear to be running (no PID file found).")
        return
    if not _process_alive(pid):
        print(f"No process found with PID {pid} — service may have already stopped.")
        _clear_pid()
        return

    print(f"Stopping service (PID {pid})…")
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        check=False,
        capture_output=True,
    )

    # Wait up to 10 seconds for the process to exit
    for _ in range(20):
        time.sleep(0.5)
        if not _process_alive(pid):
            break

    if _process_alive(pid):
        print(f"Process {pid} did not exit — try: taskkill /PID {pid} /F")
    else:
        _clear_pid()
        print("Service stopped.")


def cmd_status() -> None:
    """Print the current service status."""
    pid = _read_pid()
    if pid and _process_alive(pid):
        print(f"Service is RUNNING  (PID {pid})")
        print(f"  Logs: {LOG_FILE}")
        nxt = _next_run_time()
        secs = _seconds_until(nxt)
        hours, rem = divmod(int(secs), 3600)
        mins = rem // 60
        print(f"  Next run: {nxt.strftime('%Y-%m-%d %H:%M GMT')}  ({hours}h {mins}m from now)")
    else:
        print("Service is NOT RUNNING.")
        if pid:
            print(f"  (Stale PID file for {pid} — will be cleared on next start)")
        print(f"  Start with: python setup_pc.py start")


def cmd_run_now() -> None:
    """Run the pipeline once in the foreground (blocking)."""
    print("Running pipeline now (foreground)…")
    success = _run_pipeline()
    sys.exit(0 if success else 1)


def cmd_install() -> None:
    """
    Register a Windows Task Scheduler task that starts the service
    automatically when you log in.
    """
    launcher = VENV_PYTHONW if VENV_PYTHONW.exists() else Path(sys.executable)
    script   = Path(__file__).resolve()

    # schtasks /create — run at logon, once per user session
    cmd = [
        "schtasks", "/create", "/f",
        "/tn", TASK_NAME,
        "/tr", f'"{launcher}" "{script}" start',
        "/sc", "ONLOGON",
        "/rl", "HIGHEST",
        "/delay", "0001:00",   # wait 1 minute after logon before starting
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Task Scheduler task '{TASK_NAME}' created.")
        print("  The service will start automatically the next time you log in.")
        print("  To start it right now:  python setup_pc.py start")
    else:
        print(f"Failed to create task: {result.stderr.strip()}")
        print("  You may need to run this command in an elevated (Administrator) prompt.")


def cmd_uninstall() -> None:
    """Remove the Task Scheduler task."""
    # Stop the service first if running
    pid = _read_pid()
    if pid and _process_alive(pid):
        print("Stopping running service first…")
        cmd_stop()

    result = subprocess.run(
        ["schtasks", "/delete", "/f", "/tn", TASK_NAME],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Task Scheduler task '{TASK_NAME}' removed.")
    else:
        err = result.stderr.strip()
        if "cannot find" in err.lower():
            print("Task was not installed — nothing to remove.")
        else:
            print(f"Failed to remove task: {err}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS: dict[str, object] = {
    "start":     cmd_start,
    "stop":      cmd_stop,
    "status":    cmd_status,
    "run-now":   cmd_run_now,
    "install":   cmd_install,
    "uninstall": cmd_uninstall,
    "_daemon":   _daemon_loop,   # internal — called by the background process
}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command not in COMMANDS:
        print(__doc__)
        print(f"Unknown command: {command!r}")
        sys.exit(1)

    COMMANDS[command]()


if __name__ == "__main__":
    main()
