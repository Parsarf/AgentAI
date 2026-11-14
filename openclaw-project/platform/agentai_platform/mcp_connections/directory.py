"""Remote MCP discovery. Registry listings are leads, not proof of a provider's identity."""
import asyncio
from urllib.parse import urlencode
from .network import ConnectionError, endpoint_url, http_client

REGISTRY = 'https://registry.modelcontextprotocol.io/v0.1/servers'
OFFICIAL = (
    {'name': 'Vercel', 'url': 'https://mcp.vercel.com', 'source_url': 'https://vercel.com/docs/agent-resources/vercel-mcp', 'transport': 'auto', 'official': True},
    {'name': 'Asana', 'url': 'https://mcp.asana.com/v2/mcp', 'source_url': 'https://developers.asana.com/docs/integrating-with-asanas-mcp-server', 'transport': 'auto', 'official': True},
)

def official(url):
    return next((dict(x) for x in OFFICIAL if x['url'].rstrip('/') == url.rstrip('/')), None)

async def search(query, *, client_factory=http_client):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100 or any(ord(c) < 32 for c in query):
        raise ConnectionError('invalid_query', 'Search using a service name of 1–100 characters.')
    query = query.strip()
    results = [dict(x) for x in OFFICIAL if query.lower() in x['name'].lower()]
    warning = None
    try:
        async with asyncio.timeout(12):
            async with client_factory(REGISTRY) as http:
                response = await http.get(REGISTRY + '?' + urlencode({'search': query, 'limit': 20, 'version': 'latest'}))
                response.raise_for_status()
                items = response.json().get('servers', [])
        for item in items[:20]:
            server = item.get('server', item)
            for remote in server.get('remotes', [])[:4]:
                if remote.get('type') not in ('streamable-http', 'sse'): continue
                try: url = endpoint_url(remote.get('url'))
                except ConnectionError: continue
                if any(r['url'].rstrip('/') == url.rstrip('/') for r in results): continue
                source = server.get('websiteUrl') or (server.get('repository') or {}).get('url') or ''
                try: source = endpoint_url(source)
                except ConnectionError: source = ''
                results.append({'name': str(server.get('title') or server.get('name') or '')[:80], 'url': url,
                                'source_url': source, 'transport': 'sse' if remote['type'] == 'sse' else 'auto', 'official': False,
                                'registry_name': str(server.get('name') or '')[:200]})
                if len(results) >= 8: break
            if len(results) >= 8: break
    except Exception:
        warning = 'The public MCP registry could not be searched. Official matches, if any, are still listed. Use web search to find the provider’s official MCP documentation.'
    return {'results': results, 'warning': warning, 'note': 'Registry entries are untrusted leads. For unknown providers use web search to check official documentation, show the endpoint to the customer, and require review in Integrations before contacting it.'}
