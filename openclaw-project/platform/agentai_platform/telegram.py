"""One Telegram ingress with secure account linking (Phase 7).

Bearer link codes are stored only as SHA-256 hashes, single use, short expiry,
consumed atomically and bound to the numeric sender identity taken from the
authenticated Bot API update. One numeric identity maps to at most one account;
suspension and revocation are rechecked on every use. Updates are deduplicated
durably before routing; replies go through an outbox with recorded receipts.
Groups are not accepted. Real bot linking/reply proof belongs to Phase 15/17;
every network touchpoint is injectable and the ingress fails closed when the
bot is not configured.
"""
from __future__ import annotations
import hashlib
import json
import secrets
import time
import urllib.request
import uuid
from .adapters import CapabilityUnavailable
from .budget import BudgetDenied
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

CODE_TTL_SECONDS = 600
MAX_OUTBOUND_TEXT = 4000


def code_digest(raw: str) -> str:
    return hashlib.sha256(''.join(raw.split()).encode()).hexdigest()


class TelegramBotApi:
    """Bot API transport; the token exists only here, never in links or logs."""

    def __init__(self, token: str):
        if not token or any(c.isspace() for c in token):
            raise ValueError('invalid bot token')
        self.token = token

    def send_message(self, chat_id: str, text: str):
        body = json.dumps({'chat_id': chat_id, 'text': text[:MAX_OUTBOUND_TEXT]}).encode()
        request = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/sendMessage', data=body,
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
        if payload.get('ok') is not True:
            raise LookupError('telegram rejected message')
        message_id = payload.get('result', {}).get('message_id')
        if not isinstance(message_id, int):
            raise LookupError('telegram receipt missing')
        return message_id


class NullTransport:
    def send_message(self, chat_id: str, text: str):
        raise CapabilityUnavailable('bot not configured')


class TelegramService:
    def __init__(self, store, *, chat, transport=None, bot_username: str = '', clock=time.time):
        self.store = store
        self.chat = chat
        self.coordinator = Coordinator(store, clock=clock)
        self.clock = clock
        self.transport = transport if transport is not None else NullTransport()
        self.bot_username = bot_username.lstrip('@')

    # ---------- linking (customer side) ----------

    def create_code(self, principal: Principal):
        """Single-use bearer code; previous unconsumed codes are invalidated."""
        raw = secrets.token_urlsafe(24)
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            con.execute('''UPDATE telegram_link_codes SET consumed_epoch=? WHERE account_id=?
                AND consumed_epoch IS NULL''', (now, principal.account_id))
            code_id = uuid.uuid4().hex
            con.execute('''INSERT INTO telegram_link_codes(account_id,id,code_hash,epoch,expires_epoch,created_epoch,actor_id)
                VALUES (?,?,?,?,?,?,?)''', (principal.account_id, code_id, code_digest(raw),
                                            now, now + CODE_TTL_SECONDS, now, principal.actor_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id,
                                    code_id, 'telegram.code_create', 'completed')
        return {'expires_in': CODE_TTL_SECONDS,
                'link': f'https://t.me/{self.bot_username}?start={raw}' if self.bot_username else None}

    def bindings(self, principal: Principal):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('''SELECT chat_id,selected_project_id,created_epoch FROM telegram_links
                WHERE account_id=? ORDER BY created_epoch,chat_id''', (principal.account_id,)).fetchall()
            return [dict(row) for row in rows]

    def unlink(self, principal: Principal, chat_id: str | None):
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if chat_id:
                cursor = con.execute('DELETE FROM telegram_links WHERE account_id=? AND chat_id=?',
                                     (principal.account_id, chat_id))
            else:
                cursor = con.execute('DELETE FROM telegram_links WHERE account_id=?', (principal.account_id,))
            if cursor.rowcount < 1:
                raise NotFound('unavailable')
            self.coordinator._audit(con, principal.account_id, principal.actor_id,
                                    chat_id or 'all', 'telegram.unlink', 'completed')

    # ---------- ingress (provider side) ----------

    def _alive(self, con, account_id, actor_id):
        row = con.execute('''SELECT 1 FROM accounts a JOIN memberships m ON m.account_id=a.id
            WHERE a.id=? AND a.status='active' AND m.actor_id=? AND m.status='active'
            AND m.role='customer' ''', (account_id, actor_id)).fetchone()
        return bool(row)

    def _reply(self, con, chat_id, text, account_id=None):
        now = int(self.clock())
        reply_id = uuid.uuid4().hex
        con.execute('''INSERT INTO telegram_outbox(account_id,id,chat_id,text,state,created_epoch,updated_epoch)
            VALUES (?,?,?,?,'pending',?,?)''', (account_id, reply_id, chat_id, text[:MAX_OUTBOUND_TEXT], now, now))
        return reply_id

    def _try_send(self, chat_id, text, account_id, reply_id):
        """One bounded inline send attempt with a recorded receipt."""
        try:
            message_id = self.transport.send_message(chat_id, text)
        except CapabilityUnavailable:
            return  # stays pending for the host drain; bot not configured
        except LookupError:
            with self.coordinator.transaction() as con:
                con.execute("UPDATE telegram_outbox SET state='failed',updated_epoch=? WHERE id=?",
                            (int(self.clock()), reply_id))
            return
        except Exception:
            with self.coordinator.transaction() as con:
                con.execute("UPDATE telegram_outbox SET state='uncertain',updated_epoch=? WHERE id=?",
                            (int(self.clock()), reply_id))
            return
        with self.coordinator.transaction() as con:
            con.execute("UPDATE telegram_outbox SET state='sent',native_message_id=?,updated_epoch=? WHERE id=?",
                        (str(message_id), int(self.clock()), reply_id))

    def _flush(self, reply_id):
        with self.store.connect() as con:
            row = con.execute('SELECT id,chat_id,text,account_id FROM telegram_outbox WHERE id=?',
                              (reply_id,)).fetchone()
        if row:
            self._try_send(row['chat_id'], row['text'], row['account_id'], row['id'])

    def _flush_latest(self, chat_id):
        with self.store.connect() as con:
            row = con.execute('''SELECT id FROM telegram_outbox WHERE chat_id=? AND state='pending'
                ORDER BY created_epoch DESC,id DESC LIMIT 1''', (chat_id,)).fetchone()
        if row:
            self._flush(row['id'])

    def _dedupe(self, con, update_id):
        if type(update_id) is not int or update_id < 0:
            raise ValueError('invalid update')
        cursor = con.execute('INSERT OR IGNORE INTO telegram_updates(update_id,received_epoch) VALUES (?,?)',
                             (update_id, int(self.clock())))
        return cursor.rowcount == 1

    def _binding(self, con, chat_id):
        row = con.execute('''SELECT account_id,chat_id,telegram_user_id,actor_id,selected_project_id
            FROM telegram_links WHERE chat_id=?''', (chat_id,)).fetchone()
        return dict(row) if row else None

    def _resolve_conversation(self, binding):
        """Latest conversation with messages in the selected (or first) project,
        else a fresh one. Reads run outside any open transaction; the create
        opens its own."""
        project_id = binding['selected_project_id']
        with self.store.connect() as con:
            if project_id:
                row = con.execute('SELECT id FROM projects WHERE account_id=? AND id=?',
                                  (binding['account_id'], project_id)).fetchone()
                if not row:
                    raise NotFound('unavailable')
            else:
                row = con.execute('SELECT id FROM projects WHERE account_id=? ORDER BY created_at,id LIMIT 1',
                                  (binding['account_id'],)).fetchone()
                if not row:
                    raise Conflict('account setup incomplete')
                project_id = row[0]
            latest = con.execute('''SELECT c.id FROM conversations c WHERE c.account_id=? AND c.project_id=?
                AND EXISTS(SELECT 1 FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id)
                ORDER BY c.created_at DESC,c.id DESC LIMIT 1''', (binding['account_id'], project_id)).fetchone()
        if latest:
            return project_id, latest[0]
        created = self.chat.create_conversation(
            Principal(binding['account_id'], binding['actor_id'], 'customer'), project_id)
        return project_id, created['id']

    def handle_update(self, update):
        """Returns a coarse outcome for the caller's log; never raises for
        provider-shaped payloads it can ignore."""
        if not isinstance(update, dict):
            return 'ignored'
        update_id = update.get('update_id')
        if type(update_id) is not int or update_id < 0:
            return 'ignored'
        with self.coordinator.transaction() as con:
            fresh = self._dedupe(con, update_id)
        if not fresh:
            return 'duplicate'
        message = update.get('message')
        if not isinstance(message, dict):
            return 'ignored'
        chat = message.get('chat')
        sender = message.get('from')
        text = message.get('text')
        if not isinstance(chat, dict) or chat.get('type') != 'private' or not isinstance(sender, dict):
            return 'ignored'  # groups stay disabled; attachments bounded away (Phase 8)
        chat_id = str(chat.get('id'))
        user_id = sender.get('id')
        if not isinstance(user_id, int) or not isinstance(text, str) or not text.strip():
            return 'ignored'  # numeric identity only; usernames and forwards are not trusted
        payload = text.strip()[:16000]
        with self.store.connect() as con:
            binding = self._binding(con, chat_id)
        if binding is None:
            return self._handle_unlinked(chat_id, user_id, payload)
        return self._handle_linked(binding, chat_id, user_id, payload, update_id)

    def _handle_unlinked(self, chat_id, user_id, payload):
        code = payload[6:].strip() if payload.lower().startswith('/start') else ''
        if not code:
            with self.coordinator.transaction() as con:
                reply = self._reply(con, chat_id, 'This chat is not linked to an AgentAI account. '
                                    'Create a link code in your account dashboard and send /start <code>.')
            self._flush(reply)
            return 'unlinked'
        return self._consume_code(chat_id, user_id, code)

    def _consume_code(self, chat_id, user_id, raw):
        now = int(self.clock())
        digest = code_digest(raw)
        with self.coordinator.transaction() as con:
            row = con.execute('''SELECT account_id,id,actor_id FROM telegram_link_codes
                WHERE code_hash=?''', (digest,)).fetchone()
            if not row:
                reply = self._reply(con, chat_id, 'This link code is not valid. Request a new one in your dashboard.')
                outcome = 'invalid_code'
            else:
                consumed = con.execute('''UPDATE telegram_link_codes SET consumed_epoch=?
                    WHERE account_id=? AND id=? AND consumed_epoch IS NULL AND expires_epoch>?''',
                    (now, row['account_id'], row['id'], now)).rowcount
                alive = self._alive(con, row['account_id'], row['actor_id'])
                existing = con.execute('SELECT account_id FROM telegram_links WHERE chat_id=?', (chat_id,)).fetchone()
                if consumed != 1:
                    reply = self._reply(con, chat_id, 'This link code expired or was already used. Request a new one.')
                    outcome = 'code_expired_or_used'
                elif not alive:
                    reply = self._reply(con, chat_id, 'Your AgentAI account is not available for linking.')
                    outcome = 'account_unavailable'
                elif existing and existing['account_id'] != row['account_id']:
                    reply = self._reply(con, chat_id, 'This chat is already linked to another AgentAI account. '
                                        'Unlink it there first.')
                    outcome = 'link_conflict'
                else:
                    con.execute('''INSERT INTO telegram_links(account_id,chat_id,telegram_user_id,actor_id,
                        selected_project_id,created_epoch,updated_epoch) VALUES (?,?,?,?,NULL,?,?)
                        ON CONFLICT(chat_id) DO UPDATE SET telegram_user_id=excluded.telegram_user_id,
                        actor_id=excluded.actor_id,updated_epoch=excluded.updated_epoch''',
                        (row['account_id'], chat_id, str(user_id), row['actor_id'], now, now))
                    self.coordinator._audit(con, row['account_id'], row['actor_id'], chat_id,
                                            'telegram.link', 'completed')
                    reply = self._reply(con, chat_id, 'Linked. Send /projects to pick a project, then just write '
                                        'your request. Agent execution is offline; messages queue safely.',
                                        row['account_id'])
                    outcome = 'linked'
        self._flush(reply)
        return outcome

    def _handle_linked(self, binding, chat_id, user_id, payload, update_id):
        principal = Principal(binding['account_id'], binding['actor_id'], 'customer')
        with self.coordinator.transaction() as con:
            if not self._alive(con, binding['account_id'], binding['actor_id']):
                reply = self._reply(con, chat_id, 'Your AgentAI account is unavailable; this chat cannot start work.')
                self._flush(reply)
                return 'account_unavailable'
        if payload.startswith('/'):
            with self.coordinator.transaction() as con:
                outcome = self._command(con, binding, chat_id, payload)
            self._flush_latest(chat_id)
            return outcome
        try:
            project_id, conversation_id = self._resolve_conversation(binding)
        except (Conflict, NotFound):
            with self.coordinator.transaction() as con:
                reply = self._reply(con, chat_id, 'Your account has no usable project yet. Create one in the dashboard.',
                                    binding['account_id'])
                self._flush(reply)
            return 'no_project'
        try:
            self.chat.send(principal, conversation_id=conversation_id, message=payload,
                           key='tg' + str(update_id), provenance='telegram')
        except BudgetDenied:
            with self.coordinator.transaction() as con:
                reply = self._reply(con, chat_id, 'Your plan allowance cannot fund this request. '
                                    'Nothing was charged or started.', binding['account_id'])
                self._flush(reply)
            return 'budget_denied'
        except Conflict:
            return 'conflict'
        with self.coordinator.transaction() as con:
            reply = self._reply(con, chat_id, 'Saved to your AgentAI queue. Agent execution is offline; '
                                'nothing runs or is charged yet.', binding['account_id'])
        self._flush(reply)
        return 'queued'

    def _command(self, con, binding, chat_id, payload):
        command, _, argument = payload.partition(' ')
        command = command.lower().strip()
        principal = Principal(binding['account_id'], binding['actor_id'], 'customer')
        if command == '/projects':
            projects = self.chat.projects(principal)
            listing = '\n'.join(f'{p["id"][:12]} — {p["name"]}{" (active)" if p["id"] == binding["selected_project_id"] else ""}'
                                for p in projects) or 'No projects yet.'
            self._reply(con, chat_id, 'Your projects:\n' + listing + '\n\nSelect with /use <id>.', binding['account_id'])
            return 'projects'
        if command == '/use':
            wanted = argument.strip()
            match = [p['id'] for p in self.chat.projects(principal) if wanted and p['id'].startswith(wanted)]
            if len(match) != 1:
                self._reply(con, chat_id, 'Unknown project. Send /projects to list valid ids.', binding['account_id'])
                return 'use_denied'
            con.execute('UPDATE telegram_links SET selected_project_id=?,updated_epoch=? WHERE chat_id=?',
                        (match[0], int(self.clock()), chat_id))
            self._reply(con, chat_id, 'Active project set. Your next message starts or continues a conversation there.',
                        binding['account_id'])
            return 'use_ok'
        if command == '/status':
            waiting = con.execute("SELECT count(*) FROM customer_requests WHERE account_id=? AND state='waiting'",
                                  (binding['account_id'],)).fetchone()[0]
            self._reply(con, chat_id, f'{waiting} request(s) waiting. Agent execution is offline; '
                        'nothing runs or is charged yet.', binding['account_id'])
            return 'status'
        if command == '/unlink':
            con.execute('DELETE FROM telegram_links WHERE chat_id=?', (chat_id,))
            self.coordinator._audit(con, binding['account_id'], binding['actor_id'], chat_id,
                                    'telegram.unlink', 'completed')
            self._reply(con, chat_id, 'Unlinked. Re-link anytime from your dashboard.')
            return 'unlinked'
        if command == '/start':
            self._reply(con, chat_id, 'This chat is already linked. Send /projects to pick a project, '
                        'then write your request.', binding['account_id'])
            return 'already_linked'
        self._reply(con, chat_id, 'Unknown command. Use /projects, /use <id>, /status or just write your request.',
                    binding['account_id'])
        return 'unknown_command'

    def drain(self, limit=20):
        """Host-side bounded sender for replies the webhook could not deliver."""
        with self.store.connect() as con:
            rows = con.execute("""SELECT id FROM telegram_outbox WHERE state='pending'
                ORDER BY created_epoch,id LIMIT ?""", (limit,)).fetchall()
        for row in rows:
            self._flush(row['id'])
        return len(rows)
