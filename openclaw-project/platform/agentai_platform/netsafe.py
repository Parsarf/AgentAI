"""Where Lumina's own servers may connect on a customer's behalf (stdlib only).

The relays and connectors run inside Lumina's network. A customer-supplied address (their own model endpoint, a remote MCP server, a connector fetch) that led to a
private address would turn them into a way to reach internal services: the model proxy's admin API, the database, the cloud metadata address. So every such feature
asks the same question here, and there is one answer to it.

`is_public_address` is that answer. It is deliberately the strictest of the rules the features used to carry separately:

  * the address must be globally routable (no loopback, private, link-local, carrier-grade NAT, documentation or unspecified ranges);
  * no multicast and no reserved space;
  * an IPv4 address wrapped in IPv6 (::ffff:a.b.c.d) is judged as the IPv4 address it is;
  * no IPv6 transition ranges that carry an IPv4 address inside them (6to4, Teredo, NAT64): they can name an internal IPv4 host while looking global.

Users: model_keys.py (own model endpoint: `is_public`), mcp_connections/network.py (`public_address`), ssrf.py (connector fetches).
The customer's *browser* is a different question (what a page may be opened, with loopback allowed in tests) and keeps its own rule in browse/native_runner.py.

`HOSTNAME` and `BLOCKED_SUFFIXES` are the matching rule for names as typed: a real public DNS name, never an IP literal or an internal-looking suffix.
"""
from __future__ import annotations
import ipaddress
import re

HOSTNAME = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]')
BLOCKED_SUFFIXES = ('.local', '.localhost', '.internal', '.lan', '.home', '.corp', '.intranet', '.arpa', '.test', '.invalid', '.example', '.onion')

_NAT64 = (ipaddress.ip_network('64:ff9b::/96'), ipaddress.ip_network('64:ff9b:1::/48'))


def is_public_address(value) -> bool:
    """True only for an address on the public internet. Anything unparseable is not public."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if ip.version == 6 and (ip.sixtofour or ip.teredo or any(ip in net for net in _NAT64)):
        return False
    return True
