import { describe, expect, it, vi } from 'vitest';
import { blockSchema, parseBlock, presentationPlanSchema, actionSchema, IMPLEMENTED_TYPES, treeShape } from './schemas';
import { COMPONENT_VARIANTS, checkCombination, FAMILY_VARIANTS } from './variants';
import { MANIFEST, byId, offerable, search } from './manifest';
import { ADAPTER_ONLY, OFFERED, REGISTRY, modelCatalog, schemaSummary, unsupportedReason } from './registry';
import { EnvelopeStream, fromPlainText, initialStream, migrate, parseDocument, parseFence, reduce, splitReply, type StreamEvent, type StreamState } from './protocol';
import { Dispatcher, formMessage, type ActionEnv, type AuditEntry } from './actions';
import { safeFilePath, safeHttpUrl, safeInternalPath } from './safety';
import { ALL_BLOCKS, INVALID_BLOCKS, SAMPLE_CONVERSATION } from './fixtures';

describe('variants', () => {
  it('every component variant is part of its family vocabulary', () => {
    const all = new Set(Object.values(FAMILY_VARIANTS).flat() as string[]);
    for (const [type, list] of Object.entries(COMPONENT_VARIANTS)) for (const v of list) expect(all.has(v), `${type}:${v}`).toBe(true);
  });
  it('rejects meaningless combinations', () => {
    expect(checkCombination({ type: 'metric_card', variant: 'stacked' })).toMatch(/no variant/);
    expect(checkCombination({ type: 'bar_chart', variant: 'stacked', seriesCount: 1 })).toMatch(/two series/);
    expect(checkCombination({ type: 'bar_chart', variant: 'stacked', seriesCount: 2 })).toBeNull();
    expect(checkCombination({ type: 'metric_card', expansion: 'full-screen' })).toMatch(/full-screen/);
    expect(checkCombination({ type: 'text', interaction: 'editable' })).toMatch(/not editable/);
    expect(checkCombination({ type: 'info_card', appearance: 'ghost', emphasis: 'prominent' })).toMatch(/ghost/);
    expect(checkCombination({ type: 'nope' })).toMatch(/unknown/);
  });
});

describe('schemas', () => {
  it('accepts every fixture block', () => { for (const b of ALL_BLOCKS) { const r = parseBlock(b); expect(r.ok, JSON.stringify(r)).toBe(true); } });
  it('has one schema per implemented type and applies defaults', () => {
    const r = parseBlock({ id: 'h', type: 'heading', props: { text: 'Hi' } }); expect(r.ok && (r.block.props as any).level).toBe(3);
    expect(IMPLEMENTED_TYPES.length).toBe(new Set(IMPLEMENTED_TYPES).size);
  });
  it.each(INVALID_BLOCKS)('refuses %s', (_n, raw) => { expect(parseBlock(raw).ok).toBe(false); });
  it('bounds nesting depth', () => {
    const leaf = { id: 'l', type: 'text', props: { content: 'x' } };
    const wrap = (id: string, inner: unknown) => ({ id, type: 'section', props: { blocks: [inner] } });
    expect(parseBlock(wrap('s1', wrap('s2', leaf))).ok).toBe(true);
    expect(parseBlock(wrap('s1', wrap('s2', wrap('s3', leaf)))).ok).toBe(false);
    expect(treeShape([wrap('s1', leaf)]).count).toBe(2);
  });
  it('validates actions against the allowlist', () => {
    expect(actionSchema.safeParse({ kind: 'agent.request', message: 'Compare these two' }).success).toBe(true);
    expect(actionSchema.safeParse({ kind: 'shell.run', cmd: 'rm -rf /' }).success).toBe(false);
    expect(actionSchema.safeParse({ kind: 'agent.approve', planBlockId: 'p1', phaseId: 'deploy', extra: 1 }).success).toBe(false);
    expect(actionSchema.safeParse({ kind: 'file.download', path: '../x' }).success).toBe(false);
  });
  it('presentation plan is advisory and bounded', () => {
    const ok = { advisory: true, blocks: [{ blockId: 'trend', componentId: 'line_chart', purpose: 'Show the revenue trend', dataRequirements: ['monthly revenue'] }] };
    expect(presentationPlanSchema.safeParse(ok).success).toBe(true);
    expect(presentationPlanSchema.safeParse({ ...ok, advisory: false }).success).toBe(false);
    expect(presentationPlanSchema.safeParse({ ...ok, blocks: [] }).success).toBe(false);
    expect(presentationPlanSchema.safeParse({ ...ok, props: { rows: [1] } }).success).toBe(false);   // JEV never supplies data
  });
});

describe('safety helpers', () => {
  it('urls and paths', () => {
    expect(safeHttpUrl('https://example.com/a?b=1')).toBeTruthy(); expect(safeHttpUrl('data:text/html,hi')).toBeNull(); expect(safeHttpUrl('//evil')).toBeNull();
    expect(safeInternalPath('/chat/abc')).toBe('/chat/abc'); expect(safeInternalPath('/admin')).toBeNull(); expect(safeInternalPath('/chat/../admin')).toBeNull(); expect(safeInternalPath('//evil.com')).toBeNull();
    expect(safeFilePath('reports/a.csv')).toBe('reports/a.csv'); expect(safeFilePath('/abs')).toBeNull(); expect(safeFilePath('a/../b')).toBeNull(); expect(safeFilePath('file:x')).toBeNull();
  });
});

describe('manifest and registry', () => {
  it('has unique ids and covers the brief', () => {
    expect(new Set(MANIFEST.map(e => e.id)).size).toBe(MANIFEST.length);
    expect(MANIFEST.length).toBeGreaterThan(150);
    for (const id of ['markdown', 'sankey', 'gantt', 'kanban', 'weather', 'pull_request_diff', 'approval_request', 'token_cost_monitor']) expect(byId.has(id), id).toBe(true);
  });
  it('every implemented entry has a real renderer (itself or via)', () => {
    for (const e of offerable()) { const t = e.via ?? e.id; expect(IMPLEMENTED_TYPES, e.id).toContain(t); expect(ADAPTER_ONLY.has(t as any), `${e.id} is adapter-only`).toBe(false); }
  });
  it('every offered type is reachable from the manifest, and nothing unbuilt is offered', () => {
    const reachable = new Set(offerable().map(e => e.via ?? e.id)); for (const t of OFFERED) expect(reachable.has(t), t).toBe(true);
    for (const e of MANIFEST.filter(x => x.status === 'planned' || x.status === 'unsupported')) expect(OFFERED as string[]).not.toContain(e.id);
  });
  it('the model catalog lists only offered components', () => {
    const cat = modelCatalog(); for (const t of OFFERED) expect(cat).toContain(`${t}:`);
    for (const t of ADAPTER_ONLY) expect(cat).not.toContain(`${t}:`);
    expect(cat).not.toMatch(/\b(map|kanban|gantt|sankey)\b:/);
    expect(cat.length / 4).toBeLessThan(2600);                     // rough token budget for the always-on catalog (chars/4)
  });
  it('registry entries carry the contract fields', () => {
    for (const t of OFFERED) { const r = REGISTRY[t]; expect(r.useWhen && r.avoidWhen && r.schemaRef && r.rendererKey).toBeTruthy(); expect(r.supportedActions).not.toContain('file.download'); }
    expect(schemaSummary('metric_card')).toMatch(/label, value/); expect(schemaSummary('nope')).toBeNull(); expect(unsupportedReason('gantt')).toMatch(/planned/);
  });
  it('is searchable', () => { expect(search('kanban')[0].status).toBe('planned'); expect(search('', { status: 'unsupported' }).every(e => e.status === 'unsupported')).toBe(true); });
});

describe('documents and migration', () => {
  it('parses the sample conversation, keeping order and resolving dataRefs', () => {
    const d = parseDocument(SAMPLE_CONVERSATION); if ('error' in d) throw new Error(d.error);
    expect(d.slots.map(s => s.id)).toEqual(['intro', 'metric', 'trend', 'compare', 'approval', 'next']); expect(d.issues).toEqual([]);
  });
  it('one bad block does not hide the rest, and keeps useful fallback text', () => {
    const d = parseDocument({ version: '1.0', responseId: 'r', blocks: [{ id: 'a', type: 'text', props: { content: 'ok' } }, { id: 'b', type: 'line_chart', props: { title: 'Sales by month', xKey: 'm', series: [] } }, { id: 'c', type: 'divider', props: {} }] });
    if ('error' in d) throw new Error(d.error); expect(d.slots.map(s => s.status)).toEqual(['ready', 'invalid', 'ready']);
    expect((d.slots[1] as any).fallback).toContain('Sales by month');
  });
  it('a dataRef without a dataset is invalid, not a crash', () => {
    const d = parseDocument({ version: '1.0', responseId: 'r', blocks: [{ id: 't', type: 'table', dataRef: 'missing', props: {} }] }); if ('error' in d) throw new Error(d.error);
    expect(d.slots[0].status).toBe('invalid');
  });
  it('drops duplicate block ids and caps block count', () => {
    const blocks = Array.from({ length: 30 }, (_, i) => ({ id: `b${i}`, type: 'divider', props: {} }));
    expect('error' in parseDocument({ version: '1.0', responseId: 'r', blocks })).toBe(true);
    const d = parseDocument({ version: '1.0', responseId: 'r', blocks: [blocks[0], blocks[0]] }); if ('error' in d) throw new Error(d.error); expect(d.slots).toHaveLength(1);
  });
  it('migrates older shapes and refuses unknown majors', () => {
    expect(migrate({ blocks: [] }).ok).toBe(true); expect(migrate({ version: '2.0', blocks: [] }).ok).toBe(false); expect(migrate('x').ok).toBe(false);
    const legacy = fromPlainText('Just a **plain** answer.'); expect(legacy.slots).toHaveLength(1); expect(legacy.slots[0].status).toBe('ready');
  });
  it('splits prose from the fence and hides an unfinished fence', () => {
    const body = '{"version":"1.0","responseId":"r","blocks":[{"id":"d","type":"divider","props":{}}]}';
    const r = splitReply(`Here you go.\n\`\`\`lumina-doc\n${body}\n\`\`\`\nAfter.`); expect(r.prose).toBe('Here you go.\n\nAfter.'); expect(r.open).toBe(false); expect(r.fence).toContain('"blocks"');
    const open = splitReply('Working on it\n```lumina-doc\n{"version":"1.0","blo'); expect(open.open).toBe(true); expect(open.prose).toBe('Working on it');
    expect(splitReply('no fence').fence).toBeNull();
  });
  it('parses a JSON-Lines fence block by block', () => {
    const body = ['{"responseId":"r9"}', '{"dataset":"d1","columns":[{"id":"k","label":"K"},{"id":"v","label":"V","type":"number"}],"rows":[{"k":"a","v":1}]}', '{"id":"t","type":"table","dataRef":"d1","props":{}}', 'not json', '{"id":"x","type":"iframe","props":{}}'].join('\n');
    const d = parseFence(body); if ('error' in d) throw new Error(d.error);
    expect(d.responseId).toBe('r9'); expect(d.slots.map(s => `${s.id}:${s.status}`)).toEqual(['t:ready', 'x:invalid']);
  });
});

const ev = (e: Partial<StreamEvent> & { type: StreamEvent['type'] }, seq: number, responseId = 'r1') => ({ responseId, seq, ...e }) as StreamEvent;
describe('streaming reducer', () => {
  const start = (): StreamState => reduce(initialStream(), ev({ type: 'response.started' }, 0));
  it('streams prose into a stable block, then mounts a validated widget', () => {
    let s = start();
    s = reduce(s, ev({ type: 'block.started', id: 'intro', blockType: 'text' } as any, 1)); s = reduce(s, ev({ type: 'block.delta', id: 'intro', text: 'Hel' } as any, 2)); s = reduce(s, ev({ type: 'block.delta', id: 'intro', text: 'lo' } as any, 3));
    expect((s.slots[0] as any).block.props.content).toBe('Hello');
    s = reduce(s, ev({ type: 'block.started', id: 'm', blockType: 'metric_card' } as any, 4)); expect(s.slots[1].status).toBe('pending');
    s = reduce(s, ev({ type: 'block.completed', id: 'm', block: { id: 'm', type: 'metric_card', props: { label: 'A', value: 1 } } } as any, 5)); expect(s.slots[1].status).toBe('ready');
    s = reduce(s, ev({ type: 'response.completed' }, 6)); expect(s.status).toBe('complete'); expect(s.slots.map(x => x.id)).toEqual(['intro', 'm']);
  });
  it('an invalid completed block becomes a fallback, never a crash', () => {
    let s = start(); s = reduce(s, ev({ type: 'block.completed', id: 'b', block: { id: 'b', type: 'table', props: { title: 'Broken', columns: [] } } } as any, 1));
    expect(s.slots[0].status).toBe('invalid');
  });
  it('ignores duplicates, holds out-of-order events, and ignores other responses', () => {
    let s = start(); const e2 = ev({ type: 'block.started', id: 'x', blockType: 'divider' } as any, 2); const e1 = ev({ type: 'block.started', id: 'w', blockType: 'divider' } as any, 1);
    s = reduce(s, e2); expect(s.slots).toHaveLength(0); expect(s.lastSeq).toBe(0);
    s = reduce(s, e1); expect(s.slots.map(x => x.id)).toEqual(['w', 'x']); expect(s.lastSeq).toBe(2);
    const again = reduce(s, e1); expect(again).toBe(s);
    expect(reduce(s, ev({ type: 'block.started', id: 'z', blockType: 'divider' } as any, 3, 'other'))).toBe(s);
  });
  it('block.updated keeps position and local identity', () => {
    let s = start(); s = reduce(s, ev({ type: 'block.completed', id: 'a', block: { id: 'a', type: 'text', props: { content: 'one' } } } as any, 1));
    s = reduce(s, ev({ type: 'block.completed', id: 'b', block: { id: 'b', type: 'divider', props: {} } } as any, 2));
    s = reduce(s, ev({ type: 'block.updated', id: 'a', block: { id: 'a', type: 'text', props: { content: 'two' } } } as any, 3));
    expect(s.slots.map(x => x.id)).toEqual(['a', 'b']); expect((s.slots[0] as any).block.props.content).toBe('two');
  });
  it('error keeps what arrived and reports retriable; pending widgets degrade on completion', () => {
    let s = start(); s = reduce(s, ev({ type: 'block.started', id: 'c', blockType: 'bar_chart' } as any, 1)); s = reduce(s, ev({ type: 'response.completed' }, 2));
    expect(s.slots[0].status).toBe('invalid');
    let t = start(); t = reduce(t, ev({ type: 'block.completed', id: 'a', block: { id: 'a', type: 'divider', props: {} } } as any, 1)); t = reduce(t, ev({ type: 'response.error', message: 'dropped', retriable: true } as any, 2));
    expect(t.status).toBe('error'); expect(t.error?.retriable).toBe(true); expect(t.slots).toHaveLength(1);
  });
  it('a retry starts a fresh response and a replayed older start is ignored', () => {
    let s = start(); s = reduce(s, ev({ type: 'response.error', message: 'x', retriable: true } as any, 1));
    const r2 = reduce(s, ev({ type: 'response.started' }, 0, 'r2')); expect(r2.status).toBe('streaming'); expect(r2.responseId).toBe('r2');
  });
});

describe('text-first envelope', () => {
  const doc = ['Short answer first.', '```lumina-doc', '{"dataset":"d","columns":[{"id":"k","label":"K"},{"id":"v","label":"V","type":"number"}],"rows":[{"k":"a","v":1},{"k":"b","v":2}]}', '{"id":"t","type":"table","dataRef":"d","props":{"title":"T"}}', '{"id":"n","type":"follow_up","props":{"suggestions":["Go on"]}}', '```', 'Done.'].join('\n');
  const run = (chunks: string[]) => { const es = new EnvelopeStream('r1'); let s = initialStream(); for (const c of chunks) for (const e of es.feed(c)) s = reduce(s, e); for (const e of es.finish()) s = reduce(s, e); return s; };
  it('gives the same result for any chunking, including one character at a time', () => {
    const whole = run([doc]); const bytes = run(doc.split('')); expect(JSON.stringify(bytes.slots)).toBe(JSON.stringify(whole.slots));
    expect(whole.slots.map(x => `${x.id}:${x.status}`)).toEqual(['prose-0:ready', 't:ready', 'n:ready', 'prose-1:ready']);
  });
  it('shows prose before the fence is complete and never leaks fence text', () => {
    const es = new EnvelopeStream('r1'); let s = initialStream(); for (const e of es.feed('Hello wor')) s = reduce(s, e);
    expect((s.slots[0] as any).block.props.content).toBe('Hello wor');
    for (const e of es.feed('ld\n```lumina-doc\n{"id":"t","type":"tab')) s = reduce(s, e);
    expect(s.slots.map(x => x.id)).toEqual(['prose-0']); expect(JSON.stringify(s.slots)).not.toContain('lumina-doc');
  });
  it('text-only replies produce exactly one text block (fast path)', () => {
    const s = run(['Just a plain answer, ', 'nothing fancy.']); expect(s.slots).toHaveLength(1); expect((s.slots[0] as any).block.props.content).toBe('Just a plain answer, nothing fancy.');
  });
});

describe('action dispatcher', () => {
  function setup(over: Partial<ActionEnv> = {}, phase: string | null = 'awaiting_approval') {
    const audit: AuditEntry[] = []; let t = 1_000_000;
    const env: ActionEnv = { local: vi.fn(() => true), send: vi.fn(async () => {}), phase: vi.fn(async () => {}), retryRequest: vi.fn(async () => {}), navigate: vi.fn(), download: vi.fn(async () => {}),
      phaseState: vi.fn(() => phase as any), confirm: vi.fn(async () => true), audit: e => audit.push(e), now: () => (t += 10), ...over };
    return { env, audit, d: new Dispatcher(env, { scope: 'blk1' }) };
  }
  it('refuses anything outside the allowlist, with an audit entry and no side effect', async () => {
    const { env, d, audit } = setup(); const r = await d.dispatch({ kind: 'shell.run' }); expect(r).toMatchObject({ ok: false, reason: 'invalid' }); expect(audit[0].outcome).toBe('refused');
    expect(env.send).not.toHaveBeenCalled();
  });
  it('approve needs the live state to say awaiting_approval, asks first, then calls the host once', async () => {
    const { env, d } = setup(); const a = { kind: 'agent.approve', planBlockId: 'p1', phaseId: 'deploy' };
    expect(await d.dispatch(a)).toEqual({ ok: true }); expect(env.confirm).toHaveBeenCalledTimes(1); expect(env.phase).toHaveBeenCalledWith('p1', 'deploy', 'approve', expect.stringMatching(/^gen/));
    expect(await d.dispatch(a)).toMatchObject({ ok: false, reason: 'duplicate' }); expect(env.phase).toHaveBeenCalledTimes(1);
  });
  it.each([['completed'], ['running'], [null]])('approve is forbidden when the phase is %s', async st => {
    const { env, d } = setup({}, st); expect(await d.dispatch({ kind: 'agent.approve', planBlockId: 'p1', phaseId: 'deploy' })).toMatchObject({ ok: false, reason: 'forbidden' }); expect(env.phase).not.toHaveBeenCalled();
  });
  it('a declined confirmation does nothing and can be retried later', async () => {
    const answers = [false, true]; const { env, d } = setup({ confirm: vi.fn(async () => answers.shift()!) }); const a = { kind: 'agent.deny', planBlockId: 'p1', phaseId: 'deploy' };
    expect(await d.dispatch(a)).toMatchObject({ ok: false, reason: 'declined' }); expect(env.phase).not.toHaveBeenCalled();
    expect(await d.dispatch(a)).toEqual({ ok: true }); expect(env.phase).toHaveBeenCalledWith('p1', 'deploy', 'skip', expect.any(String));
  });
  it('retry only for a failed phase; a host failure releases the idempotency claim', async () => {
    const fail = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(undefined);
    const { d } = setup({ phase: fail }, 'failed'); const a = { kind: 'agent.retry', planBlockId: 'p1', phaseId: 'checks' };
    expect(await d.dispatch(a)).toMatchObject({ ok: false, reason: 'failed' }); expect(await d.dispatch(a)).toEqual({ ok: true });
    const { env: e2, d: d2 } = setup({}, 'running'); expect(await d2.dispatch(a)).toMatchObject({ reason: 'forbidden' }); expect(e2.phase).not.toHaveBeenCalled();
  });
  it('requests send exactly the validated words; the same request in the same scope is one effect', async () => {
    const { env, d } = setup(); const a = { kind: 'agent.request', message: 'Compare these two in detail' };
    await d.dispatch(a); expect(env.send).toHaveBeenCalledWith('Compare these two in detail', expect.any(String)); expect(await d.dispatch(a)).toMatchObject({ reason: 'duplicate' });
  });
  it('rate limits consequential actions', async () => {
    const { d } = setup(); const results = []; for (let i = 0; i < 10; i++) results.push(await d.dispatch({ kind: 'agent.request', message: `Question number ${i}` }));
    expect(results.filter(r => !r.ok && r.reason === 'rate_limited').length).toBe(2);
  });
  it('internal navigation is allowlisted; local actions need a target in the document', async () => {
    const { env, d } = setup({ local: vi.fn(() => false) }); expect(await d.dispatch({ kind: 'navigate.internal', path: '/admin' })).toMatchObject({ reason: 'forbidden' }); expect(env.navigate).not.toHaveBeenCalled();
    expect(await d.dispatch({ kind: 'navigate.internal', path: '/tasks' })).toEqual({ ok: true }); expect(env.navigate).toHaveBeenCalledWith('/tasks');
    expect(await d.dispatch({ kind: 'local.expand', target: 'ghost', expanded: true })).toMatchObject({ ok: false });
  });
  it('destructive button styling forces a confirmation', async () => {
    const { env, d } = setup(); await d.dispatch({ kind: 'agent.request', message: 'Delete the draft' }, { destructiveStyle: true }); expect(env.confirm).toHaveBeenCalled();
  });
  it('formMessage builds the sent text from answered fields only', () => {
    expect(formMessage('Here are my choices:', [{ label: 'Kind', value: 'A' }, { label: 'Skipped', value: '' }])).toBe('Here are my choices:\n- Kind: A');
  });
});
void blockSchema;
