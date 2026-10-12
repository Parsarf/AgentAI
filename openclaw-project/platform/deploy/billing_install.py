#!/usr/bin/env python3
"""Check (and with --apply, install) the Stripe TEST configuration for hosted billing.

Reads STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID and STRIPE_API_VERSION from the private
openclaw-project/.env. Dry-run by default: it reports which checks pass without printing any value.
It refuses anything that is not a TEST key, writes secrets only as 0600 files owned by the app user,
and records the owner-switch facts it has actually verified. It never touches live mode.
"""
import json
import re
import sys

TEST_KEY = re.compile(r'(sk|rk)_test_[A-Za-z0-9]{8,}')
WEBHOOK_SECRET = re.compile(r'whsec_[A-Za-z0-9]{16,}')
PRICE = re.compile(r'price_[A-Za-z0-9]{6,}')
VERSION = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(\.[a-z]+)?')
WEBHOOK_URL = 'https://backend.getlumina.pro/v1/billing/webhook'


def check_values(values, required_events):
    """Return (problems, facts). Facts are only the ones this script can verify itself."""
    problems, facts = [], {}
    key, secret, price, version = (values.get(k, '') for k in ('STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRET', 'STRIPE_PRICE_ID', 'STRIPE_API_VERSION'))
    if key.startswith(('sk_live_', 'rk_live_')): problems.append('STRIPE_SECRET_KEY is a LIVE key; live mode is not authorized')
    elif not TEST_KEY.fullmatch(key): problems.append('STRIPE_SECRET_KEY must be a Stripe test key (sk_test_… or rk_test_…)')
    else: facts['stripe_test_keys_present'] = True
    if not WEBHOOK_SECRET.fullmatch(secret): problems.append('STRIPE_WEBHOOK_SECRET must be the whsec_… signing secret')
    else: facts['webhook_secret_present'] = True
    if not PRICE.fullmatch(price): problems.append('STRIPE_PRICE_ID must be the price_… of the $79/month test price')
    else: facts['stripe_price_configured'] = True
    if not VERSION.fullmatch(version): problems.append('STRIPE_API_VERSION must be a pinned Stripe API version such as 2025-09-30.clover')
    return problems, facts


def endpoint_registered(endpoints, required_events, url=WEBHOOK_URL):
    """True only if an enabled endpoint at our URL subscribes to every required event."""
    for endpoint in endpoints:
        if endpoint.get('url') == url and endpoint.get('status') == 'enabled':
            enabled = set(endpoint.get('enabled_events') or [])
            if '*' in enabled or set(required_events) <= enabled:
                return True
    return False


def account_env_lines(paths, price, version):
    return {'AGENTAI_BILLING_SECRET_KEY_FILE': paths['key'], 'AGENTAI_BILLING_WEBHOOK_SECRET_FILE': paths['secret'],
            'AGENTAI_BILLING_PLAN_FILE': paths['plan'], 'AGENTAI_BILLING_PRICE_ID': price, 'AGENTAI_BILLING_API_VERSION': version}


def merge_env(text, updates):
    """Idempotently set KEY=value lines in an env file's text, preserving everything else."""
    seen, out = set(), []
    for line in text.splitlines():
        name = line.split('=', 1)[0]
        if name in updates:
            if name not in seen: out.append(f'{name}={updates[name]}')
            seen.add(name)
        else:
            out.append(line)
    out += [f'{k}={v}' for k, v in updates.items() if k not in seen]
    return '\n'.join(out) + '\n'


REMOTE_DIR = '/var/lib/agentai-platform/billing'   # /etc/agentai-platform is root-only (0700), the app user cannot reach it
PLAN_PATH = '/opt/agentai-platform/billing-plan.json'
ENV_FILE = '/etc/agentai-platform/accounts.env'
FACTS_FILE = '/opt/openclaw-production/feature-switches/facts.json'


def apply_steps(local, price, version):
    """Ordered remote steps. `local` maps names to local temp files holding the secrets; nothing secret is in argv."""
    paths = {'key': REMOTE_DIR + '/secret_key', 'secret': REMOTE_DIR + '/webhook_secrets', 'plan': PLAN_PATH}
    steps = [('ssh', f'install -d -m700 -o agentai-platform -g agentai-platform {REMOTE_DIR}')]
    for name in ('key', 'secret'):   # secrets: readable by the app user only
        steps.append(('scp', local[name], f'/root/.billing-{name}.tmp'))
        steps.append(('ssh', f'install -m600 -o agentai-platform -g agentai-platform /root/.billing-{name}.tmp {paths[name]} && shred -u /root/.billing-{name}.tmp'))
    steps.append(('scp', local['plan'], '/root/.billing-plan.tmp'))   # the approved plan is not secret
    steps.append(('ssh', f'install -m644 -o root -g root /root/.billing-plan.tmp {paths["plan"]} && rm -f /root/.billing-plan.tmp'))
    return paths, steps


def merge_script(updates, facts, env_file=ENV_FILE, facts_file=FACTS_FILE):
    """A stdlib-only remote script: merge KEY=value settings and owner-switch facts, keeping modes."""
    import inspect
    return ("import json, os\n" + inspect.getsource(merge_env) + "\n"
            f"ENV, FACTS = {env_file!r}, {facts_file!r}\n"
            f"updates, new_facts = json.loads({json.dumps(json.dumps(updates))}), json.loads({json.dumps(json.dumps(facts))})\n"
            "text = open(ENV).read() if os.path.exists(ENV) else ''\n"
            "mode = os.stat(ENV).st_mode & 0o777 if os.path.exists(ENV) else 0o600\n"
            "open(ENV, 'w').write(merge_env(text, updates)); os.chmod(ENV, mode)\n"
            "current = json.load(open(FACTS)) if os.path.exists(FACTS) else {}\n"
            "current.update(new_facts)\n"
            "tmp = FACTS + '.new'; open(tmp, 'w').write(json.dumps(current, indent=2) + '\\n'); os.replace(tmp, FACTS)\n")


def main(argv, *, env_path=None, run=None):
    import os
    import subprocess
    import tempfile
    from pathlib import Path
    here = Path(__file__).resolve()
    repo = here.parents[3]
    sys.path.insert(0, str(here.parents[1]))
    from dotenv import dotenv_values
    from agentai_platform.billing import REQUIRED_EVENTS, StripeHttp, ProviderRejected, ProviderUnavailable, BillingNotConfigured
    apply = '--apply' in argv
    values = dotenv_values(env_path or repo / 'openclaw-project' / '.env')
    problems, facts = check_values(values, REQUIRED_EVENTS)
    for problem in problems:
        print('PROBLEM:', problem)
    if problems:
        print('Nothing was checked or changed. Fix .env and run again.')
        return 1
    api = StripeHttp(lambda: values['STRIPE_SECRET_KEY'], values['STRIPE_API_VERSION'])
    try:
        price = api.call('GET', f"/v1/prices/{values['STRIPE_PRICE_ID']}")
        ok_price = (price.get('active') is True and price.get('currency') == 'usd' and price.get('unit_amount') == 7900
                    and (price.get('recurring') or {}).get('interval') == 'month' and (price.get('recurring') or {}).get('interval_count') == 1
                    and price.get('livemode') is False)
        endpoints = api.call('GET', '/v1/webhook_endpoints', {'limit': 100}).get('data', [])
    except (ProviderRejected, ProviderUnavailable, BillingNotConfigured) as exc:
        print('PROBLEM: could not read from Stripe test mode:', type(exc).__name__)
        return 1
    print('price is the active $79/month USD test price:', 'yes' if ok_price else 'NO')
    if ok_price is not True:
        facts.pop('stripe_price_configured', None)
    registered = endpoint_registered(endpoints, REQUIRED_EVENTS)
    print('webhook endpoint registered at', WEBHOOK_URL, 'with every required event:', 'yes' if registered else 'NO')
    if registered:
        facts['webhook_endpoint_registered'] = True
    print('facts that would be recorded:', ', '.join(sorted(facts)) or 'none')
    if not apply:
        print('Dry run only. Run again with --apply to install the files on the server.')
        return 0
    runner = run or subprocess.run
    helper = lambda name: str(repo / 'openclaw-project' / 'bin' / name)
    with tempfile.TemporaryDirectory() as tmp:
        local = {}
        for name, content in (('key', values['STRIPE_SECRET_KEY']), ('secret', values['STRIPE_WEBHOOK_SECRET']),
                              ('plan', (repo / 'product' / 'plan.json').read_text())):
            path = os.path.join(tmp, name)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle: handle.write(content.strip() + '\n')
            local[name] = path
        paths, steps = apply_steps(local, values['STRIPE_PRICE_ID'], values['STRIPE_API_VERSION'])
        for step in steps:
            command = [sys.executable, helper('ssh-server'), step[1]] if step[0] == 'ssh' else [sys.executable, helper('scp-server'), step[1], step[2]]
            if runner(command).returncode != 0:
                print('PROBLEM: a remote step failed; stopping. Secrets staged on the server were not activated.')
                return 1
        updates = account_env_lines(paths, values['STRIPE_PRICE_ID'], values['STRIPE_API_VERSION'])
        merge = os.path.join(tmp, 'merge.py')
        Path(merge).write_text(merge_script(updates, facts))
        for command in ([sys.executable, helper('scp-server'), merge, '/root/.billing-merge.py'],
                        [sys.executable, helper('ssh-server'), 'python3 /root/.billing-merge.py && rm -f /root/.billing-merge.py']):
            if runner(command).returncode != 0:
                print('PROBLEM: merging server settings failed; files are staged but settings were not changed.')
                return 1
    print('Installed. Restart the app (systemctl restart agentai-platform-app) and enable the billing worker timer when ready.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
