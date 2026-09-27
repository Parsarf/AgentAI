#!/usr/bin/env python3
"""Prepare disabled native integration definitions; never authenticate or read mail.

Runs on the production host. Input bundle is public configuration only.
Existing configuration is backed up privately, then changed with native CLI.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text())
    root = Path("/opt/openclaw-production")
    os.chdir(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    private = root / "integrations/google/private"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    os.chown(private, 1000, 1000)
    artifacts = root / "integrations/phase6" / run_id
    artifacts.mkdir(parents=True, mode=0o700)

    def cli(*parts, timeout=60):
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "openclaw-gateway",
             "node", "dist/index.js", *parts],
            capture_output=True, text=True, timeout=timeout,
        )
        # Never echo arbitrary config/auth output to operator logs.
        if result.returncode:
            (artifacts / "native-error.txt").write_text(result.stderr + result.stdout)
            (artifacts / "native-error.txt").chmod(0o600)
            raise RuntimeError(f"Native {parts[0]} failed, exit {result.returncode}; private diagnostic saved")
        return result.stdout

    # Copy config through the container boundary, without printing its secrets.
    gateway = subprocess.check_output(
        ["docker", "compose", "ps", "-q", "openclaw-gateway"], text=True
    ).strip()
    backup = artifacts / "openclaw.before.json"
    subprocess.run(["docker", "cp", f"{gateway}:/home/node/.openclaw/openclaw.json", str(backup)], check=True)
    backup.chmod(0o600)
    config = json.loads(backup.read_text())
    existing = config.get("mcp", {}).get("servers", {})
    for name in ("google-readonly", "github-readonly"):
        if name in existing:
            raise RuntimeError(f"Preserve existing {name}; reconcile instead of overwriting")

    # Resolve and pin the base locally; freeze the complete installed environment.
    subprocess.run(["docker", "pull", "python:3.12-slim"], check=True, timeout=180)
    base = json.loads(subprocess.check_output(
        ["docker", "image", "inspect", "python:3.12-slim"], text=True
    ))[0]["RepoDigests"][0]
    dockerfile = bundle["dockerfile"].replace("FROM python:3.12-slim", "FROM " + base, 1)
    (artifacts / "Dockerfile").write_text(dockerfile)
    subprocess.run(["docker", "build", "-t", "openclaw-google-readonly:1.29.0",
                    "-f", str(artifacts / "Dockerfile"), str(artifacts)], check=True, timeout=300)
    image = json.loads(subprocess.check_output(
        ["docker", "image", "inspect", "openclaw-google-readonly:1.29.0"], text=True
    ))[0]["Id"]
    # No credential, no provider call: installed help is the only connector check.
    help_text = subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--read-only",
         "--cap-drop=ALL", "--security-opt=no-new-privileges",
         "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--env", "WORKSPACE_MCP_LOG_DIR=/tmp/logs", image, "--help"],
        text=True, timeout=45,
    )
    if "--read-only" not in help_text or "--tools" not in help_text:
        raise RuntimeError("Installed release lacks required read-only/service controls")
    (artifacts / "connector-help.txt").write_text(help_text)
    freeze = subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat",
         image, "/opt/connector-requirements.txt"], text=True, timeout=20)
    (artifacts / "connector-requirements.txt").write_text(freeze)

    google = {
        "enabled": False, "transport": "stdio", "command": "/usr/bin/docker",
        "args": ["run", "--rm", "-i", "--read-only", "--cap-drop=ALL",
                 "--security-opt=no-new-privileges", "--pids-limit=128",
                 "--memory=384m", "--cpus=0.5", "--user=1000:1000",
                 "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
                 "--mount", f"type=bind,src={private},dst=/data",
                 "--env", "WORKSPACE_MCP_LOG_DIR=/tmp/logs",
                 "--env", "WORKSPACE_MCP_MAX_FILE_BYTES=5242880",
                 "--env", "WORKSPACE_MCP_DISABLE_LOCAL_FILES=true",
                 "--env", "USER_GOOGLE_EMAIL=" + bundle["google_account"], image],
        "connectionTimeoutMs": 30000, "requestTimeoutMs": 20000,
        "toolFilter": {"include": ["search_gmail_messages", "get_gmail_message_content",
                      "get_gmail_messages_content_batch", "list_calendars", "get_events",
                      "search_drive_files", "get_drive_file_content", "list_drive_items"]},
        "codex": {"agents": ["researcher"]},
    }
    namespaces = ["google-readonly__*", "github-readonly__*"]
    def extended(items, additions):
        return list(dict.fromkeys([*items, *additions]))

    changes = [
        {"path": "mcp.servers.google-readonly", "value": google},
        {"path": "mcp.servers.github-readonly", "value": bundle["github"]},
        {"path": "tools.alsoAllow", "value": extended(config["tools"].get("alsoAllow", []), namespaces)},
        {"path": "tools.sandbox.tools.allow", "value": extended(config["tools"]["sandbox"]["tools"].get("allow", []), namespaces)},
        {"path": "agents.entries.researcher.tools.profile", "value": "coding"},
        {"path": "agents.entries.researcher.tools.allow", "value": extended(config["agents"]["entries"]["researcher"]["tools"]["allow"], namespaces)},
    ]
    for agent, entry in config["agents"]["entries"].items():
        if agent != "researcher":
            changes.append({"path": f"agents.entries.{agent}.tools.deny",
                            "value": extended(entry.get("tools", {}).get("deny", []), ["bundle-mcp", *namespaces])})
    batch = artifacts / "config.batch.json"
    batch.write_text(json.dumps(changes, indent=2) + "\n")
    remote_batch = "/tmp/phase6-config.batch.json"
    subprocess.run(["docker", "cp", str(batch), f"{gateway}:{remote_batch}"], check=True)
    subprocess.run(["docker", "exec", "--user", "root", gateway,
                    "chmod", "644", remote_batch], check=True)
    cli("config", "set", "--batch-file", remote_batch, "--dry-run")
    cli("config", "set", "--batch-file", remote_batch)
    for name in ("google-readonly", "github-readonly"):
        cli("mcp", "configure", name, "--approval", "prompt")
    validation = json.loads(cli("config", "validate", "--json"))
    if not validation.get("valid"):
        raise RuntimeError("Applied config did not validate")

    # Merge bounded instructions, preserving original bytes and later edits.
    for workspace in ("workspace", "workspace-researcher"):
        path = f"/home/node/.openclaw/{workspace}/AGENTS.md"
        original = artifacts / (workspace + ".AGENTS.before.md")
        subprocess.run(["docker", "cp", f"{gateway}:{path}", str(original)], check=True)
        original.chmod(0o600)
        content = original.read_text()
        if "<!-- BEGIN PHASE6 INTEGRATIONS -->" in content:
            raise RuntimeError("Existing Phase6 instructions need reconciliation")
        authored = artifacts / (workspace + ".AGENTS.after.md")
        authored.write_text(content.rstrip() + "\n\n" + bundle["rules"])
        authored.chmod(0o600)
        subprocess.run(["docker", "cp", str(authored), f"{gateway}:{path}"], check=True)
        subprocess.run(["docker", "exec", "--user", "root", gateway,
                        "chown", "1000:1000", path], check=True)

    after = artifacts / "openclaw.after.json"
    subprocess.run(["docker", "cp", f"{gateway}:/home/node/.openclaw/openclaw.json", str(after)], check=True)
    after.chmod(0o600)
    effective = json.loads(after.read_text())
    for change in changes:
        value = effective
        for key in change["path"].split("."):
            value = value[key]
        if change["path"].startswith("mcp.servers."):
            # Native configure adds the installed approval key; compare authored fields.
            assert all(value.get(k) == v for k, v in change["value"].items() if k != "codex")
            assert value["codex"]["agents"] == ["researcher"]
        else:
            assert value == change["value"], change["path"]
    status = json.loads(cli("mcp", "status", "--json"))
    subprocess.run(["docker", "exec", "--user", "root", gateway, "rm", "-f", remote_batch], check=True)
    result = {"run_id": run_id, "backup": str(artifacts), "base": base,
              "google_image": image, "changed_paths": [c["path"] for c in changes],
              "validation": validation, "status": status,
              "provider_calls": 0, "model_calls": 0, "connections_enabled": False}
    (artifacts / "application-readback.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
