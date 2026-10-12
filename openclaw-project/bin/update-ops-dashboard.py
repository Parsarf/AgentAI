#!/usr/bin/env python3
"""Update the private ops dashboard on the VPS so it has the Feature switches page.

One command, no hand editing:
    python3 openclaw-project/bin/update-ops-dashboard.py            # shows the plan only
    python3 openclaw-project/bin/update-ops-dashboard.py --apply    # does it

Steps (each checked; any failure stops and tells you how to roll back):
  1. back up the current dashboard directory on the server (timestamped copy)
  2. copy app.py and switches.py, create the feature-switches folder with an empty
     facts file (nothing becomes available because of this update)
  3. restart only openclaw-dashboard and check that the sign-in page answers
It never prints credentials, never touches the Gateway, the proxy or any customer data.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DASH = "/opt/openclaw-production/dashboard"
SWITCH_DIR = "/opt/openclaw-production/feature-switches"
FILES = {
    REPO / "openclaw-project/dashboard/app.py": DASH + "/app.py",
    REPO / "openclaw-project/platform/agentai_platform/switches.py": DASH + "/switches.py",
    REPO / "openclaw-project/platform/agentai_platform/routing/config.py": DASH + "/routing_config.py",
}
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
BACKUP = f"{DASH}.bak-{STAMP}"

PLAN = [
    ("Back up the current dashboard", f"cp -a {DASH} {BACKUP}"),
    ("Create the switches folder", f"mkdir -p {SWITCH_DIR} && test -e {SWITCH_DIR}/facts.json || echo '{{}}' > {SWITCH_DIR}/facts.json"),
]


def ssh(command: str) -> tuple[int, str]:
    result = subprocess.run([sys.executable, str(HERE / "ssh-server"), command], capture_output=True, text=True, timeout=120)
    return result.returncode, (result.stdout + result.stderr).strip()


def main() -> int:
    apply = "--apply" in sys.argv
    for local in FILES:
        if not local.exists():
            print(f"missing {local}")
            return 2
    print("Plan:" if not apply else "Applying:")
    for title, command in PLAN:
        print(f"  - {title}")
    for local, remote in FILES.items():
        print(f"  - Copy {local.name} -> {remote}")
    print("  - Restart openclaw-dashboard and check the sign-in page")
    if not apply:
        print("\nNothing was changed. Run again with --apply to do it.")
        return 0
    for title, command in PLAN:
        code, out = ssh(command)
        if code != 0:
            print(f"FAILED: {title}\n{out}\nNothing further was done.")
            return 1
    for local, remote in FILES.items():
        code = subprocess.run([sys.executable, str(HERE / "scp-server"), str(local), remote]).returncode
        if code != 0:
            print(f"FAILED copying {local.name}. Roll back with: ssh-server 'rm -rf {DASH} && mv {BACKUP} {DASH}'")
            return 1
    code, out = ssh("systemctl restart openclaw-dashboard && sleep 2 && systemctl is-active openclaw-dashboard "
                    "&& curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18795/login")
    if code != 0 or not re.search(r"active\s+200", out.replace("\n", " ")):
        print(f"FAILED to confirm the dashboard.\n{out}\nRoll back with: ssh-server 'rm -rf {DASH} && mv {BACKUP} {DASH} && systemctl restart openclaw-dashboard'")
        return 1
    print(f"Done. Open it with: python3 openclaw-project/bin/open-ops-dashboard.py  (then choose Feature switches).\nBackup kept at {BACKUP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
