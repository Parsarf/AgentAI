"""Destination guard for credentialed browsing and connector fetches (Phase 11).

HTTPS on port 443 only, no embedded credentials, host must be on the
profile's allowlist, and every resolved address must be public. Redirect
chains are rechecked hop by hop (max five). The resolver is injectable so the
guard is testable without DNS; in production it must resolve at connection
time and pin the checked address to avoid rebinding.
"""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlsplit, urljoin

MAX_REDIRECTS = 5
METADATA_HOSTS = {'metadata.google.internal', 'metadata', 'instance-data'}


class Blocked(Exception):
    pass


def system_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved)


def check_url(url: str, allowed_hosts, *, resolver=system_resolver) -> str:
    """Return the validated URL or raise Blocked. ``allowed_hosts`` are exact hostnames."""
    if not isinstance(url, str) or len(url) > 2048:
        raise Blocked('invalid url')
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().rstrip('.')
    if parts.scheme != 'https' or not host:
        raise Blocked('https required')
    if parts.username or parts.password:
        raise Blocked('credentials in url')
    try:
        port = parts.port
    except ValueError:
        raise Blocked('invalid port')
    if port not in (None, 443):
        raise Blocked('port not allowed')
    if host in METADATA_HOSTS or host not in {h.lower() for h in allowed_hosts}:
        raise Blocked('host not allowed')
    try:
        addresses = [host] if _is_ip(host) else resolver(host)
    except OSError:
        raise Blocked('resolution failed')
    if not addresses or not all(_public(a) for a in addresses):
        raise Blocked('non-public address')
    return url


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def follow(start: str, allowed_hosts, fetch, *, resolver=system_resolver) -> str:
    """Walk redirects with ``fetch(url) -> (status, location|None)``, rechecking each hop."""
    url = check_url(start, allowed_hosts, resolver=resolver)
    for _ in range(MAX_REDIRECTS + 1):
        status, location = fetch(url)
        if status not in (301, 302, 303, 307, 308):
            return url
        if not location:
            raise Blocked('redirect without location')
        url = check_url(urljoin(url, location), allowed_hosts, resolver=resolver)
    raise Blocked('too many redirects')
