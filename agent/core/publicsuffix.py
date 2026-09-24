"""Strict merchant normalization using the installed, bundled suffix data.

The ``tld`` package reads its packaged public-suffix snapshot locally. No
runtime network request is needed to validate a purchase recipient.
"""

from __future__ import annotations

import ipaddress
import string

from tld import get_fld, get_tld

_ALLOWED = set(string.ascii_lowercase + string.digits + "-.")


def normalize_merchant_host(merchant: str) -> str:
    """Require a bare, ASCII DNS hostname with no URL or userinfo syntax."""
    host = str(merchant or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("merchant is required (a bare hostname like example.com)")
    if len(host) > 253:
        raise ValueError("merchant hostname is too long")
    if not set(host) <= _ALLOWED:
        raise ValueError("merchant must be a bare ASCII hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("merchant must be a domain name, not an IP address")
    labels = host.split(".")
    if len(labels) < 2:
        raise ValueError("merchant must be a fully-qualified domain name")
    for label in labels:
        if not label or len(label) > 63 or label.startswith("-") or label.endswith("-"):
            raise ValueError("merchant hostname has an invalid label")
    return host


def registrable_domain(host: str) -> str | None:
    """Return the eTLD+1 only for a known suffix and actual registrant."""
    url = f"http://{host}"
    suffix = get_tld(url, fail_silently=True)
    if not suffix or host == suffix:
        return None
    return get_fld(url, fail_silently=True)


def canonical_merchant(merchant: str) -> str:
    host = normalize_merchant_host(merchant)
    domain = registrable_domain(host)
    if domain is None:
        raise ValueError("merchant has no known registrable domain")
    return domain
