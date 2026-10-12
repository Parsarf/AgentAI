"""Dependency and image pinning checks: pure evaluators over file text the monitor reads."""
import re

LOCAL_BUILDS = {'openclaw-gateway:2026.9.6-sdk-peer'}   # built on this host from a digest-pinned base (phase4-sdk-image/Dockerfile)


def evaluate_compose(text):
    findings = []
    for image in re.findall(r'^\s*image:\s*(\S+)', text, re.M):
        if '@sha256:' in image or image in LOCAL_BUILDS: continue
        findings.append(('crit' if ':latest' in image or ':' not in image else 'warn', f'image is not pinned by digest: {image.split(":")[0]}'))
    return findings


def evaluate_lock(text):
    """Every requirement line must carry a hash and an exact version."""
    findings = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', '--hash')): continue
        if '==' not in line: findings.append(('crit', 'a requirement has no exact version'))
        elif '--hash=' not in line and not line.rstrip().endswith('\\'): findings.append(('crit', 'a requirement has no hash'))
    return findings


def evaluate_custody(manifest):
    """The native CLI binaries must be digest-recorded."""
    cli = manifest.get('cli', {})
    return [] if cli.get('node_sha256') and cli.get('entry_sha256') else [('crit', 'native CLI custody has no recorded digests')]
