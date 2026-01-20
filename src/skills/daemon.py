"""Daemon commands for skills CLI."""

import asyncio
import json
import os
import sys
from pathlib import Path

from skills.overseer import Overseer

# dev directory is at repo root: skills/dev
REPO_ROOT = Path(__file__).parent.parent.parent


def _get_log_func():
    """Import log function from dev directory."""
    sys.path.insert(0, str(REPO_ROOT))
    from dev.log import log
    return log


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
    log = _get_log_func()

    if Overseer.is_running():
        log(f"overseer already running (pid={Overseer.get_pid()})")
        return

    # Fork once to let parent return immediately
    pid = os.fork()
    if pid > 0:
        # Parent returns to caller (hook)
        log(f"overseer starting (forked pid={pid})")
        return

    # Child continues to daemonize
    daemonize()

    # Now running as daemon
    overseer = Overseer()
    asyncio.run(overseer.run())


def notify() -> None:
    """Send hook event to the running overseer via socket."""
    log = _get_log_func()
    data = json.load(sys.stdin)
    log(f"notify received: {json.dumps(data)}")

    if not Overseer.is_running():
        log("overseer not running, starting...")
        start()
        # Give it a moment to start up
        import time
        time.sleep(0.2)

    response = asyncio.run(Overseer.send_event(data))
    if response:
        log(f"overseer response: {response}")
    else:
        log("failed to send event to overseer")
