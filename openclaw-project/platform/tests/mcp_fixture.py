"""Local fixture only: no production setting enables this HTTP/private transport."""
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx2
from agentai_platform.mcp_connections.client import RemoteClient

URL = 'https://fixture.mcp-demo.net/mcp'
ISSUER = 'https://auth.mcp-demo.net'


class Fixture:
    def __init__(self, oauth=False):
        self.oauth = oauth
        self.calls = []; self.sessions_closed = 0; self.initialized = 0; self.token_requests = []
        self.tokens = ['fixture-access-secret', 'rotated-access-secret']
        self.tools = [
            {'name': 'echo', 'description': 'Echo text, <b>untrusted HTML</b>', 'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}},
            {'name': 'write', 'description': 'Record an action', 'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}},
            {'name': 'picture', 'description': 'Return structured/image/error content', 'inputSchema': {'type': 'object', 'properties': {}}},
        ]
        self.reject_call = False; self.reject_refresh = False; self.fail_write = False; self.revocation_status = 200
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args): pass
            def respond(self, status, body=None, **headers):
                data = json.dumps(body).encode() if body is not None else b''
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'application/json')
                for k,v in headers.items(): self.send_header(k.replace('_','-'), v)
                self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                if 'oauth-protected-resource' in self.path:
                    self.respond(200, {'resource': URL, 'authorization_servers': [ISSUER]})
                elif 'oauth-authorization-server' in self.path or 'openid-configuration' in self.path:
                    self.respond(200, {'issuer': ISSUER, 'authorization_endpoint': ISSUER+'/authorize', 'token_endpoint': ISSUER+'/token',
                                      'registration_endpoint': ISSUER+'/register', 'revocation_endpoint': ISSUER+'/revoke',
                                      'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code','refresh_token'],
                                      'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none','client_secret_post']})
                else: self.respond(405)
            def do_DELETE(self):
                fixture.sessions_closed += 1; self.respond(200)
            def do_POST(self):
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.path == '/register':
                    value=json.loads(data); self.respond(201, {**value, 'client_id': 'fixture-client', 'client_secret': 'fixture-client-secret'}); return
                if self.path == '/token':
                    from urllib.parse import parse_qs
                    params=parse_qs(data.decode()); fixture.token_requests.append(params)
                    if fixture.reject_refresh and params['grant_type'][0]=='refresh_token': self.respond(400, {'error':'invalid_grant'}); return
                    self.respond(200, {'access_token': fixture.tokens[-1] if params['grant_type'][0]=='refresh_token' else fixture.tokens[0], 'token_type':'Bearer','refresh_token':'fixture-refresh-secret','expires_in':3600}); return
                if self.path == '/revoke': self.respond(fixture.revocation_status); return
                if fixture.oauth and self.headers.get('Authorization') not in ['Bearer '+t for t in fixture.tokens]:
                    self.respond(401, WWW_Authenticate='Bearer resource_metadata="'+URL.rsplit('/mcp',1)[0]+'/.well-known/oauth-protected-resource"'); return
                value=json.loads(data); rid=value.get('id'); method=value.get('method'); params=value.get('params') or {}
                if rid is None: self.respond(202); return
                if method == 'initialize':
                    fixture.initialized += 1
                    result={'protocolVersion':'2025-06-18','serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{'listChanged':True}}}
                elif method == 'tools/list':
                    result={'tools':fixture.tools[1:]} if params.get('cursor') else {'tools':fixture.tools[:1], 'nextCursor':'second'}
                elif method == 'tools/call':
                    fixture.calls.append(params)
                    if fixture.reject_call: self.respond(401); return
                    if params['name']=='write' and fixture.fail_write:
                        self.close_connection=True; self.connection.close(); return
                    if params['name']=='picture':
                        result={'content':[{'type':'text','text':'fixture-access-secret'}, {'type':'image','mimeType':'image/png','data':'iVBORw0KGgo='}], 'structuredContent':{'ok': True}, 'isError':True}
                    else: result={'content':[{'type':'text','text':params['arguments']['text']}], 'structuredContent':{'text':params['arguments']['text']}}
                elif method == 'ping': result={}
                else:
                    self.respond(200, {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'not supported'}}); return
                self.respond(200, {'jsonrpc':'2.0','id':rid,'result':result}, Mcp_Session_Id='fixture-session')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def close(self): self.server.shutdown(); self.server.server_close(); self.thread.join(3)
    def http(self, url):
        fixture=self
        class OnlyFixture(httpx2.AsyncBaseTransport):
            def __init__(self): self.inner=httpx2.AsyncHTTPTransport(retries=0)
            async def handle_async_request(self, request):
                if request.url.host not in ('fixture.mcp-demo.net','auth.mcp-demo.net'): raise ValueError('fixture host not allowed')
                mapped = httpx2.Request(request.method, request.url.copy_with(scheme='http',host='127.0.0.1',port=fixture.server.server_port), headers=request.headers, content=await request.aread(), extensions=request.extensions)
                return await self.inner.handle_async_request(mapped)
            async def aclose(self): await self.inner.aclose()
        return httpx2.AsyncClient(transport=OnlyFixture(),timeout=3,trust_env=False,follow_redirects=False)
    async def validate_authorize(self, url):
        if not url.startswith(ISSUER + '/authorize'): raise ValueError('fixture authorization host')
    def remote(self): return RemoteClient(client_factory=self.http, authorization_validator=self.validate_authorize)
