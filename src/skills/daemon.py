"""Daemon commands for skills CLI."""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from skills.overseer import Overseer

# Global daemon log (not project-specific)
DAEMON_LOG = Path.home() / ".config" / "skills" / "daemon.log"


def daemon_log(message: str) -> None:
    """Daemon-level logging (global, not project-specific)."""
    DAEMON_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    with open(DAEMON_LOG, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def daemonize() -> None:
    """Double-fork to create a proper daemon process."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits
        sys.exit(0)

    # Become session leader
    os.setsid()

    # Second fork
    pid = os.fork()
    if pid > 0:
        # First child exits
        sys.exit(0)

    # Now we're the grandchild (daemon)

    # Change working directory to root to avoid holding mounts
    os.chdir("/")

    # Close standard file descriptors
    sys.stdin.close()
    sys.stdout.close()
    sys.stderr.close()

    # Redirect to /dev/null
    devnull = os.open("/dev/null", os.O_RDWR)
    os.dup2(devnull, 0)  # stdin
    os.dup2(devnull, 1)  # stdout
    os.dup2(devnull, 2)  # stderr
    os.close(devnull)


def start() -> None:
    """Start the overseer daemon if not already running."""
    # Read stdin BEFORE forking (hook provides cwd)
    data = json.load(sys.stdin)
    cwd = data.get("cwd")

    if Overseer.is_running():
        daemon_log(f"overseer already running (pid={Overseer.get_pid()})")
        return

    # Fork once to let parent return immediately
    pid = os.fork()
    if pid > 0:
        # Parent returns to caller (hook)
        daemon_log(f"overseer starting (forked pid={pid}, cwd={cwd})")
        return

    # Child continues to daemonize
    daemonize()

    # Now running as daemon - pass cwd to overseer
    overseer = Overseer(cwd=cwd)
    asyncio.run(overseer.run())


def notify() -> None:
    """Send hook event to the running overseer via socket."""
    data = json.load(sys.stdin)
    daemon_log(f"notify received: {json.dumps(data)}")

    if not Overseer.is_running():
        daemon_log(
            "overseer not running, cannot notify (should have been started on SessionStart)"
        )
        return

    response = asyncio.run(Overseer.send_event(data))
    if response:
        daemon_log(f"overseer response: {response}")
    else:
        daemon_log("failed to send event to overseer")
