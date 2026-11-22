#!/usr/bin/env python3
"""Copy the page scripts from the runner (browse/runner.mjs, the reference copy) into the two other engines that run the same text in a page:
the customer's-own-Chrome extension (browse/extension/src/page.js) and the cell's own browser (platform/agentai_platform/browse/native_scripts.py).

The three used to be edited by hand and held together only by tests. Run this after changing describe, fingerprint, hitAt, focusActive or ready in runner.mjs;
`--check` exits 1 when a copy has drifted (the tests run it)."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER, EXTENSION, NATIVE = HERE / 'runner.mjs', HERE / 'extension' / 'src' / 'page.js', HERE.parent / 'platform' / 'agentai_platform' / 'browse' / 'native_scripts.py'
SHARED = ('describe', 'hitAt', 'focusActive', 'fingerprint', 'ready')
NATIVE_NAMES = {'describe': ('DESCRIBE', None), 'hitAt': ('HIT_AT', '  const { x, y } = args;\n'), 'fingerprint': ('FINGERPRINT', '  const sel = args.sel;\n')}


def function(source, name, prefix=''):
    found = re.search(r'\n' + re.escape(prefix) + r'function ' + name + r'\(([^)]*)\) \{\n([\s\S]*?\n)\}\n', source)
    if not found:
        raise SystemExit(f'{name} not found')
    return found


def main():
    check = '--check' in sys.argv
    runner, extension, native = RUNNER.read_text(), EXTENSION.read_text(), NATIVE.read_text()
    new_extension, new_native = extension, native
    for name in SHARED:
        src = function(runner, name)
        old = function(new_extension, name, 'export ')
        new_extension = new_extension[:old.start()] + '\nexport ' + src.group(0)[1:] + new_extension[old.end():]
    for name, (constant, unpack) in NATIVE_NAMES.items():
        body = function(runner, name).group(2)
        if name == 'describe':                         # the cell engine has no other way to learn the address and the window's width
            body = body.replace("return { elements: out, title: document.title.slice(0, 120), text:", "return { elements: out, title: document.title.slice(0, 120), url: location.href, text:")
            body = body.replace('window: vh, focus };', 'window: vh, width: vw, focus };')
            if 'url: location.href' not in body or 'width: vw' not in body:
                raise SystemExit('describe no longer ends the way the cell engine expects')
        text = '(args) => {\n' + (unpack or '') + body + '}'
        old = re.search(r'\n' + constant + r' = r"""([\s\S]*?)"""', new_native)
        new_native = new_native[:old.start(1)] + text + new_native[old.end(1):]
    drift = [str(p) for p, a, b in ((EXTENSION, extension, new_extension), (NATIVE, native, new_native)) if a != b]
    if check:
        if drift:
            raise SystemExit('page scripts have drifted from browse/runner.mjs: ' + ', '.join(drift) + ' (run browse/sync-page-scripts.py)')
        return
    EXTENSION.write_text(new_extension)
    NATIVE.write_text(new_native)
    print('synced' if drift else 'already in sync', *drift)


if __name__ == '__main__':
    main()
