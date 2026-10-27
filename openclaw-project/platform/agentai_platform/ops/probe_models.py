"""Which models does the model gateway accept for this key, and what does it report back? A human runs this on the server; nothing calls it automatically.

    python -m agentai_platform.ops.probe_models --key-file /path/to/key [--base http://127.0.0.1:4000] [--model claude-sonnet-5-5 ...]

One tiny request per model (max_tokens 8, the word "ok"). It prints, per model: accepted or refused, the HTTP status, the model name the gateway says answered, the
names of the usage fields it returned (cached-token fields matter for cost work) and the token counts. It never prints the key, the
reply text or an error body beyond a short code.
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.error
import urllib.request

from ..lifecycle.cell_config import MODELS


def _read_key(path):
    with open(path) as handle:
        key = handle.read().strip()
    if not key:
        raise SystemExit('the key file is empty')
    return key


def probe(base, key, model, *, opener=urllib.request.urlopen, timeout=30):
    """-> a plain dict describing what happened for one model. Never raises for an HTTP or network problem."""
    body = {'model': model, 'max_tokens': 8, 'temperature': 0, 'messages': [{'role': 'user', 'content': 'Reply with the single word: ok'}]}
    req = urllib.request.Request(base.rstrip('/') + '/v1/chat/completions', data=json.dumps(body).encode(), method='POST',
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    out = {'model': model, 'accepted': False, 'status': None, 'answered_by': None, 'usage_fields': [], 'tokens': {}, 'error': ''}
    try:
        with opener(req, timeout=timeout) as response:
            out['status'] = getattr(response, 'status', 200)
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        out['status'] = exc.code
        try:
            out['error'] = str((json.load(exc).get('error') or {}).get('type') or '')[:40]
        except (ValueError, AttributeError, OSError):
            out['error'] = ''
        return out
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out['error'] = type(exc).__name__
        return out
    usage = data.get('usage') if isinstance(data, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('prompt_tokens_details') if isinstance(usage.get('prompt_tokens_details'), dict) else {}
    names = sorted(set(usage) | {f'prompt_tokens_details.{k}' for k in details})
    out.update(accepted=True, answered_by=str(data.get('model') or '')[:80], usage_fields=names,
               tokens={k: v for k, v in {**usage, **{f'prompt_tokens_details.{k}': v for k, v in details.items()}}.items() if isinstance(v, int) and not isinstance(v, bool)})
    return out


def report(results):
    lines = []
    for r in results:
        verdict = 'accepted' if r['accepted'] else 'REFUSED' if r['status'] else 'unreachable'
        cached = [n for n in r['usage_fields'] if 'cache' in n.lower() or 'cached' in n.lower()]
        lines.append(f"{r['model']}: {verdict} (HTTP {r['status']})" + (f" error={r['error']}" if r['error'] else ''))
        if r['accepted']:
            lines.append(f"  answered by: {r['answered_by']}")
            lines.append(f"  usage fields: {', '.join(r['usage_fields']) or '(none)'}")
            lines.append(f"  cached-token fields reported: {', '.join(cached) if cached else 'none'}")
            lines.append(f"  tokens: {json.dumps(r['tokens'], sort_keys=True)}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--base', default='http://127.0.0.1:4000')
    parser.add_argument('--model', action='append', help='a model id to probe (repeatable); default: every model the assistant cell allows')
    args = parser.parse_args(argv)
    key = _read_key(args.key_file)
    results = [probe(args.base, key, model) for model in (args.model or list(MODELS))]
    print(report(results))
    return 0 if all(r['accepted'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
