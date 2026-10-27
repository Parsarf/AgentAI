"""Serve Lumina's native tools (the sandboxed browser) to customer cells over MCP. App user; bound to the cells' bridge address. See agentai_platform/tool_relay.py."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.browse.adapter import BrowserTool
from agentai_platform.browse.client import BrowseRpc
from agentai_platform.events import EventService
from agentai_platform.switches import SwitchStore
from agentai_platform.tool_relay import Identity, Relay, serve
from accounts.lifecycle import AccountStore


def build(store):
    switches = SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None)
    tool = BrowserTool(store, browse_factory=lambda account: BrowseRpc(account, settings.BROWSE_SOCKET), enabled=lambda: switches.is_on('browse_tasks'), events=EventService(store))
    identify = lambda credential: BridgeRpc('-', settings.CELL_BRIDGE_SOCKET)('cell.identify', {'credential': credential}).get('account')
    return Relay(tool), Identity(identify)


class Command(BaseCommand):
    help = 'Serve the native browser tool to customer cells (MCP over HTTP on the cells bridge address).'

    def add_arguments(self, parser):
        parser.add_argument('--bind', default=settings.TOOL_RELAY_BIND)
        parser.add_argument('--port', type=int, default=settings.TOOL_RELAY_PORT)

    def handle(self, *args, **options):
        relay, identity = build(AccountStore(connection.settings_dict['NAME']))
        server = serve(relay, identity, options['bind'], options['port'])
        print(f'tool relay on {options["bind"]}:{options["port"]}', flush=True)
        server.serve_forever()
