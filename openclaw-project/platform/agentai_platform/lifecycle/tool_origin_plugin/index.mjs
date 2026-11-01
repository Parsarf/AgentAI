import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const NAMES = new Map(['lumina_browser', 'lumina_browser_step', 'lumina_task_update', 'lumina_mcp_discover', 'lumina_mcp_call'].map(n => ['lumina__' + n, n]));
const MAX_BYTES = 24000;
const MAX_PENDING = 64;
const MAX_AGE_MS = 30 * 60 * 1000;
const fileName = nonce => nonce + '.json';

export default {
  id: 'lumina-tool-origin',
  register(api) {
    const state = process.env.OPENCLAW_STATE_DIR || path.join(process.env.HOME, '.openclaw');
    const directory = path.join(state, 'tool-origins');
    try { fs.mkdirSync(directory, { mode: 0o700 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    const info = fs.lstatSync(directory);
    if (!info.isDirectory() || info.isSymbolicLink() || (info.mode & 0o077)) throw new Error('unsafe Lumina origin directory');
    const pending = new Map();
    fs.writeFileSync(path.join(directory, 'protocol.json'), '{"version":2}\n', { mode: 0o600, flag: 'w' });

    api.on('before_tool_call', (event, ctx) => {
      const name = NAMES.get(event.toolName) || (/^lumina__lumina_mcp_[a-f0-9]{32}_[a-f0-9]{12}$/.test(event.toolName) ? event.toolName.slice('lumina__'.length) : null);
      if (!name) return;
      if (![ctx.sessionKey, ctx.runId, ctx.toolCallId].every(v => typeof v === 'string' && v.length > 0 && v.length < 512)) {
        return { block: true, blockReason: 'Lumina could not verify the runtime tool identity. Nothing was started.' };
      }
      const now = Date.now();
      try {
        for (const entry of fs.readdirSync(directory)) {
          // Also prune claim markers: they only matter while their proof could still be read.
          if (!/^[a-f0-9]{32}\.(json|claimed)$/.test(entry)) continue;
          const target = path.join(directory, entry);
          if (now - fs.lstatSync(target).mtimeMs > MAX_AGE_MS) fs.unlinkSync(target);
        }
        if (fs.readdirSync(directory).filter(n => /^[a-f0-9]{32}\.json$/.test(n)).length >= MAX_PENDING) throw new Error('capacity');
        const { _lumina_origin: ignored, ...arguments_ } = event.params;
        const nonce = randomUUID().replaceAll('-', '');
        const data = JSON.stringify({ version: 2, name, arguments: arguments_,
          session_key: ctx.sessionKey, run_id: ctx.runId, call_id: ctx.toolCallId, started_ms: now });
        if (Buffer.byteLength(data) > MAX_BYTES) throw new Error('size');
        const temporary = path.join(directory, '.' + randomUUID() + '.tmp');
        try {
          fs.writeFileSync(temporary, data, { mode: 0o600, flag: 'wx' });
          fs.renameSync(temporary, path.join(directory, fileName(nonce)));
        } finally { try { fs.unlinkSync(temporary); } catch {} }
        pending.set(ctx.toolCallId, nonce);
        return { params: { ...arguments_, _lumina_origin: nonce } };
      } catch {
        return { block: true, blockReason: 'Lumina could not register this tool call. Nothing was started.' };
      }
    }, { matcher: [...NAMES.keys()], priority: -10000 });

    api.on('after_tool_call', (event, ctx) => {
      if (!NAMES.has(event.toolName) || !ctx.toolCallId) return;
      const nonce = pending.get(ctx.toolCallId);
      pending.delete(ctx.toolCallId);
      if (!nonce) return;
      try { fs.unlinkSync(path.join(directory, fileName(nonce))); }
      catch (error) { if (error.code !== 'ENOENT') api.logger.warn('Lumina tool receipt cleanup failed'); }
    }, { matcher: [...NAMES.keys()] });
  }
};
