"""Cell model-route provisioning: the virtual key and the Gateway config patch.

Applied by the host between ``fleet create`` and first start. The cell reaches
LiteLLM only through the host relay (10.77.0.1:4000) with its own per-tenant
virtual key; owner credentials are never used.
"""
import json
import os
from pathlib import Path

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

# Read by the assistant at the start of every session (OpenClaw loads AGENTS.md from the workspace). Search needs no paid
# provider: the cell can reach public search pages, and the assistant is told how to use them frugally and honestly.
WORKSPACE_RULES = '''# How you work (Lumina)

## Searching the web
You have no paid search API. To search, use the shell:

    curl -sL -m 20 -A 'Mozilla/5.0' 'https://html.duckduckgo.com/html/?q=URL+ENCODED+QUERY'

Result links have class `result__a`; the real address is the URL-decoded `uddg=` parameter. Then open the most relevant pages
(shell `curl`, or the web_fetch tool if it is available) and read only what you need.

Rules: open at most 5 pages per question; prefer the retailer's or publisher's own page; never invent prices, ratings or
availability: if a page does not show it, say so; list the page addresses you used; if a site blocks you, try a different one;
keep the final answer short and ranked when asked to rank.
'''


class CellProvisioner:
    """prepare(binding)->extra create argv (issues the key); finish(binding) patches the config;
    after_start(binding) gives the running cell working DNS."""

    def __init__(self, keys, secrets, cell_state_root, *, max_budget_usd=25, duration_days=35, chown=os.chown, run=None):
        self.keys, self.secrets, self.root = keys, secrets, Path(cell_state_root)
        self.max_budget_usd, self.duration_days, self.chown, self.run = max_budget_usd, duration_days, chown, run

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
