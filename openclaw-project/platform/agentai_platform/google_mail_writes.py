"""Sending and organizing Gmail through the action pipeline (roadmap Phase 6, #66, #67, #D6). Nothing here is called by a model: an approved action (the customer's own
press, or their approval of exactly what the assistant prepared) is executed by the action runner (actions.py), once.

Sending (#66). Only a Lumina draft is sent, at most once. Its message carries a Message-ID made from the draft (and the same value in an `X-Lumina-Draft` header), so before
anything is sent, and whenever an answer was lost, Sent is searched for it: a send that already happened is found, never repeated. A sent message cannot be taken back;
the registered compensation is a correction to the same people, prepared and approved like any other change.

Organizing (#67). Labels, archive, star, read or unread, and the bin (never a permanent deletion), on up to 100 conversations at once. What each conversation looked like
before is read first, so one undo puts every one of them back as it was. Each change is idempotent at Gmail (adding a label it already has does nothing), so a retry after a
lost answer is safe; a lost answer is settled by reading the conversations back.

Words, not provider ids, cross the boundary: 'inbox', 'starred', 'unread', and 'label:<id>' for the customer's own labels (the id is the provider's, as listed to them).
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import quote

from .connector_kit import ProviderError, Unanswered, WriteKind, record

GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me'
MAX_RECIPIENTS = 50                    # the platform's ceiling on people a message goes to (the customer and their organization may set a lower one)
MAX_PER_HOUR = 30                      # the platform's ceiling on messages an account sends in an hour
MAX_THREADS = 100                      # conversations one organizing change may touch
ADDRESS = re.compile(r'[^@\s<>",;]{1,64}@[^@\s<>",;]{1,255}')
WORDS = {'inbox': 'INBOX', 'starred': 'STARRED', 'unread': 'UNREAD'}
LABEL = re.compile(r'label:[A-Za-z0-9_\-]{1,200}')
WEEK = 7 * 86400

WRITE_KINDS = (
    WriteKind('mail.send', 'Send an email', policy_kind='send', capability='send', compensations=('mail.send',),
              irreversible_reason='A sent email cannot be taken back. A correction can be sent to the same people.'),
    WriteKind('mail.organize', 'Organize mail', policy_kind='write', undo='mail.organize', capability='organize', undo_seconds=WEEK),
    WriteKind('mail.mark', 'Mark mail read or unread', policy_kind='write', undo='mail.mark', capability='mark_read', undo_seconds=WEEK),
    WriteKind('mail.trash', 'Move mail to the bin', policy_kind='delete', undo='mail.untrash', capability='organize', undo_seconds=WEEK),
    WriteKind('mail.untrash', 'Take mail out of the bin', policy_kind='write', undo='mail.trash', capability='organize', undo_seconds=WEEK),
)
KINDS = {k.name for k in WRITE_KINDS}


def marker(draft_id: str) -> str:
    """The Message-ID a draft's message gets: the same for every attempt, so Sent can be searched for it."""
    return 'lumina.' + hashlib.sha256(str(draft_id).encode()).hexdigest()[:40] + '@getlumina.pro'


def recipients(payload) -> list:
    return [a.strip().lower() for a in list(payload.get('to') or []) + list(payload.get('cc') or [])]


def provider_label(word: str) -> str:
    return WORDS[word] if word in WORDS else word[len('label:'):]


def word_of(label_id: str) -> str:
    return {v: k for k, v in WORDS.items()}.get(label_id) or 'label:' + label_id


def _addresses_ok(value) -> bool:
    return isinstance(value, list) and all(isinstance(a, str) and ADDRESS.fullmatch(a.strip()) for a in value)


def check(kind, payload):
    """Is this a well-formed change of this kind? Raises ValueError with a fixed sentence. Called when the change is proposed, long before anything is sent."""
    if not isinstance(payload, dict):
        raise ValueError('invalid request for this kind of change')
    text = lambda key, most, least=1: isinstance(payload.get(key), str) and least <= len(payload[key]) <= most
    if kind == 'mail.send':
        if set(payload) - {'draft', 'from', 'to', 'cc', 'subject', 'body', 'thread', 'reply_to', 'notes'} or not text('draft', 80) or not text('from', 320) \
                or not ADDRESS.fullmatch(payload['from'].strip()):
            raise ValueError('invalid request for this kind of change')
        if not _addresses_ok(payload.get('to', [])) or not _addresses_ok(payload.get('cc', [])):
            raise ValueError('recipients are email addresses')
        people = recipients(payload)
        if not people or len(people) > MAX_RECIPIENTS or len(set(people)) != len(people):
            raise ValueError(f'a message goes to 1 to {MAX_RECIPIENTS} different people')
        if not text('subject', 500, 0) or not text('body', 40000, 0) or not (payload['subject'].strip() or payload['body'].strip()):
            raise ValueError('a message needs a subject or some text')
        if ('thread' in payload and not text('thread', 300)) or ('reply_to' in payload and not text('reply_to', 300)):
            raise ValueError('invalid request for this kind of change')
        notes = payload.get('notes', [])
        if not isinstance(notes, list) or len(notes) > 10 or any(not isinstance(n, str) or len(n) > 300 for n in notes):
            raise ValueError('invalid request for this kind of change')
        return
    if kind in ('mail.organize', 'mail.mark'):
        changes = payload.get('changes')
        if set(payload) - {'changes'} or not isinstance(changes, list) or not 1 <= len(changes) <= MAX_THREADS:
            raise ValueError(f'an organizing change touches 1 to {MAX_THREADS} conversations')
        allowed = (lambda w: w == 'unread') if kind == 'mail.mark' else (lambda w: w in ('inbox', 'starred') or bool(LABEL.fullmatch(w)))
        seen = set()
        for c in changes:
            if not isinstance(c, dict) or set(c) - {'thread', 'add', 'remove'} or not isinstance(c.get('thread'), str) or not 1 <= len(c['thread']) <= 300 or c['thread'] in seen:
                raise ValueError('invalid request for this kind of change')
            seen.add(c['thread'])
            add, remove = c.get('add', []), c.get('remove', [])
            if not isinstance(add, list) or not isinstance(remove, list) or not (add or remove) or set(add) & set(remove) \
                    or any(not isinstance(w, str) or not allowed(w) for w in add + remove) or len(add) + len(remove) > 10:
                raise ValueError('invalid request for this kind of change')
        return
    if kind in ('mail.trash', 'mail.untrash'):
        threads = payload.get('threads')
        if set(payload) - {'threads'} or not isinstance(threads, list) or not 1 <= len(threads) <= MAX_THREADS \
                or any(not isinstance(t, str) or not 1 <= len(t) <= 300 for t in threads) or len(set(threads)) != len(threads):
            raise ValueError(f'the bin takes 1 to {MAX_THREADS} conversations at once')
        return
    raise ValueError('invalid request for this kind of change')


def _threads_of(kind, payload) -> list:
    return list(payload['threads']) if kind in ('mail.trash', 'mail.untrash') else [c['thread'] for c in payload['changes']]


def _label_words(word, names) -> str:
    return {'inbox': 'Inbox', 'starred': 'Starred', 'unread': 'Unread'}.get(word) or names.get(word, word[len('label:'):])


def preview(kind, payload, before):
    """What the customer is shown: built only from the payload that will be sent and the conversations as they are now."""
    if kind == 'mail.send':
        people = recipients(payload)
        changes = [{'field': 'from', 'before': None, 'after': payload['from']}, {'field': 'to', 'before': None, 'after': ', '.join(payload.get('to') or []) or None}]
        if payload.get('cc'):
            changes.append({'field': 'copy', 'before': None, 'after': ', '.join(payload['cc'])})
        changes += [{'field': 'subject', 'before': None, 'after': payload['subject'] or '(no subject)'}, {'field': 'message', 'before': None, 'after': payload['body']},
                    {'field': 'conversation', 'before': None, 'after': 'A reply in the existing conversation' if payload.get('thread') else 'A new conversation'},
                    {'field': 'attachments', 'before': None, 'after': 'None'}]
        changes += [{'field': 'check', 'before': None, 'after': note} for note in payload.get('notes') or []]
        return {'destination': f'Mail from {payload["from"]}', 'summary': f'Send "{payload["subject"] or "(no subject)"}" to {len(people)} {"person" if len(people) == 1 else "people"}',
                'affected': 1, 'changes': changes}
    data = ((before or {}).get('data') or {}).get('threads') or {}
    threads = _threads_of(kind, payload)
    subjects = [data.get(t, {}).get('subject') or '(no subject)' for t in threads]
    n = len(threads)
    noun = f'{n} {"conversation" if n == 1 else "conversations"}'
    if kind in ('mail.trash', 'mail.untrash'):
        verb = 'Move' if kind == 'mail.trash' else 'Take'
        summary = f'{verb} {noun} {"to the bin" if kind == "mail.trash" else "out of the bin"}'
    else:
        adds = sorted({w for c in payload['changes'] for w in c.get('add', [])})
        removes = sorted({w for c in payload['changes'] for w in c.get('remove', [])})
        names = ((before or {}).get('data') or {}).get('label_names') or {}
        if kind == 'mail.mark':
            summary = f'Mark {noun} as {"unread" if adds else "read"}'
        elif removes == ['inbox'] and not adds:
            summary = f'Archive {noun}'
        elif adds == ['inbox'] and not removes:
            summary = f'Move {noun} back to the inbox'
        elif adds == ['starred'] and not removes:
            summary = f'Star {noun}'
        elif removes == ['starred'] and not adds:
            summary = f'Remove the star from {noun}'
        else:
            parts = ([f'add {", ".join(_label_words(w, names) for w in adds)}'] if adds else []) + ([f'remove {", ".join(_label_words(w, names) for w in removes)}'] if removes else [])
            summary = f'{" and ".join(parts).capitalize()} on {noun}'
    changes = [{'field': 'conversations', 'before': None, 'after': n}, {'field': 'sample', 'before': None, 'after': '; '.join(subjects[:5])}]
    if n > 5:
        changes.append({'field': 'all', 'before': None, 'after': '; '.join(subjects)})
    return {'destination': 'Mail', 'summary': summary, 'affected': n, 'changes': changes}


def undo_payload(kind, payload, before):
    """What the inverse needs, taken BEFORE the forward change from each conversation as it was: only what this change really altered is put back."""
    if kind == 'mail.send':
        return None
    data = ((before or {}).get('data') or {}).get('threads') or {}
    if kind in ('mail.trash', 'mail.untrash'):
        inside = lambda t: 'TRASH' in (data.get(t, {}).get('labels') or [])
        threads = [t for t in payload['threads'] if inside(t) == (kind == 'mail.untrash')]     # only those this change moves
        return {'threads': threads} if threads else None
    changes = []
    for c in payload['changes']:
        had = set(data.get(c['thread'], {}).get('labels') or [])
        add = [w for w in c.get('remove', []) if provider_label(w) in had]
        remove = [w for w in c.get('add', []) if provider_label(w) not in had]
        if add or remove:
            changes.append({'thread': c['thread'], **({'add': add} if add else {}), **({'remove': remove} if remove else {})})
    return {'changes': changes} if changes else None


def undo_after(kind, undo, result):
    return undo


def compensation_payload(kind, compensation, payload, result):
    """A sent message is made up for by a correction to the same people, in the same conversation. Prepared and approved like any other message."""
    if kind != 'mail.send' or compensation != 'mail.send' or not result:
        return None
    sent = (result.get('record') or {}).get('data') or {}
    out = {'draft': 'correction:' + str(payload['draft'])[:60], 'from': payload['from'], 'to': list(payload.get('to') or []), 'cc': list(payload.get('cc') or []),
           'subject': ('Correction: ' + (payload.get('subject') or ''))[:500], 'body': 'Please disregard my previous message.'}
    if sent.get('thread'):
        out['thread'] = sent['thread']
    if (result.get('record') or {}).get('id'):
        out['reply_to'] = result['record']['id']
    return out


def verify(kind, payload, found):
    """After a change: does what Gmail holds now match what was sent? -> (matches, a short fixed note)."""
    if found is None:
        return False, 'it could not be read back'
    data = found.get('data') or {}
    if kind == 'mail.send':
        sent = 'SENT' in (data.get('labels') or []) and sorted(data.get('recipients') or []) == sorted(recipients(payload))
        return sent, 'it is in Sent, to exactly those people' if sent else 'what is in Sent differs from what was sent'
    threads = data.get('threads') or {}
    ok = _applied(kind, payload, threads)
    return ok, 'every conversation shows the change' if ok else 'some conversations do not show the change'


def _applied(kind, payload, threads) -> bool:
    if kind in ('mail.trash', 'mail.untrash'):
        return all(('TRASH' in (threads.get(t, {}).get('labels') or [])) == (kind == 'mail.trash') for t in payload['threads'])
    for c in payload['changes']:
        labels = set(threads.get(c['thread'], {}).get('labels') or [])
        if any(provider_label(w) not in labels for w in c.get('add', [])) or any(provider_label(w) in labels for w in c.get('remove', [])):
            return False
    return True


def mime(payload, draft_id, references=None) -> str:
    """The message as Gmail takes it (base64url of RFC 5322). Plain text. The Message-ID comes from the draft, so every attempt is the same message."""
    message = EmailMessage()
    message['From'] = payload['from']
    if payload.get('to'):
        message['To'] = ', '.join(payload['to'])
    if payload.get('cc'):
        message['Cc'] = ', '.join(payload['cc'])
    message['Subject'] = payload.get('subject') or ''
    message['Date'] = formatdate(localtime=False, usegmt=True)
    message['Message-ID'] = f'<{marker(draft_id)}>'
    message['X-Lumina-Draft'] = marker(draft_id)
    if references:
        message['In-Reply-To'] = references[-1]
        message['References'] = ' '.join(references)
    message.set_content(payload.get('body') or '')
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class MailWrites:
    """Mixed into GoogleAdapter: `self._get(credential, url)`, `self._send(...)` and `self.http` are the adapter's."""

    def _post(self, credential, url, body=None):
        status, headers, raw = self._send(credential, 'POST', url, body if body is not None else {})
        if status not in (200, 204):
            from .google_hub import _failure
            raise _failure(status, headers, raw)
        return json.loads(raw or b'{}') if raw else {}

    def _thread_state(self, credential, thread_id):
        """A conversation as it is now: the labels of all its messages together, and its subject. None when it is gone."""
        try:
            raw = self._get(credential, f'{GMAIL}/threads/{quote(thread_id, safe="")}', [('format', 'metadata'), ('metadataHeaders', 'Subject')])
        except ProviderError as error:
            if error.status in (404, 410):
                return None
            raise
        messages = raw.get('messages') or []
        labels = sorted({str(l) for m in messages for l in m.get('labelIds') or []})
        subject = next((h.get('value', '') for m in messages[:1] for h in (m.get('payload') or {}).get('headers') or [] if str(h.get('name', '')).lower() == 'subject'), '')
        return {'labels': labels, 'subject': subject[:200], 'messages': len(messages)}

    def _sent_with(self, credential, draft_id, subject=''):
        """The message this draft became, if it was ever sent: found by its Message-ID, or by its X-Lumina-Draft header among recent sent mail. None when it was not."""
        mark = marker(draft_id)
        found = self._get(credential, f'{GMAIL}/messages', [('q', f'rfc822msgid:{mark}'), ('includeSpamTrash', 'true'), ('maxResults', '5')]).get('messages') or []
        candidates = [m['id'] for m in found if m.get('id')]
        if not candidates:
            query = 'in:sent newer_than:7d' + (f' subject:"{subject[:80]}"' if subject.strip() and '"' not in subject else '')
            candidates = [m['id'] for m in (self._get(credential, f'{GMAIL}/messages', [('q', query), ('maxResults', '20')]).get('messages') or []) if m.get('id')]
        for mid in candidates[:20]:
            raw = self._get(credential, f'{GMAIL}/messages/{quote(mid, safe="")}', [('format', 'metadata'), ('metadataHeaders', 'X-Lumina-Draft'), ('metadataHeaders', 'Message-ID'),
                                                                                  ('metadataHeaders', 'To'), ('metadataHeaders', 'Cc')])
            heads = {str(h.get('name', '')).lower(): str(h.get('value', '')) for h in (raw.get('payload') or {}).get('headers') or []}
            if heads.get('x-lumina-draft') == mark or heads.get('message-id', '').strip('<>') == mark:
                return raw
        return None

    @staticmethod
    def _message_record(raw):
        from .google_hub import _addresses
        heads = {str(h.get('name', '')).lower(): str(h.get('value', '')) for h in (raw.get('payload') or {}).get('headers') or []}
        people = [p['address'].lower() for p in _addresses(heads.get('to', '')) + _addresses(heads.get('cc', '')) if p.get('address')]
        return record('message', raw['id'], container=('mail', 'all'), data={'labels': [str(l) for l in raw.get('labelIds') or []], 'recipients': people,
                                                                            'thread': raw.get('threadId')})

    def _mail_read(self, credential, record_kind, record_id):
        if record_kind == 'message':
            try:
                raw = self._get(credential, f'{GMAIL}/messages/{quote(record_id, safe="")}', [('format', 'metadata'), ('metadataHeaders', 'To'), ('metadataHeaders', 'Cc')])
            except ProviderError as error:
                if error.status in (404, 410):
                    return None
                raise
            return self._message_record(raw)
        if record_kind == 'threads':
            ids = [t for t in str(record_id).split(',') if t][:MAX_THREADS]
            states = {t: self._thread_state(credential, t) for t in ids}
            labels = self._get(credential, f'{GMAIL}/labels').get('labels') or []
            names = {word_of(str(l['id'])): l.get('name') or l['id'] for l in labels if isinstance(l, dict) and l.get('id') and l.get('type') == 'user'}
            return record('threads', record_id, container=('mail', 'all'), data={'threads': {t: s for t, s in states.items() if s is not None}, 'label_names': names})
        return None

    def _mail_write(self, credential, kind, payload, *, idempotency_key=None, precondition=None):
        if kind == 'mail.send':
            draft = payload['draft']
            already = self._sent_with(credential, draft, payload.get('subject') or '')   # sent before (a retry, or a second action for the same draft): never again
            if already is not None:
                return {'receipt': f'gmail-message-{already["id"]}', 'record': self._message_record(already)}
            references = []
            if payload.get('reply_to'):
                try:
                    original = self._get(credential, f'{GMAIL}/messages/{quote(payload["reply_to"], safe="")}',
                                         [('format', 'metadata'), ('metadataHeaders', 'Message-ID'), ('metadataHeaders', 'References')])
                    heads = {str(h.get('name', '')).lower(): str(h.get('value', '')) for h in (original.get('payload') or {}).get('headers') or []}
                    references = [r for r in heads.get('references', '').split() if r][-10:] + ([heads['message-id']] if heads.get('message-id') else [])
                except ProviderError:
                    references = []
            body = {'raw': mime(payload, draft, references or None)}
            if payload.get('thread'):
                body['threadId'] = payload['thread']
            sent = self._post(credential, f'{GMAIL}/messages/send', body)
            raw = self._get(credential, f'{GMAIL}/messages/{quote(sent["id"], safe="")}', [('format', 'metadata'), ('metadataHeaders', 'To'), ('metadataHeaders', 'Cc')])
            return {'receipt': f'gmail-message-{sent["id"]}', 'record': self._message_record(raw)}
        if kind in ('mail.organize', 'mail.mark'):
            for c in payload['changes']:
                self._post(credential, f'{GMAIL}/threads/{quote(c["thread"], safe="")}/modify', {'addLabelIds': [provider_label(w) for w in c.get('add', [])],
                                                                                                'removeLabelIds': [provider_label(w) for w in c.get('remove', [])]})
            ids = ','.join(sorted(c['thread'] for c in payload['changes']))
            return {'receipt': f'gmail-threads-{len(payload["changes"])}-{kind.split(".")[1]}', 'record': record('threads', ids, container=('mail', 'all'))}
        if kind in ('mail.trash', 'mail.untrash'):
            verb = 'trash' if kind == 'mail.trash' else 'untrash'
            for t in payload['threads']:
                self._post(credential, f'{GMAIL}/threads/{quote(t, safe="")}/{verb}')
            return {'receipt': f'gmail-threads-{len(payload["threads"])}-{verb}', 'record': record('threads', ','.join(sorted(payload['threads'])), container=('mail', 'all'))}
        raise ProviderError(400, 'invalid')

    def _mail_find(self, credential, kind, payload, idempotency_key):
        """A change whose answer never came: did it happen? A send is looked for in Sent by its draft's marker; organizing by reading the conversations back."""
        if kind == 'mail.send':
            found = self._sent_with(credential, payload['draft'], payload.get('subject') or '')
            return {'receipt': f'gmail-message-{found["id"]}', 'record': self._message_record(found)} if found else None
        threads = {t: self._thread_state(credential, t) for t in _threads_of(kind, payload)}
        if _applied(kind, payload, {t: s for t, s in threads.items() if s}):
            ids = ','.join(sorted(_threads_of(kind, payload)))
            return {'receipt': f'gmail-threads-{len(threads)}-{kind.split(".")[1]}', 'record': record('threads', ids, container=('mail', 'all'))}
        return None
