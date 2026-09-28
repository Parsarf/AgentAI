#!/usr/bin/env python3
"""Install a replacement Brave API key from a trusted interactive VPS terminal."""

from getpass import getpass
import os
from pathlib import Path
import sys


TARGET = Path("/opt/openclaw-production/integrations/brave/private/api-key")


def main() -> int:
    if not sys.stdin.isatty():
        raise SystemExit("Run in a trusted interactive VPS terminal.")
    if not TARGET.is_file():
        raise SystemExit("Brave connector secret file is missing.")

    key = getpass("Replacement Brave API key: ").strip()
    if not key or any(character.isspace() for character in key):
        raise SystemExit("Expected one non-empty key without whitespace.")

    temporary = TARGET.with_name("api-key.new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(key + "\n")
        os.chown(temporary, 1000, 1000)
        temporary.chmod(0o400)
        os.replace(temporary, TARGET)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print("Brave connector key updated. Probe the connector before revoking the old key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
