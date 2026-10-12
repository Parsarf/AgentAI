import contextlib
import io
import json
import re
import uuid
from unittest.mock import patch
from django.db import connection
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.contrib.auth.models import User
from .models import Identity
from .services import token_for, consume
from .tests import AccountBoundaryTests, PASSWORD


class TelegramHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    ENABLED = override_settings(TELEGRAM_ENABLED=True, TELEGRAM_WEBHOOK_SECRET='s' * 40,
                                TELEGRAM_BOT_TOKEN='123:abc', TELEGRAM_BOT_USERNAME='agentai_testbot')

    def secret_post(self, client, update, secret=None):
        return client.post('/v1/telegram/webhook', json.dumps(update), content_type='application/json',
                           secure=True, HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret or ('s' * 40))

    def test_link_routes_fail_closed_and_require_identity(self):
        a = self.signed()
        anon = self.new_client()
        self.assertEqual(anon.post('/v1/account/telegram/link', '{}', content_type='application/json', secure=True).status_code, 403)
        self.assertEqual(self.post(anon, '/v1/account/telegram/link', {}).status_code, 401)
        self.assertEqual(self.post(a, '/v1/account/telegram/link', {}).status_code, 503)
        self.assertEqual(self.new_client().get('/v1/account/telegram', secure=True).status_code, 401)
        self.assertEqual(a.get('/v1/account/telegram', secure=True).json()['bindings'], [])

    def test_webhook_requires_secret_and_post(self):
        self.assertEqual(self.new_client().get('/v1/telegram/webhook', secure=True).status_code, 405)
        self.assertEqual(self.new_client().post('/v1/telegram/webhook', '{}', content_type='application/json', secure=True).status_code, 403)
        with self.ENABLED:
            self.assertEqual(self.new_client().post('/v1/telegram/webhook', '{}', content_type='application/json', secure=True).status_code, 403)
            self.assertEqual(self.secret_post(self.new_client(), {}).status_code, 200)
            self.assertEqual(self.secret_post(self.new_client(), {}, secret='wrong').status_code, 403)
            self.assertEqual(self.new_client().post('/v1/telegram/webhook', 'not json', content_type='application/json', secure=True,
                              HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='s' * 40).status_code, 200)

    @ENABLED
    def test_webhook_routes_linked_update_to_own_account(self):
        a, b = self.signed('a'), self.signed('b')
        with connection.cursor() as c:
            c.execute("INSERT INTO deployments(account_id,id,generation,state) SELECT account_id,'dx',1,'stopped' FROM projects GROUP BY account_id")
        from agentai_platform.security import Principal
        from agentai_platform.telegram import TelegramService
        from agentai_platform.chat import ChatService, FixedRoute
        from agentai_platform.request_queue import RequestQueue
        from agentai_platform.budget import BudgetLedger
        from .lifecycle import AccountStore
        store = AccountStore(connection.settings_dict['NAME'])
        chat = ChatService(store, queue=RequestQueue(store), ledger=BudgetLedger(store), pricer=FixedRoute(500))
        service = TelegramService(store, chat=chat, bot_username='agentai_testbot', clock=lambda: 2000000000)
        raw = service.create_code(Principal('a', str(self.users['a'].pk), 'customer'))['link'].split('=')[1]
        update = {'update_id': 7, 'message': {'message_id': 7, 'text': '/start ' + raw,
                  'chat': {'id': 555, 'type': 'private'}, 'from': {'id': 42}}}
        # No network in tests: the ack transport is stubbed at the view seam.
        class StubApi:
            def __init__(self, token): pass
            def send_message(self, chat_id, text): return 1
        with patch('accounts.telegram.TelegramBotApi', StubApi):
            self.assertEqual(self.secret_post(a, update).status_code, 200)
            self.assertEqual(self.secret_post(a, update).status_code, 200)  # dedup
            self.assertEqual(self.secret_post(a, {**update, 'update_id': 8, 'message': {**update['message'], 'text': 'real work'}}).status_code, 200)
        with connection.cursor() as c:
            c.execute("SELECT account_id, idempotency_key FROM customer_requests")
            rows = c.fetchall()
        self.assertEqual(rows, [('a', 'tg8')])
        # Other account's chat id never routes into A.
        self.assertEqual(b.get('/v1/tasks/tg8', secure=True).status_code, 404)

    def test_link_form_renders_disabled_notice(self):
        a = self.signed()
        page = a.get('/account/login/', secure=True)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        from django.utils.http import urlencode
        response = a.post('/v1/account/telegram/link', urlencode({'csrfmiddlewaretoken': token}),
                          content_type='application/x-www-form-urlencoded', secure=True,
                          HTTP_REFERER='https://localhost/account/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Telegram linking is not enabled yet')

    def test_home_overview_renders_telegram_section(self):
        a = self.signed()
        self.assertContains(a.get('/account/', secure=True), 'Telegram')
