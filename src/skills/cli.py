"""CLI for skills."""

import argparse
import json
from pathlib import Path

from skills import daemon
from skills.utils import get_settings_path, load_settings, save_settings

# Default config location
CONFIG_PATH = Path.home() / ".config" / "skills" / "config.json"

DEFAULT_CONFIG = {
    "trigger_mode": "tokens",  # "tokens" or "prompts"
    "token_threshold": 10000,  # trigger agent every N tokens
    "prompt_threshold": 5,     # trigger agent every N user prompts
    "trigger_on_first_response": True,  # trigger after first Claude response
}


def load_config() -> dict:
    """Load config or return defaults."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            config = json.load(f)
            return {**DEFAULT_CONFIG, **config}
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """Save config to file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def init(scope: str) -> None:
    """Initialize hooks for skills daemon."""
    settings_path = get_settings_path(scope)
    settings = load_settings(settings_path)

    if "hooks" not in settings:
        settings["hooks"] = {}

    # SessionStart hook to spawn daemon
    settings["hooks"]["SessionStart"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "skills daemon start",
                }
            ]
        }
    ]

    # UserPromptSubmit hook to notify daemon of user message
    settings["hooks"]["UserPromptSubmit"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "skills daemon notify",
                }
            ]
        }
    ]

    # Stop hook to notify daemon when Claude finishes responding
    settings["hooks"]["Stop"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "skills daemon notify",
                }
            ]
        }
    ]

    # SessionEnd hook to notify daemon of session close
    settings["hooks"]["SessionEnd"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": "skills daemon notify",
                }
            ]
        }
    ]

    save_settings(settings_path, settings)
    print(f"Initialized skills hooks in {settings_path}")


def config_cmd(args: argparse.Namespace) -> None:
    """Handle config subcommand."""
    config = load_config()

    if args.config_action == "show":
        print(json.dumps(config, indent=2))

    elif args.config_action == "set":
        key, value = args.key, args.value
        if key == "trigger_mode":
            if value not in ("tokens", "prompts"):
                print(f"Error: trigger_mode must be 'tokens' or 'prompts'")
                return
            config[key] = value
        elif key == "token_threshold":
            config[key] = int(value)
        elif key == "prompt_threshold":
            config[key] = int(value)
        elif key == "trigger_on_first_response":
            config[key] = value.lower() in ("true", "1", "yes")
        else:
            print(f"Error: unknown config key '{key}'")
            return

        save_config(config)
        print(f"Set {key} = {config[key]}")

    elif args.config_action == "reset":
        save_config(DEFAULT_CONFIG)
        print("Config reset to defaults")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="skills",
        description="Generate and dynamically track skills for Claude Code",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize skills hooks")
    init_parser.add_argument(
        "--user",
        action="store_const",
        const="user",
        dest="scope",
        help="Add hooks to user settings (~/.claude/settings.json)",
    )
    init_parser.add_argument(
        "--project",
        action="store_const",
        const="project",
        dest="scope",
        help="Add hooks to project settings (.claude/settings.json) [default]",
    )
    init_parser.add_argument(
        "--local",
        action="store_const",
        const="local",
        dest="scope",
        help="Add hooks to local settings (.claude/settings.local.json)",
    )

    # config command
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_action", required=True)

    config_subparsers.add_parser("show", help="Show current config")
    config_subparsers.add_parser("reset", help="Reset config to defaults")

    set_parser = config_subparsers.add_parser("set", help="Set a config value")
    set_parser.add_argument("key", help="Config key (trigger_mode, token_threshold, prompt_threshold, trigger_on_first_response)")
    set_parser.add_argument("value", help="Config value")

    # daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Daemon management")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    daemon_subparsers.add_parser("start", help="Start the daemon")
    daemon_subparsers.add_parser("notify", help="Notify daemon with context")

    args = parser.parse_args()

    if args.command == "init":
        scope = args.scope or "project"
        init(scope)
    elif args.command == "config":
        config_cmd(args)
    elif args.command == "daemon":
        if args.daemon_command == "start":
            daemon.start()
        elif args.daemon_command == "notify":
            daemon.notify()
