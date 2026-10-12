"""Host-side LiteLLM admin access: virtual-key HTTP and per-key spend. Stdlib only.

The master key is read from a root-owned file at call time and never stored,
logged or returned. Spend is the provider-side truth for what a cell used.
"""
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class LiteLLMAdmin:
    def __init__(self, env_file, base='http://127.0.0.1:4000', *, opener=urllib.request.urlopen, timeout=20):
        self.env_file, self.base, self.opener, self.timeout = Path(env_file), base.rstrip('/'), opener, timeout

    def _master(self):
        for line in self.env_file.read_text().splitlines():
            if line.startswith('LITELLM_MASTER_KEY='):
                return line.split('=', 1)[1].strip().strip('"\'')
        raise RuntimeError('model proxy master key unavailable')

    def http(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + self._master(), 'Content-Type': 'application/json'})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    def key_spend_microusd(self, key):
        status, body = self.http('GET', '/key/info?key=' + urllib.parse.quote(key, safe=''))
        spend = ((body or {}).get('info') or {}).get('spend') if status == 200 else None
        if not isinstance(spend, (int, float)) or isinstance(spend, bool) or spend < 0:
            raise RuntimeError('key spend unavailable')
        return int(round(spend * 1_000_000))
