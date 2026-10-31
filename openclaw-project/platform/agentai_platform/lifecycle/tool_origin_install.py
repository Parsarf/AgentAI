"""Install the pinned runtime hook outside the assistant's working directory."""
import os
from pathlib import Path

PLUGIN_ID = 'lumina-tool-origin'
CONTAINER_PATH = '/home/node/.openclaw/extensions/' + PLUGIN_ID


def install(root, *, chown=lambda p, u, g: None):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('unsafe cell root')
    target = root / 'extensions' / PLUGIN_ID
    for directory in (target.parent, target):
        if directory.is_symlink():
            raise ValueError('unsafe plugin directory')
        directory.mkdir(exist_ok=True)
        os.chmod(directory, 0o755)
        chown(directory, 1000, 1000)
    source = Path(__file__).with_name('tool_origin_plugin')
    for name in ('index.mjs', 'openclaw.plugin.json'):
        path = target / name
        if path.is_symlink():
            raise ValueError('unsafe plugin file')
        temporary = target / ('.' + name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write((source / name).read_bytes())
        os.chmod(temporary, 0o644)
        chown(temporary, 1000, 1000)
        os.replace(temporary, path)
    return target


def configure(config, path=CONTAINER_PATH):
    plugins = dict(config.get('plugins') or {})
    load = dict(plugins.get('load') or {})
    load['paths'] = list(dict.fromkeys([*(load.get('paths') or []), str(path)]))
    plugins['load'] = load
    entries = dict(plugins.get('entries') or {})
    entries[PLUGIN_ID] = {**(entries.get(PLUGIN_ID) or {}), 'enabled': True}
    plugins['entries'] = entries
    if 'allow' in plugins:
        plugins['allow'] = list(dict.fromkeys([*plugins['allow'], PLUGIN_ID]))
    return {**config, 'plugins': plugins}
