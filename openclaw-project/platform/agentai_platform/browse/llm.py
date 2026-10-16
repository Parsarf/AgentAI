"""Model calls for the browse agent through the account's own LiteLLM virtual key (the same key that caps the assistant)."""
from __future__ import annotations
import json
import urllib.request

MODELS = {'haiku': 'claude-haiku-4-5', 'sonnet': 'claude-sonnet-4-6'}
# USD per million tokens (input, output). ESTIMATES used only to gate spending before a call; real spend is read from the key.
PRICES = {'haiku': (1.0, 5.0), 'sonnet': (3.0, 15.0)}
PRICE_VERSION = 'browse-estimate-2026-10-13'
MAX_CALL_ESTIMATE = {'haiku': 9000, 'sonnet': 30000}       # micro-USD upper bound of one call (about 6k tokens in, 600 out)


def estimate_microusd(tier, tokens_in, tokens_out):
    pin, pout = PRICES[tier]
    return int(round(tokens_in * pin + tokens_out * pout))   # tokens x $/Mtok = micro-USD


class LiteLLM:
    def __init__(self, key, base='http://127.0.0.1:4000', opener=urllib.request.urlopen, timeout=60):
        self.key, self.base, self.opener, self.timeout = key, base.rstrip('/'), opener, timeout

    def __call__(self, tier, system, user):
        body = {'model': MODELS[tier], 'max_tokens': 600, 'temperature': 0,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        req = urllib.request.Request(self.base + '/v1/chat/completions', data=json.dumps(body).encode(), method='POST',
                                     headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        with self.opener(req, timeout=self.timeout) as response:
            data = json.load(response)
        choice = data['choices'][0]
        text = (choice['message'].get('content') or '')
        usage = data.get('usage') or {}
        return {'text': text, 'finish': choice.get('finish_reason'),    # 'length' = cut off at max_tokens
                'cost_microusd': estimate_microusd(tier, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0))}
