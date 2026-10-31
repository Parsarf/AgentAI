"""One scrubber for anything that leaves the host toward a third party that does not need personal data (classifiers, choosers).

Removes obvious personal and credential data: emails, phone numbers, card / account / ID numbers, street addresses, IP addresses,
URL credentials and long token-like strings. It is deliberately aggressive: those services only need the shape of a request.
"""
from __future__ import annotations
import re
from contextvars import ContextVar

STREET = r'(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|Highway|Hwy)'
PATTERNS = [re.compile(p, re.I | re.S) for p in (
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)',
    r'\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@\S+',                                  # credentials inside a URL
    r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',                                # email
    r'\bsk-[A-Za-z0-9_-]{12,}',
    r'(?:api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*(?:bearer\s+)?\S+',
    r'\bbearer\s+[A-Za-z0-9._~+/=-]{12,}',
    r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b',                                              # IBAN
    r'\b\d{3}-\d{2}-\d{4}\b',                                                         # US SSN shape
    r'(?<!\w)(?:\d[ -]?){12,19}\d(?!\w)',                                             # card / account numbers, with spaces or dashes
    r'(?<![\w.])\+?\(?\d{1,4}\)?[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?![\w.])',   # phone numbers
    r'\b\d{2,4}[ .-]\d{3,4}[ .-]\d{3,4}\b',                                          # grouped phone numbers
    r'\b\d{1,6}\s+(?:[A-Za-z0-9.\'-]+\s+){1,4}' + STREET + r'\b\.?',                  # street address
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b',                                                   # IPv4
    r'\b[A-Fa-f0-9]{32,}\b',                                                          # long hex (hashes, keys)
    r'\b[A-Za-z0-9_-]{40,}\b',                                                        # long token-like strings
)]


# Whether scrub() actually removes things in this thread of work. A browse job sets it per step from the account's `personal_data_scrub` safety switch (browse/loop.py), so the
# text sent to the browser model can go unscrubbed for an account that switched it off. Everything else (stored traces, logs) calls scrub(..., force=True) and is never affected.
_ACTIVE: ContextVar[bool] = ContextVar('agentai_scrub_active', default=True)


def set_scrubbing(on: bool):
    """-> a token for reset_scrubbing."""
    return _ACTIVE.set(bool(on))


def reset_scrubbing(token) -> None:
    _ACTIVE.reset(token)


def scrub(text, limit=None, *, force=False):
    out = str(text or '')
    if force or _ACTIVE.get():
        for pattern in PATTERNS:
            out = pattern.sub('[redacted]', out)
    return out if limit is None else out[:limit]
