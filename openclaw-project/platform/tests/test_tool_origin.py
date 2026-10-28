"""Native origin verification rejects stale, completed and ambiguous tool calls."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentai_platform.lifecycle.tool_origin import resolve


class OriginChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'state').mkdir()
        (self.root / 'agents/main/agent').mkdir(parents=True)
        self.state = sqlite3.connect(self.root / 'state/openclaw.sqlite')
        self.agent = sqlite3.connect(self.root / 'agents/main/agent/openclaw-agent.sqlite')
        self.addCleanup(self.state.close)
        self.addCleanup(self.agent.close)
        self.state.execute('CREATE TABLE worker_session_placements(session_id,session_key,turn_claim_run_id,turn_claim_id)')
        self.agent.execute('CREATE TABLE transcript_events(session_id,seq,event_json,event_zstd,event_utf8_bytes)')
        self.args = {'task': 'Read available colours', 'site': 'https://shop.example/product'}
        self.call = {'type': 'toolCall', 'id': 'call-1', 'name': 'tool_call', 'arguments': {'id': 'mcp:lumina:lumina__lumina_browser', 'args': self.args}}
        self.add('s1', 'run-1')

    def add(self, session, run):
        self.state.execute('INSERT INTO worker_session_placements VALUES (?,?,?,?)', (session, 'agent:main:' + session, run, 'claim-' + session))
        self.state.commit()
        self.event(session, 1, {'role': 'assistant', '__openclaw': {'runId': run}, 'content': [self.call]})

    def event(self, session, seq, message, compressed=False):
        raw = json.dumps({'type': 'message', 'message': message})
        blob = None
        if compressed:
            from compression import zstd
            blob = zstd.compress(raw.encode())
        self.agent.execute('INSERT INTO transcript_events VALUES (?,?,?,?,?)', (session, seq, None if compressed else raw, blob, len(raw)))
        self.agent.commit()

    def test_current_pending_call_has_a_verified_native_origin(self):
        self.assertEqual(resolve(self.root, 'lumina_browser', self.args), {'session_key': 'agent:main:s1', 'run_id': 'run-1', 'call_id': 'call-1'})
        self.assertIsNone(resolve(self.root, 'lumina_browser', {**self.args, 'site': 'other.example'}))

    def test_completed_call_cannot_be_replayed(self):
        self.event('s1', 2, {'role': 'toolResult', 'toolCallId': 'call-1', 'content': []})
        self.assertIsNone(resolve(self.root, 'lumina_browser', self.args))

    def test_claim_for_new_run_does_not_authorize_old_transcript(self):
        self.state.execute("UPDATE worker_session_placements SET turn_claim_run_id='new-run'")
        self.state.commit()
        self.assertIsNone(resolve(self.root, 'lumina_browser', self.args))

    def test_ambiguous_identical_calls_fail_closed(self):
        self.add('s2', 'run-2')
        self.assertIsNone(resolve(self.root, 'lumina_browser', self.args))

    def test_compressed_native_transcripts_are_supported(self):
        self.agent.execute('DELETE FROM transcript_events')
        self.event('s1', 1, {'role': 'assistant', '__openclaw': {'runId': 'run-1'}, 'content': [self.call]}, compressed=True)
        self.assertIsNotNone(resolve(self.root, 'lumina_browser', self.args))

    def test_missing_or_redirected_state_fails_closed(self):
        self.assertIsNone(resolve(self.root / 'absent', 'lumina_browser', self.args))
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(resolve(alias, 'lumina_browser', self.args))

    def test_corrupt_compression_fails_closed(self):
        self.agent.execute('DELETE FROM transcript_events')
        self.agent.execute("INSERT INTO transcript_events VALUES ('s1',1,NULL,?,12)", (b'not zstd',))
        self.agent.commit()
        self.assertIsNone(resolve(self.root, 'lumina_browser', self.args))

    def test_oversized_records_and_invalid_tool_names_fail_closed(self):
        self.assertIsNone(resolve(self.root, [], self.args))
        self.agent.execute("UPDATE transcript_events SET event_json=?,event_utf8_bytes=1", ('x' * 512001,))
        self.agent.commit()
        self.assertIsNone(resolve(self.root, 'lumina_browser', self.args))
