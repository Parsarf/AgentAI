#!/usr/bin/env python3
"""Prepare a NEW server state without reading secrets or starting services."""
import argparse
import json
import os
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telegram-owner-id",
        default=os.environ.get("TELEGRAM_USER_ID"),
        help="Numeric owner ID; defaults to the TELEGRAM_USER_ID environment variable",
    )
    parser.add_argument("--env-file", type=Path, help="Read TELEGRAM_USER_ID from this dotenv file")
    args = parser.parse_args()
    owner_id = args.telegram_owner_id
    if owner_id is None and args.env_file is not None:
        matches = []
        for line in args.env_file.read_text().splitlines():
            match = re.fullmatch(
                r"\s*(?:export\s+)?TELEGRAM_USER_ID\s*=\s*([0-9]+|'[0-9]+'|\"[0-9]+\")\s*(?:#.*)?",
                line,
            )
            if match:
                matches.append(match.group(1).strip("\"'"))
        if len(matches) != 1:
            parser.error("The dotenv file must contain one numeric TELEGRAM_USER_ID assignment")
        owner_id = matches[0]
    if not owner_id or not owner_id.isascii() or not owner_id.isdecimal() or int(owner_id) <= 0:
        parser.error("Set TELEGRAM_USER_ID or --telegram-owner-id to a positive numeric user ID")

    project = Path(__file__).resolve().parents[1]
    deploy = project / "deploy"
    state = deploy / "openclaw-state"
    # Existing state must be backed up and changed with the native CLI.
    if state.exists() or state.is_symlink():
        parser.error("Refusing existing openclaw-state; use native configuration commands")

    config = json.loads((project / "config/openclaw.example.json").read_text())
    config["gateway"]["controlUi"] = {
        "allowedOrigins": ["http://localhost:18789", "http://127.0.0.1:18789"]
    }
    config["gateway"]["auth"]["rateLimit"] = {
        "maxAttempts": 10, "windowMs": 60000, "lockoutMs": 300000
    }
    # Phase 1 is chat only. Docker tool isolation is verified in Phase 2.
    config["agents"]["defaults"]["sandbox"] = {"mode": "off"}
    config["tools"] = {
        "profile": "minimal",
        "allow": ["session_status"],
        "deny": ["gateway"],
        "elevated": {"enabled": False},
    }
    config["browser"]["enabled"] = False
    config["channels"]["telegram"].update({
        "enabled": False,
        "dmPolicy": "allowlist",
        "allowFrom": [owner_id],
        "groupPolicy": "disabled",
    })
    config["commands"] = {"ownerAllowFrom": [f"telegram:{owner_id}"]}

    os.umask(0o077)
    for name in ("workspace", "secrets", "evidence"):
        directory = deploy / name
        if directory.is_symlink():
            parser.error(f"Refusing symlink: {directory.name}")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_mode & 0o077:
            parser.error(f"Directory must be mode 0700: {directory.name}")
    state.mkdir(mode=0o700)
    # Exclusive creation: no overwrite of a config or existing runtime state.
    with (state / "openclaw.json").open("x") as output:
        json.dump(config, output, indent=2)
        output.write("\n")
    print("Prepared private Phase 1 state; Telegram disabled, services not started.")
    print("Assign state/workspace ownership to the image UID before native checks.")


if __name__ == "__main__":
    main()
