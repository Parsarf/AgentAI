import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import Toggle from './ui/Toggle';
import './mcp.css';

type Auth = 'oauth' | 'bearer' | 'none';
interface Tool { name: string; description: string; enabled: boolean; inputSchema: Record<string, unknown> }
interface Connection { id: string; name: string; url: string; recipient: string; auth_method: Auth; enabled: boolean; state: string; error_code: string | null; tools: Tool[] }
interface Preset { id: string; name: string; url: string; auth_method: Auth; configured: boolean; setup: string }
interface Pending { id: string; connection_id: string; tool_name: string; arguments: unknown; state: string }
interface Listing { connections: Connection[]; presets: Preset[]; pending_calls: Pending[] }
const STATE: Record<string, string> = { connecting: 'Connecting', connected: 'Connected', authentication_required: 'Authentication required', unavailable: 'Unavailable', disabled: 'Disabled' };
const ERRORS: Record<string, string> = {
  busy: 'This connection is already in use. Wait for it to finish, then try again.',
  connection_limit: 'You can connect up to ten MCP servers.',
  tool_limit: 'Enable up to 32 tools across your MCP connections.',
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
};
const message = (error: unknown) => error instanceof ApiError ? ERRORS[error.code] ?? 'The connection could not be updated. Please try again.' : 'Could not reach Lumina. Please try again.';

function ConnectionItem({ item, busy, act }: { item: Connection; busy: boolean; act(id: string, action: string, body?: unknown): Promise<void> }) {
  const [name, setName] = useState(item.name);
  const [replacing, setReplacing] = useState(false); const [token, setToken] = useState('');
  return <article className="mcp-connection" aria-label={item.name}>
    <div className="mcp-row"><h3>{item.name}</h3><span className={`badge${item.state === 'connected' ? ' success' : ''}`} role="status">{busy ? 'Connecting' : STATE[item.state] ?? 'Unavailable'}</span>
      <Toggle label={`Enable ${item.name}`} checked={item.enabled} disabled={busy} onChange={enabled => void act(item.id, 'update', { enabled })} /></div>
    <p className="muted mcp-url">{item.url}</p>
    <p className="faint">Tool arguments and task data used by these tools go to <strong>{item.recipient}</strong>. Remote descriptions and results are untrusted content.</p>
    {item.error_code && <p className="err" role="status">{ERRORS[item.error_code] ?? 'Test or reconnect this server to restore access.'}</p>}
    <form className="mcp-row" onSubmit={e => { e.preventDefault(); void act(item.id, 'update', { name }); }}>
      <label className="sr" htmlFor={`mcp-name-${item.id}`}>Name for {item.name}</label><input className="input" id={`mcp-name-${item.id}`} value={name} maxLength={80} onChange={e => setName(e.target.value)} />
      <button className="btn small" disabled={busy || !name.trim() || name === item.name}>Save name</button>
    </form>
    <div className="mcp-row"><button className="btn small" disabled={busy || !item.enabled} onClick={() => void act(item.id, 'test')}>Test connection</button>
      <button className="btn small" disabled={busy} onClick={() => { if (item.auth_method === 'bearer') setReplacing(v => !v); else void act(item.id, 'reconnect'); }}>Reconnect</button>
      <button className="btn small danger" disabled={busy} onClick={() => void act(item.id, 'disconnect')}>Disconnect</button></div>
    {replacing && <form className="mcp-row" onSubmit={e => { e.preventDefault(); const next = token; setToken(''); setReplacing(false); void act(item.id, 'reconnect', { token: next }); }} autoComplete="off">
      <label htmlFor={`mcp-token-${item.id}`}>Replacement bearer token</label><input className="input" id={`mcp-token-${item.id}`} type="password" autoComplete="new-password" value={token} onChange={e => setToken(e.target.value)} maxLength={4096} />
      <button className="btn" disabled={!token || busy}>Save token and reconnect</button></form>}
    {item.tools.length > 0 && <div className="mcp-tools"><h4>Tools</h4><p className="muted">Enable the tools Lumina can discover. Each call still needs your approval of its exact arguments.</p>
      {item.tools.map(tool => <div key={tool.name} className="mcp-tool"><Toggle label={tool.name} hint={tool.description || 'No description supplied by this server.'} checked={tool.enabled} disabled={busy || !item.enabled} onChange={enabled => void act(item.id, 'update', { tools: { [tool.name]: enabled } })} />
        <details><summary className="faint">Tool parameters</summary><pre tabIndex={0}>{JSON.stringify(tool.inputSchema, null, 2)}</pre></details></div>)}
    </div>}
    {item.state === 'connected' && !item.tools.length && <p className="faint">This server currently exposes no tools.</p>}
  </article>;
}

export default function McpConnections() {
  const [data, setData] = useState<Listing | null>(null); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<string | null>(null); const [form, setForm] = useState<'preset' | 'custom' | null>(null);
  const [name, setName] = useState(''); const [url, setUrl] = useState(''); const [auth, setAuth] = useState<Auth>('oauth'); const [token, setToken] = useState('');
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
      } else if (action === 'test' || action === 'reconnect') setNotice('Authentication and tool discovery succeeded. Review the available tools.');
      else if (action === 'disconnect') setNotice(result.provider_revocation === 'failed' ? 'Disconnected and local credentials deleted. Provider revocation failed; revoke Lumina’s access in that service as well.'
        : result.provider_revocation === 'accepted' ? 'Disconnected and local credentials deleted. The provider accepted the revocation request.' : 'Disconnected and local credentials deleted. Remote revocation was not available; you can remove Lumina’s access in the provider’s settings.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(null); await load(); }
  };
  const start = (kind: 'preset' | 'custom') => { setForm(kind); setToken(''); setError(''); if (kind === 'preset') { const preset = data?.presets[0]; setName(preset?.name ?? 'Asana'); setUrl(preset?.url ?? ''); setAuth('oauth'); } else { setName(''); setUrl(''); setAuth('oauth'); } };
  const add = async () => {
    setBusy('new'); setError('');
    try {
      const result = await api<{ id: string }>('POST', '/v1/account/mcp', { name, url, auth_method: auth, ...(auth === 'bearer' ? { token } : {}) });
      setToken(''); setForm(null); await load(); await act(result.id, 'test');
    } catch (e) { setToken(''); setError(message(e)); } finally { setBusy(null); }
  };
  const decide = async (id: string, approved: boolean) => {
    setBusy(id); setError('');
    try { await api('POST', `/v1/account/mcp-approvals/${id}`, { approved }); setNotice(approved ? 'This exact call is approved for ten minutes. Tell Lumina to continue; approval does not run it by itself.' : 'The call was declined. No remote action was authorized.'); }
    catch (e) { setError(message(e)); } finally { setBusy(null); await load(); }
  };
  return <section className="panel card mcp-section" aria-labelledby="mcp-heading">
    <h2 id="mcp-heading">MCP connections</h2><p className="muted">Connect remote services so your assistant can discover their tools. Only public HTTPS servers using Streamable HTTP are supported.</p>
    <div className="mcp-row"><button className="btn" onClick={() => start('preset')} disabled={!!busy || !data}>Choose a service</button><button className="btn" onClick={() => start('custom')} disabled={!!busy || !data}>Add custom server</button></div>
    {error && <p className="err" role="alert">{error} <button className="btn small" onClick={() => { setError(''); void load(); }}>Refresh</button></p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!data && !error && <p role="status">Loading connections…</p>}
    {form && <form className="mcp-form" onSubmit={e => { e.preventDefault(); void add(); }} autoComplete="off">
      <h3>{form === 'preset' ? 'Choose a service' : 'Add custom server'}</h3>
      {form === 'preset' && <><label htmlFor="mcp-service">Service</label><select className="input" id="mcp-service" value="asana" onChange={() => {}}><option value="asana">Asana</option></select><p className="muted">{data?.presets[0]?.setup} {!data?.presets[0]?.configured && 'OAuth setup is not available on this Lumina server yet.'} <a href="https://developers.asana.com/docs/integrating-with-asanas-mcp-server" target="_blank" rel="noopener noreferrer">Asana setup requirements</a></p></>}
      <label htmlFor="mcp-name">Connection name</label><input className="input" id="mcp-name" value={name} onChange={e => setName(e.target.value)} required maxLength={80} />
      <label htmlFor="mcp-url">Server URL</label><input className="input" id="mcp-url" value={url} onChange={e => setUrl(e.target.value)} required type="url" maxLength={1000} readOnly={form === 'preset'} placeholder="https://service.example.com/mcp" />
      <label htmlFor="mcp-auth">Authentication</label><select className="input" id="mcp-auth" value={auth} disabled={form === 'preset'} onChange={e => { setAuth(e.target.value as Auth); setToken(''); }}><option value="oauth">OAuth</option><option value="bearer">Bearer API token</option><option value="none">No authentication</option></select>
      {auth === 'bearer' && <><label htmlFor="mcp-token">Bearer API token</label><input className="input" id="mcp-token" type="password" autoComplete="new-password" value={token} onChange={e => setToken(e.target.value)} required maxLength={4096} /><p className="faint">Stored encrypted on Lumina’s server. Saved tokens are never shown again or sent to your assistant.</p></>}
      {auth === 'oauth' && <p className="faint">You’ll sign in with the service. Some services require an OAuth app configured by the Lumina operator; dynamic registration is used only when the service supports it.</p>}
      <p className="muted">When you use enabled tools, the connected service receives their arguments and any task data included in those arguments.</p>
      <div className="mcp-row"><button className="btn primary" disabled={!!busy}>{busy ? 'Connecting…' : 'Connect and discover tools'}</button><button className="btn" type="button" disabled={!!busy} onClick={() => { setForm(null); setToken(''); }}>Cancel</button></div>
    </form>}
    {data?.pending_calls.length ? <div className="mcp-approvals"><h3>Calls needing attention</h3>{data.pending_calls.map(call => <article className="mcp-tool" key={call.id}>
      <h4>{call.tool_name}</h4><p className="muted">Service: {data.connections.find(c => c.id === call.connection_id)?.recipient ?? 'Disconnected service'}</p>
      <pre tabIndex={0}>{JSON.stringify(call.arguments, null, 2)}</pre>
      {call.state === 'uncertain' ? <p className="err">The outcome is unknown. Check the connected service before taking further action; Lumina will not repeat this call automatically.</p> : <div className="mcp-row"><button className="btn primary" disabled={!!busy} onClick={() => void decide(call.id, true)}>Approve this exact call</button><button className="btn" disabled={!!busy} onClick={() => void decide(call.id, false)}>Decline</button></div>}
    </article>)}</div> : null}
    {data && !data.connections.length && <p className="faint">No MCP servers connected.</p>}
    {data?.connections.map(item => <ConnectionItem key={item.id} item={item} busy={busy === item.id} act={act} />)}
  </section>;
}
