"""Host exposure and permission checks: pure evaluators over text the monitor collects."""
import re
import stat

LISTEN = re.compile(r'LISTEN\s+\d+\s+\d+\s+(\S+):(\d+)\s')


def parse_listeners(ss_output):
    out = set()
    for line in ss_output.splitlines():
        m = LISTEN.search(line)
        if m: out.add((m.group(1).strip('[]'), int(m.group(2))))
    return out


def public(address): return address in ('0.0.0.0', '*', '::', '')


def evaluate_listeners(listeners, public_allowed, loopback_allowed):
    """Anything reachable from outside must be on the allowlist; unexpected loopback ports are only a warning."""
    findings = []
    for address, port in sorted(listeners):
        if public(address) and port not in public_allowed: findings.append(('crit', f'port {port} is listening on all interfaces and is not expected'))
        elif address.startswith('127.') or address == '::1':
            if port not in loopback_allowed and not (32768 <= port <= 60999): findings.append(('warn', f'unexpected local port {port}'))
        elif not public(address) and not address.startswith(('10.', '172.', '192.168.')) and port not in public_allowed:
            findings.append(('warn', f'port {port} bound to {address}'))
    return findings


def evaluate_ufw(text):
    if 'Status: active' not in text: return [('crit', 'host firewall is not active')]
    return []


def evaluate_modes(rows):
    """rows: (path, mode_int, uid, expected_max_mode, expected_uid). Secrets must not be group/world readable."""
    findings = []
    for path, mode, uid, max_mode, owner in rows:
        if stat.S_IMODE(mode) & ~max_mode: findings.append(('crit', f'{path} is more permissive than {oct(max_mode)}'))
        if owner is not None and uid != owner: findings.append(('warn', f'{path} is not owned by the expected user'))
    return findings


def evaluate_ssh(sshd_config_text):
    findings = []
    flat = {l.split(None, 1)[0].lower(): l.split(None, 1)[1].strip().lower() for l in sshd_config_text.splitlines() if l.strip() and not l.lstrip().startswith('#') and len(l.split(None, 1)) == 2}
    if flat.get('passwordauthentication', 'yes') == 'yes': findings.append(('warn', 'SSH accepts passwords (move to keys, then disable)'))
    if flat.get('permitrootlogin', 'yes') not in ('no', 'prohibit-password', 'without-password'): findings.append(('warn', 'SSH allows root login with a password'))
    return findings
