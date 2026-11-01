"""The owner's switch for remote MCP connections: off unless turned on, read every time, and when off the assistant's remote tools are gone."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from agentai_platform.mcp_connections import switch
from agentai_platform.mcp_connections.relay import CALL, DISCOVER, RemoteTools
from agentai_platform.tool_relay import Relay


class Switch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup); self.path = Path(self.dir.name) / 'mcp-connections.json'

    def put(self, text):
        self.path.write_text(text)

    def test_it_is_off_unless_the_file_says_otherwise(self):
        self.assertFalse(switch.enabled(str(self.path), 'a1'))                                    # no file
        for text in ('', 'not json', '[]', '{}', '{"mcp_connections": false}', '{"mcp_connections": "true"}', '{"mcp_connections": 1}', '{"mcp_connections": []}', '{"other": true}'):
            self.put(text); self.assertFalse(switch.enabled(str(self.path), 'a1'), text)
        self.assertFalse(switch.enabled('', 'a1'))

    def test_true_is_everyone_and_a_list_is_those_accounts(self):
        self.put('{"mcp_connections": true}'); self.assertTrue(switch.enabled(str(self.path), 'a1'))
        self.put('{"mcp_connections": ["a1", "a2"]}')
        self.assertTrue(switch.enabled(str(self.path), 'a2')); self.assertFalse(switch.enabled(str(self.path), 'a3')); self.assertFalse(switch.enabled(str(self.path), None))

    def test_it_is_read_every_time_so_turning_it_off_takes_effect_at_once(self):
        self.put('{"mcp_connections": true}'); self.assertTrue(switch.enabled(str(self.path), 'a1'))
        self.put('{"mcp_connections": false}'); self.assertFalse(switch.enabled(str(self.path), 'a1'))

    def test_a_symlink_or_an_oversize_file_counts_as_off(self):
        self.put('{"mcp_connections": true}'); link = Path(self.dir.name) / 'link.json'; os.symlink(self.path, link)
        self.assertFalse(switch.enabled(str(link), 'a1'))
        self.put('{"mcp_connections": true, "pad": "' + 'x' * switch.MAX_BYTES + '"}'); self.assertFalse(switch.enabled(str(self.path), 'a1'))


class Service:
    def catalog(self, account): return [{'name': 'lumina_mcp_x', 'description': 'd', 'inputSchema': {'type': 'object', 'properties': {}}}]
    def refresh_catalog(self, account, closed=None): return []


class Browser:
    def __init__(self): self.calls = []
    def call(self, account, arguments, closed, name=None, **kw): self.calls.append(name); return ('browser ran', False)


def rpc(relay, method, params=None):
    return relay.handle('a1', {'jsonrpc': '2.0', 'id': 1, 'method': method, **({'params': params} if params else {})})


class RelayWithdrawsTheTools(unittest.TestCase):
    def relay(self, on):
        self.browser = Browser(); self.on = on
        return Relay(self.browser, remote=RemoteTools(Service(), enabled=lambda account: self.on[0]))

    def names(self, relay):
        return [t['name'] for t in rpc(relay, 'tools/list')['result']['tools']]

    def test_the_remote_tools_are_listed_only_while_the_switch_is_on(self):
        relay = self.relay([True]); names = self.names(relay)
        self.assertIn(DISCOVER['name'], names); self.assertIn(CALL['name'], names); self.assertIn('lumina_mcp_x', names)
        self.on[0] = False; names = self.names(relay)
        self.assertNotIn(DISCOVER['name'], names); self.assertNotIn(CALL['name'], names); self.assertNotIn('lumina_mcp_x', names)
        self.assertIn('lumina_browser', names)                                                          # the browser tool is untouched

    def test_a_call_while_off_is_refused_and_never_reaches_the_browser_tool(self):
        relay = self.relay([False])
        for name in (CALL['name'], DISCOVER['name'], 'lumina_mcp_x'):
            reply = rpc(relay, 'tools/call', {'name': name, 'arguments': {'tool': 'lumina_mcp_x', 'arguments': {}}})
            self.assertEqual(reply['error']['message'], 'unknown tool', name)
        self.assertEqual(self.browser.calls, [])


if __name__ == '__main__':
    unittest.main()
