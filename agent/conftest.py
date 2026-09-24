"""Phase 1 build session setup: puts deterministic test env vars in place
BEFORE any core module (and therefore core.config.settings) is imported."""

import os

_TEST_SESSION_SECRET = "test-only-session-secret-0123456789abcdef0123456789abcdef"
os.environ.setdefault("SESSION_SECRET", _TEST_SESSION_SECRET)
