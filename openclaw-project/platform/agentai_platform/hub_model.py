"""The provider-neutral mail and calendar model (roadmap #D1).

The rule the dashboard rests on: a screen, a tool or a workflow never knows which provider an item came from, except to show its icon. Every provider is converted to the
shapes below AT ITS ADAPTER, by pure functions, and nowhere else. Nothing in this module, in hub_sync.py or in hub.py may name a provider.

What an adapter gives (the "hub interface", beside the connector contract's own operations):

    calendars(credential) -> [calendar(...)]
    mail_changes(credential, cursor, since_epoch, labels, limit) -> Changes        labels: None = all mail, else the provider label ids the customer chose
    event_changes(credential, calendar_id, cursor, start_epoch, end_epoch, limit) -> Changes
    mail_body(credential, message_id) -> body(...)
    mail_search(credential, query, labels, position, limit) -> connector_kit.Page of message(...)      (mail older than the synced window, live)

`Changes.cursor` is the provider's own "what changed since" token, opaque to everything but its adapter. While a first fill is paging, the cursor carries the page position
and `more` is True. An adapter raises `ResyncRequired` when the provider says a cursor is no longer valid: the engine then refills the window cleanly, which is not an error.

What a provider can do is DATA (`HubCaps`), read by the dashboard and by the assistant's tools. No screen has a provider's name in a condition.

Everything a provider sends (subjects, names, addresses, snippets, bodies, event titles and descriptions) is outside content: it is cut to length and stored as data here,
and neutralized before the assistant reads it (hub.py).
"""
from __future__ import annotations
import re
from dataclasses import asdict, dataclass, field

from .connector_kit import Signal

COMMON_LABELS = ('inbox', 'sent', 'drafts', 'archive', 'spam', 'trash', 'starred', 'unread')
RESPONSES = ('accepted', 'declined', 'tentative', 'needs_action')
VISIBILITIES = ('default', 'public', 'private', 'busy')
CALENDAR_ACCESS = ('busy', 'read', 'write', 'owner')
MAIL_RESOURCES = ('mailbox', 'label')          # what a grant can name for mail: ('mailbox', '*') is all mail, ('label', <provider label id>) one label
CALENDAR_RESOURCE = 'calendar'
MAX_PEOPLE = 60
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class ResyncRequired(Signal):
    """The provider no longer accepts the cursor (it expired, or the mailbox was restored). The window is refilled from nothing."""


@dataclass(frozen=True)
class Grant:
    """A permission to change things, asked for separately and only when the customer first uses what it allows (roadmap Phase 6). The name and the capabilities are the same
    words for every provider; the scope is the provider's own."""
    name: str                          # 'calendar_write' | 'send' | 'organize'
    scope: str                         # what the provider calls it
    capabilities: tuple                # which write capabilities of HubCaps it unlocks
    words: str                         # what the customer reads before being sent to the provider


WRITE_CAPABILITIES = ('send', 'organize', 'mark_read', 'event_write', 'respond')


@dataclass(frozen=True)
class HubCaps:
    """What a provider's adapter can do for the dashboard. The screens and the tools read this; it is the only place a difference between providers lives."""
    mail: bool = False                 # has mail at all
    calendar: bool = False             # has calendars at all
    mail_search: bool = False          # can search mail older than the synced window, live
    incremental: bool = True           # has a "what changed since" cursor (False: every sync re-reads the window and compares)
    push: bool = False                 # can tell Lumina when something changed (used from Phase 7)
    labels: str = 'labels'             # 'labels' (a message can carry several) | 'folders' (a message is in one) | 'none'
    subjects: bool = True              # threads have a subject (a chat does not)
    attachments: bool = False          # an attachment's bytes can be read (the knowledge pipeline reads it on demand, #55)
    compose_link: bool = False         # the provider has a compose screen a Lumina draft can open in (#57)
    free_busy: bool = False            # the provider answers a live free/busy question across calendars (#59); without it the synced copy is used
    # Managing (Phase 6). All False until a provider's write kinds exist; the dashboard shows a control only where its capability is True.
    send: bool = False
    organize: bool = False             # archive, label or move, star, trash
    mark_read: bool = False
    event_write: bool = False          # create, change, cancel
    respond: bool = False              # answer an invitation
    grants: tuple = ()                 # Grant rows: the permissions behind the write capabilities

    def public(self) -> dict:
        out = asdict(self)
        out['grants'] = [{'name': g.name, 'capabilities': list(g.capabilities), 'words': g.words} for g in self.grants]      # the provider's scope names stay on the server
        return out

    def grant_for(self, capability):
        return next((g for g in self.grants if capability in g.capabilities), None)

    def effective(self, scopes) -> dict:
        """What this connection can do now: a write capability counts only when the provider declares it AND the connection holds the permission behind it. A screen shows a
        control only where this says True; where the provider can but the permission is missing, `missing` names the grant to ask for (re-consent)."""
        held = set(scopes or ())
        out = {k: v for k, v in self.public().items() if k != 'grants'}
        missing = {}
        for capability in WRITE_CAPABILITIES:
            grant = self.grant_for(capability)
            if out[capability] and (grant is None or grant.scope not in held):
                out[capability] = False
                if grant is not None:
                    missing[capability] = grant.name
        out['missing'] = missing
        return out


@dataclass
class Changes:
    """One page of changes for a mailbox or one calendar."""
    items: list = field(default_factory=list)      # message(...) or event(...) dicts that are new or changed
    removed: list = field(default_factory=list)    # provider ids that no longer exist (or left what was granted)
    cursor: str | None = None                      # where the next call starts
    more: bool = False                             # call again now: there is another page


def _text(value, most) -> str:
    return _CONTROL.sub('', str(value if value is not None else '')).strip()[:most]


def person(name='', address='') -> dict:
    """Someone in a message or an event. An address is kept as the provider gave it, lower-cased; a name is only ever shown, never trusted."""
    return {'name': _text(name, 200), 'address': _text(address, 320).lower()}


def _people(value) -> list:
    out = []
    for item in (value or [])[:MAX_PEOPLE]:
        if isinstance(item, dict) and (item.get('address') or item.get('name')):
            out.append(person(item.get('name', ''), item.get('address', '')))
    return out


def _labels(value) -> list:
    return sorted({str(v) for v in (value or []) if v in COMMON_LABELS})


def message(mid, thread_id, *, subject='', sender=None, to=(), cc=(), sent_epoch=0, snippet='', labels=(), provider_labels=(), has_attachments=False) -> dict:
    """One mail message as headers: what the list and the thread show before a body is opened. `labels` are from COMMON_LABELS; `provider_labels` are the provider's own
    [{'id', 'name'}], kept so the customer sees the names they know and a grant can be checked."""
    mid, thread_id = _text(mid, 300), _text(thread_id, 300) or _text(mid, 300)
    if not mid:
        raise ValueError('a message has an id')
    own = [{'id': _text(p.get('id'), 300), 'name': _text(p.get('name') or p.get('id'), 200)} for p in (provider_labels or []) if isinstance(p, dict) and p.get('id')][:50]
    marks = _labels(labels)
    return {'id': mid, 'thread_id': thread_id, 'subject': _text(subject, 500), 'sender': person(**(sender or {})) if isinstance(sender, dict) else person(),
            'to': _people(to), 'cc': _people(cc), 'sent_epoch': max(0, int(sent_epoch or 0)), 'snippet': _text(snippet, 400), 'labels': marks, 'provider_labels': own,
            'unread': 'unread' in marks, 'starred': 'starred' in marks, 'has_attachments': bool(has_attachments)}


def body(text='', html='', attachments=()) -> dict:
    """A message's content, fetched only when it is opened or read. `attachments`: [{'id', 'name', 'type', 'size'}] (names and sizes; the bytes are fetched on demand)."""
    files = [{'id': _text(a.get('id'), 500), 'name': _text(a.get('name') or 'attachment', 255), 'type': _text(a.get('type') or 'application/octet-stream', 120),
              'size': max(0, int(a.get('size') or 0))} for a in (attachments or []) if isinstance(a, dict) and a.get('id')][:100]
    return {'text': str(text or '')[:400_000], 'html': str(html or '')[:1_000_000], 'attachments': files}


def calendar(cid, *, name='', colour=None, timezone=None, access='read', primary=False) -> dict:
    cid = _text(cid, 300)
    if not cid:
        raise ValueError('a calendar has an id')
    return {'id': cid, 'name': _text(name, 200) or cid, 'colour': _text(colour, 20) or None, 'timezone': _text(timezone, 64) or None,
            'access': access if access in CALENDAR_ACCESS else 'read', 'primary': bool(primary)}


def event(eid, calendar_id, *, title='', start_epoch=0, end_epoch=0, all_day=False, start_date=None, end_date=None, timezone=None, series_id=None, place='',
          conference_url=None, organizer=None, attendees=(), my_response=None, exception=False, cancelled=False, visibility='default', version=None, description='',
          provider_url=None, updated_epoch=None) -> dict:
    """One occurrence of an event, as the provider expanded it. An all-day event keeps its dates as given (`start_date` inclusive, `end_date` exclusive, 'YYYY-MM-DD'): a
    date has no timezone, and the dashboard draws it on those dates wherever the customer is. `start_epoch`/`end_epoch` are still set (midnight UTC of those dates) so
    that range queries work. A timed event is epoch seconds, plus the event's own timezone for display."""
    eid, calendar_id = _text(eid, 400), _text(calendar_id, 300)
    if not eid or not calendar_id:
        raise ValueError('an event has an id and a calendar')
    start_epoch, end_epoch = int(start_epoch or 0), int(end_epoch or 0)
    if all_day and not (_DATE.match(str(start_date or '')) and _DATE.match(str(end_date or ''))):
        raise ValueError('an all-day event has its dates')
    if end_epoch < start_epoch:
        end_epoch = start_epoch
    people = []
    for item in (attendees or [])[:MAX_PEOPLE * 5]:
        if isinstance(item, dict) and (item.get('address') or item.get('name')):
            people.append({**person(item.get('name', ''), item.get('address', '')), 'response': item.get('response') if item.get('response') in RESPONSES else 'needs_action',
                           'self': bool(item.get('self')), 'optional': bool(item.get('optional'))})
    url = _text(conference_url, 1000)
    return {'id': eid, 'calendar_id': calendar_id, 'series_id': _text(series_id, 400) or None, 'title': _text(title, 500), 'start_epoch': start_epoch, 'end_epoch': end_epoch,
            'all_day': bool(all_day), 'start_date': str(start_date) if all_day else None, 'end_date': str(end_date) if all_day else None, 'timezone': _text(timezone, 64) or None,
            'place': _text(place, 500), 'conference_url': url if url.startswith('https://') else None,
            'organizer': person(**organizer) if isinstance(organizer, dict) and (organizer.get('address') or organizer.get('name')) else None, 'attendees': people,
            'my_response': my_response if my_response in RESPONSES else None, 'exception': bool(exception), 'cancelled': bool(cancelled),
            'visibility': visibility if visibility in VISIBILITIES else 'default', 'version': _text(version, 200) or None, 'description': str(description or '')[:8000],
            'provider_url': (_text(provider_url, 1000) if str(provider_url or '').startswith('https://') else None), 'updated_epoch': int(updated_epoch) if updated_epoch else None}


def people_text(*groups) -> str:
    """Names and addresses in one lower-case line: what a search over people matches against."""
    seen, out = set(), []
    for group in groups:
        for p in ([group] if isinstance(group, dict) else (group or [])):
            for part in (p.get('name', ''), p.get('address', '')):
                part = part.lower()
                if part and part not in seen:
                    seen.add(part); out.append(part)
    return ' '.join(out)[:4000]


def hub_caps(declaration) -> HubCaps | None:
    """A connector's dashboard capabilities, or None when it has none (it is not a mail or calendar provider)."""
    caps = getattr(declaration, 'hub', None)
    return caps if isinstance(caps, HubCaps) and (caps.mail or caps.calendar) else None
