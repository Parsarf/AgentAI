#!/usr/bin/env python3
"""Host operator: install a separate pinned CLI; never change owner binaries.

Run under a bounded systemd transient service. Ignore package install scripts;
this is a Fleet CLI candidate, not evidence of full plugin/runtime readiness.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

NODE_VERSION='24.16.0'
OPENCLAW_VERSION='2026.9.6'
NODE_SHA256='d804845d34eddc21dc1092b519d643ef40b1f58ec5dec5c22b1f4bd8fabde6c9'
PACKAGE_INTEGRITY='sha512-Ie0kyQSCVfFqixsgVg39vevUDq01Ch5u3+7Yu5Y3qARczmdAe+lzp8bVnO9925rHiW/+CFp70zfORCyPmCH31g=='
ROOT=Path('/opt/agentai-native/2026.9.6-node24.16.0')


def main():
    if os.geteuid()!=0 or platform.system()!='Linux' or platform.machine()!='x86_64':
        raise SystemExit('requires an authorized Linux x86_64 host operator')
    available=next(int(l.split()[1])*1024 for l in open('/proc/meminfo') if l.startswith('MemAvailable:'))
    # Installation alone: 384 MiB hard cap plus 512 MiB owner headroom.
    # This is not an admitted or measured customer task profile.
    if available<896*1024**2:
        raise SystemExit(f'insufficient installation headroom: available={available} required={896*1024**2}')
    if ROOT.exists() or ROOT.is_symlink(): raise SystemExit('existing candidate: inspect/reconcile before retry')
    ROOT.parent.mkdir(mode=0o755,exist_ok=True)
    if ROOT.parent.is_symlink() or ROOT.parent.stat().st_uid!=0 or ROOT.parent.stat().st_mode&0o022:
        raise SystemExit('unsafe native installation parent')
    ROOT.mkdir(mode=0o755);(ROOT/'cache').mkdir(mode=0o700)
    url=f'https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-linux-x64.tar.xz'
    archive=ROOT/'node.tar.xz';digest=hashlib.sha256();count=0
    with urllib.request.urlopen(url,timeout=30) as source,archive.open('xb') as target:
        while chunk:=source.read(1024*1024):
            count+=len(chunk)
            if count>100*1024**2: raise SystemExit('archive exceeds download bound')
            digest.update(chunk);target.write(chunk)
    if digest.hexdigest()!=NODE_SHA256: raise SystemExit('Node archive integrity mismatch')
    with tarfile.open(archive) as bundle:
        members=bundle.getmembers()
        if sum(max(0,m.size) for m in members)>300*1024**2 or len(members)>20000:
            raise SystemExit('archive exceeds extraction bound')
        prefix=f'node-v{NODE_VERSION}-linux-x64/'
        if any(not (m.name==prefix[:-1] or m.name.startswith(prefix)) for m in members):
            raise SystemExit('unexpected archive root')
        bundle.extractall(ROOT,filter='data')
    archive.unlink()
    node=ROOT/f'node-v{NODE_VERSION}-linux-x64/bin/node'
    npm=ROOT/f'node-v{NODE_VERSION}-linux-x64/lib/node_modules/npm/bin/npm-cli.js'
    target=ROOT/'cli'
    configs=ROOT/'npm-config';configs.mkdir(mode=0o700)
    for name in ('user.npmrc','global.npmrc'):
        path=configs/name;path.write_text('');path.chmod(0o600)
    env={'PATH':str(node.parent)+':/usr/bin:/bin','NODE_OPTIONS':'--max-old-space-size=144',
         'npm_config_cache':str(ROOT/'cache'),'npm_config_userconfig':str(configs/'user.npmrc'),
         'npm_config_globalconfig':str(configs/'global.npmrc')}
    subprocess.run([str(node),str(npm),'install','--prefix',str(target),'--registry','https://registry.npmjs.org',
        '--ignore-scripts','--omit=dev','--omit=optional','--no-audit','--no-fund',f'openclaw@{OPENCLAW_VERSION}'],
        env=env,check=True,timeout=480)
    lock=json.loads((target/'package-lock.json').read_text())
    package=lock['packages']['node_modules/openclaw']
    if package.get('version')!=OPENCLAW_VERSION or package.get('integrity')!=PACKAGE_INTEGRITY:
        raise SystemExit('CLI package identity mismatch; candidate not verified')
    manifest={'node_version':NODE_VERSION,'node_sha256':NODE_SHA256,
        'openclaw_version':OPENCLAW_VERSION,'package_integrity':PACKAGE_INTEGRITY,
        'lock_sha256':hashlib.sha256((target/'package-lock.json').read_bytes()).hexdigest(),
        'native_execution_enabled':False,'install_scripts_enabled':False}
    (ROOT/'candidate.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'candidate_installed':True,'native_execution_enabled':False}))


if __name__=='__main__': main()
