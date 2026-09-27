#!/usr/bin/env python3
"""Manage tool connections on the VPS using native OpenClaw config and OAuth.

New definitions stay disabled. Explicit tool selection is required: arbitrary
MCP write calls are not covered by exec approvals. No credentials in arguments.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="Show native connector status without connecting")
    add = actions.add_parser("add", help="Register a disabled connector and reader policy")
    add.add_argument("name")
    source = add.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="HTTPS MCP endpoint; no credentials in URL")
    source.add_argument("--command", help="Operator-selected stdio executable")
    add.add_argument("--arg", action="append", default=[], help="Non-secret stdio argument")
    add.add_argument("--tools", required=True, help="Exact read tool names, comma separated")
    add.add_argument("--oauth", action="store_true", help="Use native protected HTTP OAuth")
    add.add_argument("--auth-profile", help="Existing protected native bearer profile ID")
    for action in ("enable", "disable", "remove", "login", "logout", "check"):
        command = actions.add_parser(action)
        command.add_argument("name")
    args = parser.parse_args()
    root = Path("/opt/openclaw-production")
    os.chdir(root)
    base = ["docker", "compose", "exec", "-T", "openclaw-gateway", "node", "dist/index.js"]

    def cli(*parts):
        result = subprocess.run(base + list(parts), capture_output=True, text=True, timeout=90)
        if result.returncode:
            # Native commands below contain no credential values.
            raise SystemExit(result.stderr or result.stdout or f"Native command exited {result.returncode}")
        return result.stdout

    if args.action == "list":
        print(cli("mcp", "status", "--json"))
        return
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,29}", args.name):
        raise SystemExit("Use1–30 lowercase letters/digits/hyphens, starting with a letter.")
    if args.action != "add":
        # Login URLs belong only in this trusted operator terminal.
        if args.action == "login":
            raise SystemExit(subprocess.run(base + ["mcp", "login", args.name]).returncode)
        if args.action in ("enable", "disable"):
            print(cli("mcp", "configure", args.name, "--" + args.action))
        elif args.action == "remove":
            print(cli("mcp", "unset", args.name))
            print("Definition removed; provider credentials/consent are not revoked.")
        elif args.action == "check":
            print(cli("mcp", "doctor", args.name, "--probe", "--json"))
        else:
            print(cli("mcp", args.action, args.name))
        return

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    if not tools or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", t) for t in tools):
        raise SystemExit("Select exact tool names; wildcard/all-tool grants are unsupported by this helper.")
    if args.command and (args.oauth or args.auth_profile):
        raise SystemExit("Native OAuth/profile binding requires an HTTP connector.")
    if args.url:
        from urllib.parse import urlsplit
        url = urlsplit(args.url)
        if url.scheme != "https" or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise SystemExit("Use an HTTPS endpoint without credentials, query or fragment.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    private = root / "integrations/connector-backups" / run_id
    private.mkdir(parents=True, mode=0o700)
    gateway = subprocess.check_output(["docker", "compose", "ps", "-q", "openclaw-gateway"], text=True).strip()
    backup = private / "openclaw.before.json"
    subprocess.run(["docker", "cp", f"{gateway}:/home/node/.openclaw/openclaw.json", str(backup)], check=True)
    backup.chmod(0o600)
    config = json.loads(backup.read_text())
    if args.name in config.get("mcp", {}).get("servers", {}):
        raise SystemExit("Connector already exists; preserve it and use native configure for changes.")
    if not config.get("agents", {}).get("entries", {}).get("researcher"):
        raise SystemExit("Restricted researcher role is missing; do not grant tools to a broader agent.")
    server = {"enabled": False, "connectionTimeoutMs": 15000, "requestTimeoutMs": 20000,
              "toolFilter": {"include": tools},
              "codex": {"agents": ["researcher"], "defaultToolsApprovalMode": "prompt"}}
    if args.url:
        server.update(url=args.url, transport="streamable-http")
    else:
        server.update(command=args.command, args=args.arg, transport="stdio")
    if args.oauth or args.auth_profile:
        server["auth"] = "oauth"
    if args.auth_profile:
        server["oauth"] = {"authProfileId": args.auth_profile}
    pattern = args.name + "__*"
    def extended(items, additions):
        return list(dict.fromkeys([*items, *additions]))
    changes = [{"path": "mcp.servers." + args.name, "value": server}]
    for path, old in [
        ("tools.alsoAllow", config["tools"].get("alsoAllow", [])),
        ("tools.sandbox.tools.allow", config["tools"]["sandbox"]["tools"].get("allow", [])),
        ("agents.entries.researcher.tools.allow", config["agents"]["entries"]["researcher"]["tools"].get("allow", [])),
    ]:
        changes.append({"path": path, "value": extended(old, [pattern])})
    changes.append({"path": "agents.entries.researcher.tools.profile", "value": "coding"})
    for agent, entry in config["agents"]["entries"].items():
        if agent != "researcher":
            changes.append({"path": f"agents.entries.{agent}.tools.deny",
                            "value": extended(entry.get("tools", {}).get("deny", []), ["bundle-mcp", pattern])})
    batch = private / "config.batch.json"
    batch.write_text(json.dumps(changes, indent=2) + "\n")
    batch.chmod(0o600)
    staging = "/tmp/connect-tool-" + run_id + ".json"
    subprocess.run(["docker", "cp", str(batch), gateway + ":" + staging], check=True)
    subprocess.run(["docker", "exec", "--user", "root", gateway, "chmod", "644", staging], check=True)
    try:
        cli("config", "set", "--batch-file", staging, "--dry-run")
        cli("config", "set", "--batch-file", staging)
        validation = json.loads(cli("config", "validate", "--json"))
        if not validation.get("valid"):
            raise SystemExit("Config validation failed; keep connector disabled and inspect private backup.")
        after = private / "openclaw.after.json"
        subprocess.run(["docker", "cp", f"{gateway}:/home/node/.openclaw/openclaw.json", str(after)], check=True)
        after.chmod(0o600)
        effective = json.loads(after.read_text())
        for change in changes:
            value = effective
            for key in change["path"].split("."):
                value = value[key]
            if value != change["value"]:
                raise SystemExit("Authored readback mismatch: " + change["path"])
        print(f"Registered {args.name}, disabled. Reader: researcher. Tools: {', '.join(tools)}")
        print(f"Private backup: {private}")
        print("Complete protected account setup, then explicitly enable and check the connector.")
    finally:
        subprocess.run(["docker", "exec", "--user", "root", gateway, "rm", "-f", staging], check=True)


if __name__ == "__main__":
    main()
