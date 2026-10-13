"""Cell model-route provisioning: the virtual key and the Gateway config patch.

Applied by the host between ``fleet create`` and first start. The cell reaches
LiteLLM only through the host relay (10.77.0.1:4000) with its own per-tenant
virtual key; owner credentials are never used.
"""
import json
import os
from pathlib import Path
import time

MODELS = ('claude-sonnet-4-6', 'claude-haiku-4-5')
DEFAULT_MODEL = 'litellm/claude-haiku-4-5'
CELL_UID = CELL_GID = 1000


def patch(config, *, relay='http://10.77.0.1:4000', default_model=DEFAULT_MODEL):
    config = dict(config)
    config['models'] = {'providers': {'litellm': {
        'baseUrl': relay, 'api': 'openai-completions',
        'apiKey': {'source': 'env', 'provider': 'default', 'id': 'LITELLM_API_KEY'},
        'request': {'allowPrivateNetwork': True},
        'models': [
            {'id': 'claude-sonnet-4-6', 'name': 'Claude Sonnet 4.6', 'reasoning': True, 'input': ['text', 'image'], 'contextWindow': 200000, 'maxTokens': 4096},
            {'id': 'claude-haiku-4-5', 'name': 'Claude Haiku 4.5', 'reasoning': False, 'input': ['text', 'image'], 'contextWindow': 200000, 'maxTokens': 4096}]}}}
    config['agents'] = {'defaults': {'model': {'primary': default_model}, 'workspace': '/home/node/.openclaw/workspace',
                                     'sandbox': {'mode': 'off'}, 'heartbeat': {'every': '0m'}}}
    return config


RESOLVERS = ('1.1.1.1', '9.9.9.9')
SEARCH_PLUGIN_VERSION = '2026.9.6'   # must match the pinned runtime image

# Read by the assistant at the start of every session (OpenClaw loads AGENTS.md from the workspace). Search needs no paid
# provider: the cell can reach public search pages, and the assistant is told how to use them frugally and honestly.
WORKSPACE_RULES = '''# How you work (Lumina)

## Searching the web
Use the `web_search` tool for anything that needs current information (it returns titles, links and snippets). If tools are
listed as deferred, load `web_search` first with `tool_search`, then call it with `tool_call`. Then open the best 3 to 5 result
pages with `web_fetch` and read only what you need.

Rules: never invent prices, ratings or availability: if a page does not show it, say so; prefer the seller's or publisher's own
page; list the page addresses you used; keep the final answer short, and ranked when asked to rank. If `web_search` is
unavailable, say so plainly instead of guessing; do not scrape search-engine pages.

## Showing data as a table, chart or comparison
When the answer is mainly data (a ranking, prices, a schedule, numbers over time, a share breakdown, or 2 to 6 options to choose
between), write a short answer in plain text first, then add exactly one card as a fenced block whose language is `lumina`
containing one JSON object. Plain text only inside the JSON (no HTML or markdown). Use real facts only; leave a value out when you
do not know it. Never put secrets in a card. Shapes (schemaVersion is always "1.0"):

```lumina
{"schemaVersion":"1.0","type":"table","title":"Top paddles by price","columns":[{"id":"name","label":"Paddle"},{"id":"price","label":"Price","type":"currency","unit":"$"},{"id":"url","label":"Page","type":"link"}],"rows":[{"name":"Example","price":89.99,"url":"https://example.com/p"}],"highlightRow":0}
```
Column types: text, number, currency, percent, rating, link. Up to 12 columns and 200 rows.

```lumina
{"schemaVersion":"1.0","type":"chart","chart":"bar","title":"Monthly cost","labels":["Jan","Feb"],"series":[{"name":"Cost","values":[10,12]}],"unit":"$"}
```
Chart types: bar, line (up to 4 series), pie, donut (one series, share of a whole). Up to 40 labels.

```lumina
{"schemaVersion":"1.0","type":"comparison","title":"Which plan?","items":[{"name":"Plan A","price":"$10","badge":"Best value","facts":[{"label":"Storage","value":"1 TB"}],"pros":["Cheap"],"cons":["Slow"],"link":"https://example.com"},{"name":"Plan B"}],"bestIndex":0}
```
Use a card only when it helps; a simple answer stays plain text.
'''


class CellProvisioner:
    """prepare(binding)->extra create argv (issues the key); finish(binding) patches the config;
    after_start(binding) gives the running cell working DNS."""

    def __init__(self, keys, secrets, cell_state_root, *, max_budget_usd=25, duration_days=35, chown=os.chown, run=None, search_key_file=None,
                 sleep=time.sleep):
        self.keys, self.secrets, self.root = keys, secrets, Path(cell_state_root)
        self.max_budget_usd, self.duration_days, self.chown, self.run = max_budget_usd, duration_days, chown, run
        self.search_key_file, self.sleep = (Path(search_key_file) if search_key_file else None), sleep

    def after_start(self, binding):
        """Docker's embedded resolver (127.0.0.11) does not answer inside a gVisor sandbox, so every name lookup in
        a cell fails. Write public resolvers into the container's resolv.conf in place (the sandbox sees the same
        inode); the file is regenerated at each container start, so this runs after every start. Cell egress to
        private ranges stays dropped by the host firewall, so public resolvers do not widen what a cell can reach."""
        try:
            self.write_rules(binding)
        except OSError:
            pass   # rules are a convenience; a cell without them still works
        if self.run is None:
            return
        code, out = self.run(['docker', 'inspect', '-f', '{{.ResolvConfPath}}', f'openclaw-cell-{binding.tenant_ref}'])
        path = out.strip()
        if code != 0 or not path.startswith('/var/lib/agentai-cells/docker/containers/') or not path.endswith('/resolv.conf'):
            raise RuntimeError('cell resolver file not found')
        with open(path, 'r+') as handle:         # in place: a replaced file would not reach the running sandbox
            handle.seek(0)
            handle.write(''.join(f'nameserver {ip}\n' for ip in RESOLVERS) + 'options ndots:0\n')
            handle.truncate()

    def prepare(self, binding):
        self.keys.issue(binding.tenant_ref, binding.account_id, max_budget_usd=self.max_budget_usd,
                        duration_days=self.duration_days, models=list(MODELS))
        key = self.secrets.provider_key(binding.tenant_ref)
        if key is None:
            raise RuntimeError('provider key missing after issuance')
        return ['--env', 'LITELLM_API_KEY=' + key]

    def setup_search(self, binding, *, attempts=20):
        """Install the official Brave search plugin (pinned to the runtime's version) and give the cell the search key.

        Idempotent via a marker in the cell's own volume. The key travels on stdin, never on a command line. Needs the
        Gateway to be up, so it retries while the cell finishes starting."""
        if self.run is None or self.search_key_file is None:
            return False
        marker = self.root / binding.tenant_ref / 'workspace' / f'.search-{SEARCH_PLUGIN_VERSION}'
        if marker.exists():
            return True
        key = self.search_key_file.read_text().strip()
        if not key:
            return False
        name = f'openclaw-cell-{binding.tenant_ref}'
        cli = ['docker', 'exec', name, 'node', '/app/openclaw.mjs']
        for _ in range(attempts):
            code, _out = self.run(cli + ['plugins', 'install', f'@openclaw/brave-plugin@{SEARCH_PLUGIN_VERSION}', '--force'])
            if code == 0:
                break
            self.sleep(3)
        else:
            return False
        steps = [['config', 'set', 'tools.web.search.enabled', 'true'], ['config', 'set', 'tools.web.search.provider', 'brave']]
        for step in steps:
            if self.run(cli + step)[0] != 0:
                return False
        stdin_cmd = ['docker', 'exec', '-i', name, 'sh', '-c', 'cd /app && node openclaw.mjs config set plugins.entries.brave.config.webSearch.apiKey "$(cat | tr -d \'\\n\')"']
        if self.run(stdin_cmd, input_text=key + '\n')[0] != 0:
            return False
        marker.write_text('ok\n')
        self.chown(marker, CELL_UID, CELL_GID)
        return True

    def write_rules(self, binding):
        """Idempotent: (re)write the assistant's working rules into its workspace (the volume must be mounted)."""
        workspace = self.root / binding.tenant_ref / 'workspace'
        workspace.mkdir(exist_ok=True)
        target = workspace / 'AGENTS.md'
        if not target.exists() or target.read_text() != WORKSPACE_RULES:
            target.write_text(WORKSPACE_RULES)
        for path in (workspace, target):
            self.chown(path, CELL_UID, CELL_GID)

    def finish(self, binding):
        self.write_rules(binding)
        path = self.root / binding.tenant_ref / 'openclaw.json'
        config = patch(json.loads(path.read_text()))
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(config, indent=2))
        os.chmod(tmp, 0o600)
        self.chown(tmp, CELL_UID, CELL_GID)
        os.replace(tmp, path)
