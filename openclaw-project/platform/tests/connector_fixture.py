"""A database with two accounts, sealed custody, the synthetic connector registered, and every service of the connector and action layers on top (shared by the Phase 2-3 tests)."""
import tempfile
import unittest
from pathlib import Path

from agentai_platform import synthetic_connector
from agentai_platform.action_runner import ActionRunner
from agentai_platform.actions import ActionService
from agentai_platform.connector_custody import SealedCustody
from agentai_platform.connector_kit import ConnectorClient, Registry
from agentai_platform.connector_refresh import ConnectorRefresher
from agentai_platform.connectors import ConnectorService
from agentai_platform.organizations import OrganizationService
from agentai_platform.security import Principal
from agentai_platform.store import Store
from agentai_platform.synthetic_connector import SyntheticBench
from agentai_platform.vault import Keyring
from agentai_platform.workflows import WorkflowService


class ConnectorBase(unittest.TestCase):
    ACCOUNTS = ('a', 'b')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        clock = lambda: self.now
        with self.store.connect() as con:
            for a in self.ACCOUNTS:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (a, 'd-' + a))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (a, 'p-' + a))
                con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                    VALUES (?,?,?,?,?,?,'h','m','running',1)''', (a, 'req-' + a, 'actor-' + a, 'p-' + a, 'c-' + a, 'k-' + a))
        key = Keyring.generate().split(':', 1)
        self.custody = SealedCustody(self.store, Keyring({key[0]: __import__('base64').urlsafe_b64decode(key[1] + '=' * (-len(key[1]) % 4))}, key[0]), clock=clock)
        self.registry = synthetic_connector.register(Registry(), self.store, clock)
        self.notices = []
        self.connectors = ConnectorService(self.store, custody=self.custody, registry=self.registry, clock=clock, notify=lambda *a: self.notices.append(a))
        self.slept = []
        self.client = ConnectorClient(self.store, self.connectors, self.registry, clock=clock, sleep=self.slept.append)
        self.actions = ActionService(self.store, self.connectors, self.client, clock=clock)
        self.workflows = WorkflowService(self.store, self.actions, clock=clock)
        self.runner = ActionRunner(self.store, self.actions, self.workflows, clock=clock)
        self.refresher = ConnectorRefresher(self.store, self.connectors, {'synthetic': SyntheticBench.refresher}, clock=clock)
        self.orgs = OrganizationService(self.store, clock=clock)
        self.bench = SyntheticBench(self.store, clock)
        self.a, self.b = (Principal(x, 'actor-' + x, 'customer') for x in self.ACCOUNTS[:2])

    def connect(self, who=None, *, grants=(('folder', 'inbox', 'write'),), expires_in=3600, tokens=None):
        who = who or self.a
        connection = self.connectors.connect_declared(who, 'synthetic', who.account_id + '@synthetic.test', tokens=tokens or SyntheticBench.tokens(who.account_id),
                                                      scopes=('notes', 'messages'), expires_in=expires_in)
        if grants:
            self.connectors.set_grants(who, connection, [{'kind': k, 'id': i, 'access': acc} for k, i, acc in grants])
        return connection

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def do(self, connection, kind, payload, who=None, request_id=None):
        """Propose, approve and run one change. -> the action afterwards."""
        who = who or self.a
        action = self.actions.propose(who, connection, kind, payload, request_id=request_id or 'req-' + who.account_id)
        self.actions.approve(who, action['id'], action['payload_hash'])
        self.actions.execute(who.account_id, action['id'])
        return self.actions.get(who, action['id'])
