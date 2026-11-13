"""Customer request worker loop (app user). Runs requests only while the owner's customer_execution switch is on."""
import json
import time
from django.conf import settings
from django.core.management.base import BaseCommand
from agentai_platform.chat_driver import ChatDriver
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.genui.store import BlockStore
from agentai_platform.goals import GoalChain
from agentai_platform.lifecycle.profiles import host_capacity
from agentai_platform.panel.offer import PanelOffer
from agentai_platform.request_worker import RequestWorker
from agentai_platform.routing.display import DisplayDecider
from agentai_platform.routing.shadow import ShadowRouter
from accounts import wiring


def build_worker(store):
    queue = wiring.request_queue(store, require_cell=True)
    switches = wiring.switches()
    # When the assistant answers in plain text, JEV may choose a layout for that text (owner switch jev_display, off by default: it sends the reply text to TypeSafe).
    display = DisplayDecider(config_path=settings.ROUTING_CONFIG_FILE, key_path=settings.TYPESAFE_KEY_FILE, switch_on=lambda: switches.is_on('jev_display'))
    # OpenClaw owns the run. The driver hands a message over, asks the runtime when it ended and settles it; the browser the assistant uses is a native tool (tool_relay).
    panel = PanelOffer(wiring.panel_secret, wiring.browse_rpc, enabled=lambda: switches.is_on('browse_tasks'))      # the side panel only exists for browser tasks, so their owner switch is its switch
    driver = ChatDriver(store, ledger=wiring.ledger(store), gateway_factory=lambda claim: wiring.cell_gateway(claim.account_id), events=wiring.event_service(store),
                        artifacts=wiring.artifact_service(store) if wiring.storage_ready() else None, sleep=time.sleep, heartbeat=queue.heartbeat,
                        genui=GenUiRuntime(store, BlockStore(store)), browse_factory=wiring.browse_rpc, display=display, queue=queue, goal_chain_limit=settings.GOAL_CHAIN_LIMIT, panel=panel)
    shadow = ShadowRouter(store, config_path=settings.ROUTING_CONFIG_FILE, key_path=settings.TYPESAFE_KEY_FILE,
                          switch_on=lambda: switches.is_on('jev_routing'))
    # Plan phases and goal turns are sent through the same chat service the web app uses (built fresh each tick, so an owner switch change is seen without a restart).
    return RequestWorker(queue, driver, host_capacity, shadow=shadow, runner=lambda: wiring.chat_service().runner, goals=lambda: GoalChain(wiring.chat_service(), limit=settings.GOAL_CHAIN_LIMIT))


class Command(BaseCommand):
    help = 'Run waiting customer requests through their own cell (only while customer_execution is on).'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=3)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        store = wiring.store()
        worker = build_worker(store)
        from agentai_platform.location import Locations
        locations = Locations(store)
        while True:
            try:
                # Heal old cancelled/queued disagreements before lifecycle drain or admission.
                worker.queue.reconcile_cancelled()
                locations.cleanup()
                report = worker.tick() if wiring.switch_on('customer_execution') else {'idle': 'customer_execution is off'}
            except Exception as exc:   # one failed request must not stop the loop; the queue marks it uncertain
                report = {'error': type(exc).__name__}
            if report != {'ran': 0}:
                print(json.dumps(report, sort_keys=True), flush=True)   # counts and states only; no account detail
            if options['once']:
                return
            time.sleep(options['interval'])
