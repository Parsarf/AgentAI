import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import Toggle from './ui/Toggle';
import Sheet from './ui/Sheet';
import ServiceIcon from './ServiceIcon';
import { argumentLine as summary } from '../lib/work';
import { Plus, Search, Edit } from './Icons';
import './integrations.css';

type Auth = 'oauth' | 'bearer' | 'none';
interface Tool { name: string; description: string; enabled: boolean; auto_approve?: boolean; inputSchema: Record<string, unknown>; unusable?: string | null }
interface Connection { id: string; name: string; url: string; recipient: string; auth_method: Auth; enabled: boolean; state: string; error_code: string | null; tools: Tool[] }
interface Preset { id: string; name: string; url: string; auth_method: Auth; configured: boolean; setup: string }
interface Pending { id: string; connection_id: string; tool_name: string; arguments: unknown; state: string }
interface Listing { connections: Connection[]; presets: Preset[]; pending_calls: Pending[] }
const STATE: Record<string, string> = { connecting: 'Connecting…', connected: 'Connected', authentication_required: 'Sign-in needed', unavailable: 'Not reachable', disabled: 'Off' };
const TONE: Record<string, string> = { connected: 'success', authentication_required: 'warning', unavailable: 'danger' };
const ERRORS: Record<string, string> = {
  busy: 'This connection is already in use. Wait for it to finish, then try again.',
  connection_limit: 'You can connect up to ten MCP servers.',
  tool_limit: 'Enable up to 200 tools across your MCP connections.',
  ambiguous_tool: 'More than one connected service has a tool with that name.',
  discovery_limit: 'This server exceeds the supported discovery limit of 100 tools and eight pages.',
  redirect_refused: 'The server redirects. Enter its final public HTTPS URL instead.',
  no_tools: 'The server did not advertise MCP tool support.',
  invalid_token: 'Enter a valid bearer token without spaces.',
  invalid_url: 'Enter a public HTTPS URL. Internal addresses, credentials in URLs, and redirects are not supported.',
  authentication_required: 'The server rejected or expired your authorization. Reconnect to authorize it again.',
  oauth_setup_required: 'This service needs an OAuth app registered by the Lumina operator before you can sign in.',
  timeout: 'The server took too long to respond. Check it and try again.',
  unavailable: 'The server could not complete MCP initialization and tool discovery. Check its URL and availability.',
  oauth_state_invalid: 'Authorization expired or belongs to another browser session. Reconnect to start again.',
  unsupported_schema: 'The server returned a tool schema Lumina cannot safely validate.',
  response_too_large: 'The server response exceeded Lumina’s size limit.',
  tool_changed: 'A tool changed. Test the connection, review its definition, then enable it again.',
  tool_unusable: 'That tool cannot be used. The reason is shown under it.',
};
const message = (error: unknown) => error instanceof ApiError ? ERRORS[error.code] ?? 'The connection could not be updated. Please try again.' : 'Could not reach Lumina. Please try again.';

export const humanize = (tool: string) => { const t = tool.replace(/[_-]+/g, ' ').trim(); return t ? t[0].toUpperCase() + t.slice(1) : tool; };
type Mode = 'off' | 'ask' | 'auto';
const modeOf = (t: Tool): Mode => !t.enabled ? 'off' : t.auto_approve ? 'auto' : 'ask';
const MODES: { id: Mode; label: string }[] = [{ id: 'off', label: 'Off' }, { id: 'ask', label: 'Ask' }, { id: 'auto', label: 'Auto' }];
const modeBody = (name: string, mode: Mode) => mode === 'off' ? { tools: { [name]: false } } : mode === 'ask' ? { tools: { [name]: true }, auto: { [name]: false } } : { tools: { [name]: true }, auto: { [name]: true } };
type Act = (id: string, action: string, body?: unknown) => Promise<void>;

function ToolRow({ tool, locked, onMode }: { tool: Tool; locked: boolean; onMode(mode: Mode): void }) {
  const [open, setOpen] = useState(false); const mode = modeOf(tool);
  return <li className="tool">
    <div className="tool-main">
      <button type="button" className="tool-name" aria-expanded={open} onClick={() => setOpen(v => !v)}><span>{humanize(tool.name)}</span>
        <small>{tool.unusable ? `Can’t be used: ${tool.unusable}` : tool.description || 'No description from this service.'}</small></button>
      {tool.unusable ? <span className="faint">Unavailable</span>
        : <div className="seg" role="radiogroup" aria-label={`${humanize(tool.name)}: how Lumina uses it`}>{MODES.map(m =>
          <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} className="seg-item" data-mode={m.id} disabled={locked} onClick={() => mode !== m.id && onMode(m.id)}>{m.label}</button>)}</div>}
    </div>
    {open && !tool.unusable && <pre tabIndex={0}>{JSON.stringify(tool.inputSchema, null, 2)}</pre>}
  </li>;
}

function ConnectionSheet({ item, busy, act, onClose }: { item: Connection; busy: boolean; act: Act; onClose(): void }) {
  const [name, setName] = useState(item.name); const [renaming, setRenaming] = useState(false);
  const [replacing, setReplacing] = useState(false); const [token, setToken] = useState(''); const [confirm, setConfirm] = useState(false); const [q, setQ] = useState('');
  const on = item.tools.filter(t => t.enabled).length;
  const shown = item.tools.filter(t => !q.trim() || `${t.name} ${t.description}`.toLowerCase().includes(q.trim().toLowerCase()));
  const state = busy ? 'connecting' : item.state;
  const title = <div className="sheet-id"><ServiceIcon name={item.name} url={item.url} size="lg" />
    <div>{renaming
      ? <form className="name-edit" onSubmit={e => { e.preventDefault(); setRenaming(false); void act(item.id, 'update', { name }); }}><label className="sr" htmlFor={`mcp-name-${item.id}`}>Name</label><input className="input" id={`mcp-name-${item.id}`} value={name} maxLength={80} autoFocus onChange={e => setName(e.target.value)} /><button className="btn small primary" disabled={busy || !name.trim()}>Save</button></form>
      : <h2>{item.name}<button type="button" className="iconbtn small" aria-label="Rename" onClick={() => setRenaming(true)}><Edit /></button></h2>}
      <p className="host">{item.recipient}</p></div></div>;
  return <Sheet title={title} onClose={onClose} footer={<>
    <p className="faint">What you ask Lumina to do with these tools is shared with {item.recipient}.</p>
    {confirm ? <div className="int-row"><span>Disconnect {item.name}?</span><button className="btn small danger" disabled={busy} onClick={() => void act(item.id, 'disconnect').then(onClose)}>Yes, disconnect</button><button className="btn small" onClick={() => setConfirm(false)}>Keep</button></div>
      : <button className="btn small tertiary danger-text" disabled={busy} onClick={() => setConfirm(true)}>Disconnect</button>}</>}>
    <div className="status-row"><span className={`badge ${TONE[state] ?? 'alt'}`} role="status"><i className="status-dot" />{STATE[state] ?? 'Not reachable'}</span>
      <Toggle label={`Turn ${item.name} on`} checked={item.enabled} disabled={busy} onChange={enabled => void act(item.id, 'update', { enabled })} /></div>
    {item.error_code && <div className="notice warning" role="status"><p>{ERRORS[item.error_code] ?? 'Test or reconnect this service to restore access.'}</p></div>}
    <div className="int-row"><button className="btn small" disabled={busy || !item.enabled} onClick={() => void act(item.id, 'test')}>Check connection</button>
      <button className="btn small" disabled={busy} onClick={() => { if (item.auth_method === 'bearer') setReplacing(v => !v); else void act(item.id, 'reconnect'); }}>{item.auth_method === 'bearer' ? 'New token' : 'Sign in again'}</button></div>
    {replacing && <form className="int-row" onSubmit={e => { e.preventDefault(); const next = token; setToken(''); setReplacing(false); void act(item.id, 'reconnect', { token: next }); }} autoComplete="off">
      <label className="sr" htmlFor={`mcp-token-${item.id}`}>Replacement bearer token</label><input className="input" id={`mcp-token-${item.id}`} type="password" autoComplete="new-password" placeholder="New API token" value={token} onChange={e => setToken(e.target.value)} maxLength={4096} />
      <button className="btn small primary" disabled={!token || busy}>Save</button></form>}
    {item.tools.length > 0 && <section aria-labelledby={`tools-${item.id}`}>
      <div className="tools-head"><h3 id={`tools-${item.id}`}>What Lumina can do</h3><span className="faint">{on} of {item.tools.length} on</span></div>
      <p className="legend"><b>Off</b> not available · <b>Ask</b> you approve each use · <b>Auto</b> runs right away</p>
      {item.tools.length > 6 && <label className="search"><Search /><span className="sr">Search tools</span><input className="input" placeholder="Search tools" value={q} onChange={e => setQ(e.target.value)} /></label>}
      <ul className="tools">{shown.map(t => <ToolRow key={t.name} tool={t} locked={busy || !item.enabled} onMode={mode => void act(item.id, 'update', modeBody(t.name, mode))} />)}
        {!shown.length && <li className="faint">Nothing matches “{q}”.</li>}</ul></section>}
    {item.state === 'connected' && !item.tools.length && <p className="faint">This service has no tools to offer.</p>}
  </Sheet>;
}

function AddSheet({ data, busy, onClose, onAdd }: { data: Listing | null; busy: boolean; onClose(): void; onAdd(v: { name: string; url: string; auth: Auth; token: string }): Promise<void> }) {
  const preset = data?.presets[0];
  const [mode, setMode] = useState<'pick' | 'custom'>('pick');
  const [name, setName] = useState(''); const [url, setUrl] = useState(''); const [auth, setAuth] = useState<Auth>('oauth'); const [token, setToken] = useState('');
  if (mode === 'pick') return <Sheet title="Choose a service" onClose={onClose}>
    <div className="pick">
      {preset && <button type="button" className="pick-item" disabled={busy || !preset.configured} onClick={() => void onAdd({ name: preset.name, url: preset.url, auth: 'oauth', token: '' })}>
        <ServiceIcon name={preset.name} url={preset.url} size="lg" /><span><b>{preset.name}</b><small>{preset.configured ? 'Sign in with Asana' : 'Not set up on this Lumina yet'}</small></span></button>}
      <button type="button" className="pick-item" disabled={busy} onClick={() => setMode('custom')}><span className="svc svc-lg add"><Plus /></span><span><b>Custom server</b><small>Any MCP server with an HTTPS address</small></span></button>
    </div></Sheet>;
  return <Sheet title="Custom server" onClose={onClose}>
    <form className="stack" autoComplete="off" onSubmit={e => { e.preventDefault(); const t = token; setToken(''); void onAdd({ name, url, auth, token: t }); }}>
      <label htmlFor="mcp-name">Name</label><input className="input" id="mcp-name" value={name} onChange={e => setName(e.target.value)} required maxLength={80} placeholder="My service" />
      <label htmlFor="mcp-url">Server URL</label><input className="input" id="mcp-url" value={url} onChange={e => setUrl(e.target.value)} required type="url" maxLength={1000} placeholder="https://service.example.com/mcp" />
      <span id="mcp-auth-label" className="label">How it signs in</span>
      <div className="seg" role="radiogroup" aria-labelledby="mcp-auth-label">{([['oauth', 'Sign in'], ['bearer', 'API token'], ['none', 'Nothing']] as const).map(([id, label]) =>
        <button key={id} type="button" role="radio" aria-checked={auth === id} className="seg-item" onClick={() => { setAuth(id); setToken(''); }}>{label}</button>)}</div>
      {auth === 'bearer' && <><label htmlFor="mcp-token">API token</label><input className="input" id="mcp-token" type="password" autoComplete="new-password" value={token} onChange={e => setToken(e.target.value)} required maxLength={4096} /><p className="faint">Stored encrypted. Never shown again.</p></>}
      <div className="int-row"><button className="btn primary" disabled={busy}>{busy ? 'Connecting…' : 'Connect'}</button><button className="btn" type="button" onClick={() => setMode('pick')}>Back</button></div>
    </form></Sheet>;
}

export default function McpConnections({ adding, onAdding }: { adding?: boolean; onAdding?(v: boolean): void } = {}) {
  const [data, setData] = useState<Listing | null>(null); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<string | null>(null); const [open, setOpen] = useState<string | null>(null); const [localAdding, setLocalAdding] = useState(false);
  const isAdding = adding ?? localAdding; const setAdding = (v: boolean) => { setLocalAdding(v); onAdding?.(v); };
  const load = useCallback(async () => { try { setData(await api<Listing>('GET', '/v1/account/mcp')); } catch (e) { setError(message(e)); } }, []);
  useEffect(() => { void load(); const timer = setInterval(() => { if (!document.hidden) void load(); }, 5000); return () => clearInterval(timer); }, [load]);
  useEffect(() => { const outcome = new URLSearchParams(window.location.search).get('mcp'); if (outcome === 'authorization_failed') setError('Authorization was declined, expired, or did not match this browser session. Reconnect to try again.'); if (outcome === 'connected') setNotice('Authorization and tool discovery completed. Choose which tools to enable.'); }, []);
  const act = async (id: string, action: string, body: unknown = {}) => {
    setBusy(id); setError(''); setNotice('');
    try {
      const result = await api('POST', `/v1/account/mcp/${id}/${action}`, body);
      if (result.authorize_url) {
        const target = new URL(result.authorize_url);
        if (target.protocol !== 'https:') throw new Error('invalid authorization URL');
        window.location.assign(target.href);
      } else if (action === 'test' || action === 'reconnect') setNotice('Checked. Choose what Lumina may do below.');
      else if (action === 'disconnect') setNotice(result.provider_revocation === 'failed' ? 'Disconnected and local credentials deleted. Provider revocation failed; revoke Lumina’s access in that service as well.'
        : result.provider_revocation === 'accepted' ? 'Disconnected and local credentials deleted. The provider accepted the revocation request.' : 'Disconnected and local credentials deleted. Remote revocation was not available; you can remove Lumina’s access in the provider’s settings.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(null); await load(); }
  };
  const add = async (v: { name: string; url: string; auth: Auth; token: string }) => {
    setBusy('new'); setError('');
    try {
      const result = await api<{ id: string }>('POST', '/v1/account/mcp', { name: v.name, url: v.url, auth_method: v.auth, ...(v.auth === 'bearer' ? { token: v.token } : {}) });
      setAdding(false); await load(); await act(result.id, 'test'); setOpen(result.id);
    } catch (e) { setError(message(e)); } finally { setBusy(null); }
  };
  const decide = async (id: string, approved: boolean) => {
    setBusy(id); setError('');
    try { await api('POST', `/v1/account/mcp-approvals/${id}`, { approved }); setNotice(approved ? 'Approved for ten minutes. Tell Lumina to continue.' : 'Declined. Nothing was run.'); }
    catch (e) { setError(message(e)); } finally { setBusy(null); await load(); }
  };
  const connected = data?.connections.filter(c => c.state === 'connected' && c.enabled).length ?? 0;
  const current = data?.connections.find(c => c.id === open);
  return <section className="mcp" aria-labelledby="mcp-heading">
    <div className="sec-head"><h2 id="mcp-heading">MCP connections</h2>{connected > 0 && <span className="badge success">{connected} connected</span>}</div>
    {error && <div className="notice danger" role="alert"><p>{error}</p><button className="btn small" onClick={() => { setError(''); void load(); }}>Refresh</button></div>}
    {notice && <div className="notice success" role="status"><p>{notice}</p></div>}
    {data?.pending_calls.length ? <div className="wait-list" aria-label="Waiting for you">{data.pending_calls.map(call => {
      const svc = data.connections.find(c => c.id === call.connection_id);
      return <article className="wait-card" key={call.id}>
        <ServiceIcon name={svc?.name ?? 'Service'} url={svc?.url} />
        <div className="wait-text"><b>{humanize(call.tool_name)}</b><small>{svc ? `on ${svc.name}` : 'Disconnected service'} · waiting for you</small>{summary(call.arguments) && <small className="wait-sum">{summary(call.arguments)}</small>}</div>
        {call.state === 'uncertain' ? <small className="err">Outcome unknown. Check {svc?.name ?? 'the service'}.</small>
          : <div className="int-row"><button className="btn small primary" disabled={!!busy} onClick={() => void decide(call.id, true)}>Approve</button><button className="btn small" disabled={!!busy} onClick={() => void decide(call.id, false)}>Decline</button></div>}
        <details className="wait-args"><summary>All details</summary><pre tabIndex={0}>{JSON.stringify(call.arguments, null, 2)}</pre></details>
      </article>; })}</div> : null}
    {!data && !error && <p role="status" className="faint">Loading…</p>}
    {data && <div className="tiles">
      {data.connections.map(c => <button key={c.id} type="button" className="tile" aria-label={`${c.name}, ${STATE[c.enabled ? c.state : 'disabled'] ?? 'Not reachable'}`} onClick={() => setOpen(c.id)}>
        <span className="tile-art"><ServiceIcon name={c.name} url={c.url} /><i className={`status-dot ${c.enabled ? TONE[c.state] ?? 'idle' : 'idle'}`} /></span><span className="tile-label">{c.name}</span></button>)}
      <button type="button" className="tile add" onClick={() => setAdding(true)}><span className="tile-art"><span className="svc add"><Plus /></span></span><span className="tile-label">Custom server</span></button>
    </div>}
    {current && <ConnectionSheet key={current.id} item={current} busy={busy === current.id} act={act} onClose={() => setOpen(null)} />}
    {isAdding && <AddSheet data={data} busy={busy === 'new'} onClose={() => setAdding(false)} onAdd={add} />}
  </section>;
}
