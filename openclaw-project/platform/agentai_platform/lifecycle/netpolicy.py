"""Host firewall policy for customer cells; generated text only, no execution.

Cells live on their own Docker engine (default runtime gVisor) and per-cell
networks drawn from one address pool. Docker's own isolation already blocks
cell-to-cell and cell-to-owner-network forwarding, but a cell can still reach
every service bound on the host (SSH, HTTPS, anything on a bridge address).
This ruleset adds only DROP rules in a separate nftables table, so it can never
widen what Docker permits. It is loaded by a host unit, not by the app.

Allowed by default: public internet egress (translated by this table's postrouting chain). Allowed to the host: nothing except
the optional model-proxy endpoint, which is authenticated by a per-account
virtual key. Quarantined (restored) cells get all egress dropped.
"""
from dataclasses import dataclass
import ipaddress
import re

PRIVATE_RANGES = ('0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16',
                  '172.16.0.0/12','192.0.0.0/24','192.168.0.0/16','198.18.0.0/15',
                  '224.0.0.0/4','240.0.0.0/4')

@dataclass(frozen=True)
class NetPolicy:
    cell_pool: str                    # all cell networks, e.g. 10.78.0.0/16
    bridge_gateway: str               # dedicated cells bridge address, e.g. 10.77.0.1
    model_proxy_port: int | None = None
    quarantined: tuple[str, ...] = () # cell subnets with all egress dropped

    def __post_init__(self):
        pool = ipaddress.ip_network(self.cell_pool)
        if not pool.is_private or pool.version != 4 or pool.prefixlen < 8:
            raise ValueError('cell pool must be a private IPv4 network')
        gateway = ipaddress.ip_address(self.bridge_gateway)
        if gateway.version != 4 or not gateway.is_private:
            raise ValueError('bridge gateway must be private IPv4')
        if self.model_proxy_port is not None and (type(self.model_proxy_port) is not int
                or isinstance(self.model_proxy_port, bool) or not 1 <= self.model_proxy_port <= 65535):
            raise ValueError('invalid model proxy port')
        for subnet in self.quarantined:
            net = ipaddress.ip_network(subnet)
            if net.version != 4 or not net.subnet_of(pool):
                raise ValueError('quarantine subnet must be inside the cell pool')

    def ruleset(self, *, atomic=True) -> str:
        pool = ipaddress.ip_network(self.cell_pool)
        bridge_pool = ipaddress.ip_network(self.bridge_gateway + '/16', strict=False)
        sources = ', '.join(sorted({str(pool), str(bridge_pool)}))
        quarantine = ', '.join(sorted(str(ipaddress.ip_network(q)) for q in self.quarantined))
        # `table X` + `delete table X` + definition in one file replaces the table
        # in a single netlink transaction, so a reload never leaves cells unfiltered.
        lines = ['table inet agentai_cells', 'delete table inet agentai_cells'] if atomic else []
        lines += [
            'table inet agentai_cells {',
            '  set cell_sources { type ipv4_addr; flags interval; elements = { ' + sources + ' } }',
            '  set private_ranges { type ipv4_addr; flags interval; elements = { ' + ', '.join(PRIVATE_RANGES) + ' } }',
        ]
        if quarantine:
            lines.append('  set quarantined { type ipv4_addr; flags interval; elements = { ' + quarantine + ' } }')
        lines += [
            '  chain input {',
            '    type filter hook input priority -5; policy accept;',
            '    ip saddr != @cell_sources return',
            '    ct state established,related return',
        ]
        if self.model_proxy_port is not None:
            lines.append(f'    ip daddr {self.bridge_gateway} tcp dport {self.model_proxy_port} return')
        lines += [
            '    counter drop comment "cell to host services"',
            '  }',
            '  chain forward {',
            '    type filter hook forward priority -5; policy accept;',
            '    ip saddr != @cell_sources return',
        ]
        if quarantine:
            lines.append('    ip saddr @quarantined counter drop comment "quarantined cell egress"')
        lines += [
            '    ip daddr @private_ranges counter drop comment "cell to private/metadata"',
            '  }',
            # The cell engine does not touch iptables (two engines on one host clobber each other's chains),
            # so address translation for cell egress lives here. Forwarding is allowed by `ufw route` rules.
            '  chain postrouting {',
            '    type nat hook postrouting priority srcnat; policy accept;',
            '    ip saddr @cell_sources ip daddr != @cell_sources masquerade',
            '  }',
            '}',
        ]
        return '\n'.join(lines) + '\n'


def parse_counters(listing: str) -> dict:
    """Return packet counters per commented drop rule from `nft list table` output."""
    result = {}
    for match in re.finditer(r'counter packets (\d+) bytes (\d+) drop comment "([^"]+)"', listing):
        result[match.group(3)] = (int(match.group(1)), int(match.group(2)))
    return result
