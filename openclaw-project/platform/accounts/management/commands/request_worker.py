"""Customer request worker loop (app user). Runs requests only while the owner's customer_execution switch is on."""
import json
import time
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.browse.client import BrowseRpc
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatDriver
from agentai_platform.events import EventService
from agentai_platform.gateway import NativeGateway
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.genui.store import BlockStore
from agentai_platform.lifecycle.profiles import host_capacity
from agentai_platform.request_queue import RequestQueue
from agentai_platform.request_worker import RequestWorker
from accounts.chat import execution_on
from accounts.lifecycle import AccountStore


def build_worker(store):
    queue = RequestQueue(store, require_cell=True)
    factory = lambda claim: NativeGateway(BridgeRpc(claim.account_id, settings.CELL_BRIDGE_SOCKET))
    driver = ChatDriver(store, ledger=BudgetLedger(store), gateway_factory=factory, events=EventService(store),
                        sleep=time.sleep, heartbeat=queue.heartbeat, genui=GenUiRuntime(store, BlockStore(store)),
                        browse_factory=lambda account: BrowseRpc(account, settings.BROWSE_SOCKET))
    from agentai_platform.routing.shadow import ShadowRouter
    from agentai_platform.switches import SwitchStore
    switches = SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None)
    shadow = ShadowRouter(store, config_path=settings.ROUTING_CONFIG_FILE, key_path=settings.TYPESAFE_KEY_FILE,
                          switch_on=lambda: switches.is_on('jev_routing'))
    from accounts.chat import service
    return RequestWorker(queue, driver, host_capacity, shadow=shadow, runner=lambda: service().runner)


class Command(BaseCommand):
    help = 'Run waiting customer requests through their own cell (only while customer_execution is on).'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=3)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        store = AccountStore(connection.settings_dict['NAME'])
        worker = build_worker(store)
        while True:
            try:
                report = worker.tick() if execution_on() else {'idle': 'customer_execution is off'}
            except Exception as exc:   # one failed request must not stop the loop; the queue marks it uncertain
                report = {'error': type(exc).__name__}
            if report != {'ran': 0}:
                print(json.dumps(report, sort_keys=True), flush=True)   # counts and states only; no account detail
            if options['once']:
                return
            time.sleep(options['interval'])
