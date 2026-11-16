"""Serve Lumina's native tools and admitted model routes to customer cells."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand
from agentai_platform.browse.adapter import BrowserTool
from agentai_platform.budget import OWN_KEY_AMOUNT
from agentai_platform.location import LocationTool
from agentai_platform.file_tools import FileTools
from agentai_platform.longterm_memory import MemoryTools
from agentai_platform.mcp_connections.relay import RemoteTools
from agentai_platform.show_tool import ShowTools
from agentai_platform.task_progress import TaskProgressTool
from agentai_platform.tool_relay import Identity, Relay, ToolPermit, serve
from agentai_platform import model_keys, request_states
from accounts import wiring


def build(store):
    switches = wiring.switches()
    tool = BrowserTool(store, browse_factory=wiring.browse_rpc, enabled=lambda: switches.is_on('browse_tasks'), events=wiring.event_service(store))
    identify = lambda credential: wiring.cell_rpc('-')('cell.identify', {'credential': credential}).get('account')
    def origin(account, name, arguments):
        arguments = dict(arguments)
        nonce = arguments.pop('_lumina_origin', None)
        return wiring.cell_rpc(account)('tools.origin', {'name': name, 'arguments': arguments, 'nonce': nonce})
    def selection_admitted(account, personal):
        """At least one funded live run, and every one's reservation is the kind (own key or Lumina's) the call claims."""
        with store.connect() as con:
            rows = con.execute(f"""SELECT v.amount_microusd FROM task_reservations v
                JOIN customer_requests r ON r.account_id=v.account_id AND r.id=v.task_id
                JOIN accounts a ON a.id=r.account_id WHERE r.account_id=? AND a.status='active'
                AND {request_states.live_run()}
                AND v.state='active' LIMIT 8""", (account,)).fetchall()
        # Several requests of one account can be live at once (the customer's task and phases of a plan in their lanes). A model call belongs to the account, and every live request of
        # an account is admitted on the same route, so the call is admitted when ALL of them agree with it.
        return len(rows) >= 1 and all((r['amount_microusd'] == OWN_KEY_AMOUNT) == personal for r in rows)
    def selected_route(account):
        with store.connect() as con:
            rows = con.execute(f"""SELECT r.context_json FROM customer_requests r
                JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                JOIN accounts a ON a.id=r.account_id WHERE r.account_id=? AND a.status='active'
                AND {request_states.live_run()} AND v.state='active' LIMIT 8""", (account,)).fetchall()
        selections = {json.loads(r['context_json'] or '{}').get('model_selection') for r in rows}
        if not rows or len(selections) != 1:        # no admitted task, or live tasks that were admitted on different routes: no model call may be attributed to either
            raise model_keys.RelayError(403, 'No single admitted task owns this model call.', 'admission_mismatch')
        selected = next(iter(selections))
        # Existing requests admitted before the snapshot release retain compatibility.
        return selected if isinstance(selected, str) else wiring.model_key_store(sealed=False).choices(account)['selected']
    events = wiring.event_service(store)
    def provider_wait(account, seconds=0, first=True, own=False):
        """The model provider asked us to wait (a per-minute limit, or it is busy). The wait is not the task's own time: its run limit is moved out by as long as it waited. The
        account's one running task is told (once per call) in its timeline, so a pause reads as a pause, and whose limit it is."""
        with store.connect() as con:
            rows = con.execute(f"SELECT r.id FROM customer_requests r WHERE r.account_id=? AND {request_states.live_run()} LIMIT 8", (account,)).fetchall()
        for row in rows:                                      # the call may belong to any of the account's live requests: each one's run limit moves out, and each is told
            if seconds and seconds > 0:
                with store.connect() as con:
                    con.execute("UPDATE chat_deliveries SET deadline_epoch=deadline_epoch+? WHERE account_id=? AND request_id=? AND state IN ('acknowledged','uncertain') AND deadline_epoch IS NOT NULL",
                                (int(seconds) + 1, account, row['id']))
            if first:
                words = 'Your own model provider asked for a short wait (its limit, not Lumina\'s). Carrying on in a moment.' if own else 'Waiting a moment for the model provider, then carrying on.'
                events.append(account, row['id'], 'progress', {'summary': words, 'step': 'working'}, 'gateway')
    own_models = model_keys.ModelRelay(wiring.model_key_store(), wiring.own_model_on, admission=selection_admitted, selection=selected_route, waiting=provider_wait)
    memory = wiring.memory_service(store)                         # None unless fully configured; the tools then do not exist for anyone
    files = None                                                  # the file tool exists only where files can be stored at all
    if wiring.storage_ready():
        files = FileTools(store, wiring.artifact_service(store), gateway_for=wiring.cell_gateway, renderer=wiring.renderer(), events=wiring.event_service(store))
    return (Relay(tool, location=LocationTool(store), progress=TaskProgressTool(store), origin=origin, memory=MemoryTools(memory) if memory is not None else None,
                  remote=RemoteTools(wiring.mcp_service(store), enabled=wiring.mcp_on), files=files, show=ShowTools(store), connectors=wiring.connector_tools(store), permit=ToolPermit(store)), Identity(identify), own_models)


class Command(BaseCommand):
    help = 'Serve native browser and task progress tools to customer cells (MCP over HTTP on the cells bridge address).'

    def add_arguments(self, parser):
        parser.add_argument('--bind', default=settings.TOOL_RELAY_BIND)
        parser.add_argument('--port', type=int, default=settings.TOOL_RELAY_PORT)

    def handle(self, *args, **options):
        relay, identity, own_models = build(wiring.store())
        server = serve(relay, identity, options['bind'], options['port'], byok=own_models)
        print(f'tool relay on {options["bind"]}:{options["port"]}', flush=True)
        server.serve_forever()
