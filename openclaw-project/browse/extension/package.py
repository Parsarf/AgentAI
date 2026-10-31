#!/usr/bin/env python3
"""Build the zip to upload to the Chrome Web Store (or to load as a packed extension).

    python3 package.py [--out dist]

Only what Chrome needs at run time goes in: the manifest, the popup, the icons and the scripts. No tests, no dev tools, no README. The manifest is checked first
(every file it names exists, no host permissions, a store-ready name and description) and the build is refused if anything is wrong. The zip is reproducible: same
files in, same bytes out.
"""
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = ['manifest.json', 'popup.html', 'src/popup.css', 'src/popup.js', 'src/popup-model.js', 'src/background.js', 'src/config.js', 'src/executor.js', 'src/page.js', 'src/rules.js',
           'icons/icon-16.png', 'icons/icon-48.png', 'icons/icon-128.png']
STAMP = (2026, 1, 1, 0, 0, 0)               # fixed, so the same files always give the same zip


def referenced(manifest):
    """Every file the manifest points at."""
    files = {manifest['background']['service_worker'], manifest['action']['default_popup'], *manifest['icons'].values(), *manifest['action'].get('default_icon', {}).values()}
    return files


def check(manifest):
    problems = []
    if manifest.get('manifest_version') != 3:
        problems.append('manifest_version must be 3')
    if not re.fullmatch(r'\d+(\.\d+){0,3}', str(manifest.get('version', ''))):
        problems.append('version must look like 1.2.3')
    if not manifest.get('name') or re.search(r'dev(elopment)?|test|beta', manifest['name'], re.I):
        problems.append('name is empty or still says development/test')
    if not 1 <= len(manifest.get('description', '')) <= 132:
        problems.append('description must be 1 to 132 characters (the store limit)')
    if manifest.get('host_permissions') or manifest.get('optional_host_permissions'):
        problems.append('host permissions are not asked for: the extension acts only on tabs it opens')
    if set(manifest.get('permissions', [])) != {'debugger', 'tabGroups', 'storage'}:
        problems.append('permissions changed: update the store justifications, then this check')
    for size in ('16', '48', '128'):
        if size not in manifest.get('icons', {}):
            problems.append(f'icon {size} missing')
    for name in sorted(referenced(manifest) | set(RUNTIME)):
        if not (HERE / name).is_file():
            problems.append(f'missing file: {name}')
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(HERE / 'dist'))
    out_dir = Path(parser.parse_args().out)
    manifest = json.loads((HERE / 'manifest.json').read_text())
    problems = check(manifest)
    if problems:
        sys.exit('not building:\n  ' + '\n  '.join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f'lumina-browser-{manifest["version"]}.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(RUNTIME):
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
            z.writestr(info, (HERE / name).read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f'{target}\n{target.stat().st_size} bytes, {len(RUNTIME)} files, version {manifest["version"]}\nsha256 {digest}')


if __name__ == '__main__':
    main()
