"""Alert routing to authorized destinations only.

Destinations and recipients come from a root-owned configuration; callers cannot name one.
Messages carry a fixed set of fields (kind, severity, one-line summary, correlation id, counts) and are
trimmed; tenant content, tenant references, tokens and paths are never accepted. Repeats are suppressed
for a cooldown so a persistent fault does not flood the owner, but a recovery is announced once.
"""
import json
import os
from pathlib import Path
import re
import smtplib
from email.message import EmailMessage
import time
import urllib.request

SEVERITIES = ('info', 'warn', 'crit')
SAFE = re.compile(r'[^\x20-\x7e]')
FORBIDDEN = re.compile(r'(aa-[a-f0-9]{32}|(sk|rk)_(test|live)_\w+|whsec_\w+|AGE-SECRET-KEY-\w+|age1[a-z0-9]{50,}|(secret|password|token|key)\s*[=:]\s*\S+)', re.I)


class AlertError(Exception): pass


def clean(text, limit=300):
    text = SAFE.sub('?', str(text))[:limit]
    return FORBIDDEN.sub('[removed]', text)


class EmailSender:
    name = 'email'

    def __init__(self, host, user, password_reader, sender, recipients, *, port=587, smtp=smtplib.SMTP):
        self.host, self.user, self.password_reader, self.sender, self.port, self.smtp = host, user, password_reader, sender, port, smtp
        self.recipients = list(recipients)
        if not self.recipients: raise AlertError('no recipients configured')

    def send(self, subject, body):
        msg = EmailMessage()
        msg['Subject'], msg['From'], msg['To'] = subject, self.sender, ', '.join(self.recipients)
        msg.set_content(body)
        with self.smtp(self.host, self.port, timeout=20) as server:
            server.starttls(); server.login(self.user, self.password_reader()); server.send_message(msg)


class TelegramSender:
    name = 'telegram'

    def __init__(self, token_reader, chat_id, *, opener=urllib.request.urlopen):
        if not str(chat_id).lstrip('-').isdigit(): raise AlertError('invalid chat id')
        self.token_reader, self.chat_id, self.opener = token_reader, str(chat_id), opener

    def send(self, subject, body):
        data = json.dumps({'chat_id': self.chat_id, 'text': f'{subject}\n{body}'[:3500]}).encode()
        request = urllib.request.Request(f'https://api.telegram.org/bot{self.token_reader()}/sendMessage', data=data,
                                         headers={'Content-Type': 'application/json'})
        with self.opener(request, timeout=15) as response:
            if response.status != 200: raise AlertError('telegram rejected the message')


class AlertRouter:
    def __init__(self, senders, state_path, *, clock=time.time, cooldown=None, journal=print):
        self.senders, self.state_path, self.clock, self.journal = list(senders), Path(state_path), clock, journal
        self.cooldown = {'info': 24 * 3600, 'warn': 6 * 3600, 'crit': 3600, **(cooldown or {})}

    def _state(self):
        try: return json.loads(self.state_path.read_text())
        except (OSError, ValueError): return {}

    def _save(self, state):
        tmp = self.state_path.with_suffix('.tmp'); tmp.write_text(json.dumps(state)); os.chmod(tmp, 0o600); os.replace(tmp, self.state_path)

    def send(self, kind, severity, summary, *, correlation_id='', counts=None):
        if severity not in SEVERITIES or not re.fullmatch(r'[a-z0-9_.-]{1,60}', kind): raise AlertError('invalid alert')
        now, state = self.clock(), self._state()
        last = state.get(kind, {})
        if last.get('severity') == severity and now - last.get('at', 0) < self.cooldown[severity]:
            self.journal(json.dumps({'alert': kind, 'severity': severity, 'delivered': False, 'reason': 'cooldown'})); return False
        subject = f'[AgentAI {severity.upper()}] {clean(kind, 60)}'
        body = '\n'.join([clean(summary), f'correlation: {clean(correlation_id, 40)}', *[f'{clean(k, 40)}: {clean(v, 40)}' for k, v in sorted((counts or {}).items())][:12]])
        delivered = []
        for sender in self.senders:
            try: sender.send(subject, body); delivered.append(sender.name)
            except Exception as exc: self.journal(json.dumps({'alert': kind, 'sender': sender.name, 'error': type(exc).__name__}))
        state[kind] = {'severity': severity, 'at': now, 'delivered': delivered}
        self._save(state)
        self.journal(json.dumps({'alert': kind, 'severity': severity, 'delivered': bool(delivered), 'senders': delivered}))
        return bool(delivered)

    def resolved(self, kind, *, correlation_id=''):
        """Announce recovery once, then forget the fault so a recurrence alerts immediately."""
        state = self._state()
        if kind not in state: return False
        del state[kind]; self._save(state)
        for sender in self.senders:
            try: sender.send(f'[AgentAI RESOLVED] {clean(kind, 60)}', f'cleared; correlation: {clean(correlation_id, 40)}')
            except Exception: pass
        return True
