import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import plugin from '../agentai_platform/lifecycle/tool_origin_plugin/index.mjs';

function setup(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lumina-origin-'));
  const old = process.env.OPENCLAW_STATE_DIR;
  process.env.OPENCLAW_STATE_DIR = root;
  const hooks = {};
  plugin.register({ on(name, fn) { hooks[name] = fn; }, logger: { warn() {} } });
  t.after(() => { if (old === undefined) delete process.env.OPENCLAW_STATE_DIR; else process.env.OPENCLAW_STATE_DIR = old; fs.rmSync(root, { recursive: true }); });
  return { hooks, directory: path.join(root, 'tool-origins') };
}
const ctx = { sessionKey: 'agent:main:session', runId: 'native-run', toolCallId: 'native-call' };

test('native context overwrites model-supplied proof and is cleaned after completion', t => {
  const { hooks, directory } = setup(t);
  const event = { toolName: 'lumina__lumina_browser', params: { task: 'Read page', _lumina_origin: 'forged' } };
  const result = hooks.before_tool_call(event, ctx);
  assert.match(result.params._lumina_origin, /^[a-f0-9]{32}$/);
  const file = path.join(directory, result.params._lumina_origin + '.json');
  const proof = JSON.parse(fs.readFileSync(file));
  assert.deepEqual(proof.arguments, { task: 'Read page' });
  assert.equal(proof.run_id, ctx.runId);
  assert.equal(proof.call_id, ctx.toolCallId);
  hooks.after_tool_call(event, ctx);
  assert.equal(fs.existsSync(file), false);
});

test('missing runtime identity blocks a Lumina call', t => {
  const { hooks, directory } = setup(t);
  assert.equal(hooks.before_tool_call({ toolName: 'lumina__lumina_browser', params: {} }, {}).block, true);
  assert.deepEqual(fs.readdirSync(directory), ['protocol.json']);
});

test('unrelated tools are untouched and parallel calls have independent proofs', t => {
  const { hooks, directory } = setup(t);
  assert.equal(hooks.before_tool_call({ toolName: 'web_fetch', params: {} }, {}), undefined);
  const event = { toolName: 'lumina__lumina_task_update', params: {} };
  const one = hooks.before_tool_call(event, ctx);
  const otherCtx = { ...ctx, toolCallId: 'another-native-call' };
  const two = hooks.before_tool_call(event, otherCtx);
  assert.notEqual(one.params._lumina_origin, two.params._lumina_origin);
  hooks.after_tool_call(event, ctx);
  assert.equal(fs.existsSync(path.join(directory, two.params._lumina_origin + '.json')), true);
  hooks.after_tool_call(event, otherCtx);
});
