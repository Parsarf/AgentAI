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


class CellProvisioner:
    """prepare(binding)->extra create argv (issues the key); finish(binding) patches the config."""

    def __init__(self, keys, secrets, cell_state_root, *, max_budget_usd=25, duration_days=35, chown=os.chown):
        self.keys, self.secrets, self.root = keys, secrets, Path(cell_state_root)
        self.max_budget_usd, self.duration_days, self.chown = max_budget_usd, duration_days, chown

    def prepare(self, binding):
        self.keys.issue(binding.tenant_ref, binding.account_id, max_budget_usd=self.max_budget_usd,
                        duration_days=self.duration_days, models=list(MODELS))
        key = self.secrets.provider_key(binding.tenant_ref)
        if key is None:
            raise RuntimeError('provider key missing after issuance')
        return ['--env', 'LITELLM_API_KEY=' + key]

    def finish(self, binding):
        path = self.root / binding.tenant_ref / 'openclaw.json'
        config = patch(json.loads(path.read_text()))
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(config, indent=2))
        os.chmod(tmp, 0o600)
        self.chown(tmp, CELL_UID, CELL_GID)
        os.replace(tmp, path)
