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
from agentai_platform.task_progress import TaskProgressTool
from agentai_platform.tool_relay import Identity, Relay, serve
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
        """Exactly one funded live run, and its reservation is the kind (own key or Lumina's) the call claims."""
        with store.connect() as con:
            rows = con.execute(f"""SELECT v.amount_microusd FROM task_reservations v
                JOIN customer_requests r ON r.account_id=v.account_id AND r.id=v.task_id
                JOIN accounts a ON a.id=r.account_id WHERE r.account_id=? AND a.status='active'
                AND {request_states.live_run()}
                AND v.state='active' LIMIT 2""", (account,)).fetchall()
        return len(rows) == 1 and (rows[0]['amount_microusd'] == OWN_KEY_AMOUNT) == personal
    def selected_route(account):
        with store.connect() as con:
            rows = con.execute(f"""SELECT r.context_json FROM customer_requests r
                JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                JOIN accounts a ON a.id=r.account_id WHERE r.account_id=? AND a.status='active'
                AND {request_states.live_run()} AND v.state='active' LIMIT 2""", (account,)).fetchall()
        if len(rows) != 1:
            raise model_keys.RelayError(403, 'No single admitted task owns this model call.', 'admission_mismatch')
        selected = json.loads(rows[0]['context_json'] or '{}').get('model_selection')
        # Existing requests admitted before the snapshot release retain compatibility.
        return selected if isinstance(selected, str) else wiring.model_key_store(sealed=False).choices(account)['selected']
    own_models = model_keys.ModelRelay(wiring.model_key_store(), wiring.own_model_on, admission=selection_admitted, selection=selected_route)
    memory = wiring.memory_service(store)                         # None unless fully configured; the tools then do not exist for anyone
    files = None                                                  # the file tool exists only where files can be stored at all
    if wiring.storage_ready():
        files = FileTools(store, wiring.artifact_service(store), gateway_for=wiring.cell_gateway, renderer=wiring.renderer(), events=wiring.event_service(store))
    return (Relay(tool, location=LocationTool(store), progress=TaskProgressTool(store), origin=origin, memory=MemoryTools(memory) if memory is not None else None,
                  remote=RemoteTools(wiring.mcp_service(store), enabled=wiring.mcp_on), files=files), Identity(identify), own_models)


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
