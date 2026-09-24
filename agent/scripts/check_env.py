"""Check which operator credentials are set in .env — prints only SET/MISSING,
never values. Run after editing .env:  python scripts/check_env.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402

PHASE_NEEDS = {
    "Phase 1 (running)": ["database_url", "session_secret"],
    "Phase 2 (core loop)": ["anthropic_api_key", "search_api_key", "telegram_bot_token"],
    "Phase 4 (browser/vault)": ["vault_master_key"],
    "Phase 5 (billing)": ["stripe_secret_key", "stripe_webhook_secret"],
}


def main() -> int:
    ok = True
    for phase, keys in PHASE_NEEDS.items():
        print(f"\n{phase}:")
        for key in keys:
            value = getattr(settings.secrets, key, None)
            state = "SET     " if value else "MISSING "
            ok &= bool(value)
            print(f"  [{state}] {key.upper()}")
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
