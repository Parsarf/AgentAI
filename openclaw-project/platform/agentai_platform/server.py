from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import signal
import threading
from urllib.parse import urlsplit
from . import __version__
from .config import Config
from .security import DenyIdentity, Forbidden, NotFound, log_request, request_id
from .store import Store

class BoundedServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, address, handler, *, config, store, service, identity=None):
        self.config=config;self.store=store;self.service=service
        self.identity=identity if identity is not None else DenyIdentity()
        self.slots=threading.BoundedSemaphore(config.max_connections)
        super().__init__(address,handler)
    def get_request(self):
        conn,addr=super().get_request();conn.settimeout(self.config.socket_timeout_seconds);return conn,addr
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False): self.shutdown_request(request);return
        try: super().process_request(request,client_address)
        except Exception: self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try: super().process_request_thread(request,client_address)
        finally: self.slots.release()
    def handle_error(self,request,client_address):
        logging.getLogger("agentai").error('{"event":"connection_error"}')

class Handler(BaseHTTPRequestHandler):
    server_version="AgentAI/0.1";sys_version=""
    def log_message(self,*args): pass
    def _reply(self,status,payload,route,rid):
        body=json.dumps(payload,separators=(",",":"),ensure_ascii=True).encode()
        self.send_response(status)
        for name,value in {"Content-Type":"application/json; charset=utf-8","Content-Length":str(len(body)),"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'","X-Request-ID":rid,"Connection":"close"}.items(): self.send_header(name,value)
        self.end_headers();self.wfile.write(body);self.close_connection=True
        log_request(self.server.service,rid,status,route)
    def _dispatch(self):
        rid=request_id();path=urlsplit(self.path).path;route="unknown"
        if self.headers.get("Transfer-Encoding") or len(self.path)>2048:
            return self._reply(400,{"error":"invalid_request"},route,rid)
        try: size=int(self.headers.get("Content-Length","0"))
        except ValueError: size=-1
        if size<0 or size>self.server.config.max_body_bytes: return self._reply(413,{"error":"request_size"},route,rid)
        allowed_hosts={f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed_hosts: return self._reply(403,{"error":"origin_denied"},route,rid)
        if self.headers.get("Origin") not in {None,*["http://"+x for x in allowed_hosts]}: return self._reply(403,{"error":"origin_denied"},route,rid)
        if self.command=="GET" and path=="/healthz":
            return self._reply(200,{"status":"alive","service":self.server.service,"version":__version__},"health",rid)
        if self.command=="GET" and path=="/readyz":
            ready=self.server.store.ready()
            return self._reply(200 if ready else 503,{"foundation_ready":ready,"customer_ready":False,"identity":"disabled","execution":"disabled"},"readiness",rid)
        if path.startswith("/v1/"):
            # No account identity is taken from URL, headers or body.
            principal=self.server.identity.verify(self.headers.get("Cookie"))
            if principal is None: return self._reply(401,{"error":"authentication_required"},route,rid)
            try:
                if self.server.service=="app" and self.command=="GET" and path=="/v1/projects":
                    return self._reply(200,{"items":self.server.store.list_projects(principal)},"projects",rid)
                if self.server.service=="app" and self.command=="GET" and path.startswith("/v1/projects/"):
                    project_id=path[len("/v1/projects/"):]
                    if not project_id or "/" in project_id: raise NotFound()
                    return self._reply(200,self.server.store.get_project(principal,project_id),"projects",rid)
                if self.server.service=="control":
                    # Phase 4 requires separate service authentication and fixed operations.
                    return self._reply(503,{"error":"provisioning_disabled"},"operation",rid)
                return self._reply(503,{"error":"capability_disabled"},route,rid)
            except (NotFound,Forbidden): return self._reply(404,{"error":"not_found"},"projects",rid)
            except Exception: return self._reply(503,{"error":"service_unavailable"},route,rid)
        return self._reply(404,{"error":"not_found"},route,rid)
    do_GET=_dispatch
    do_POST=_dispatch
    do_DELETE=_dispatch
    do_PATCH=_dispatch
    do_PUT=_dispatch
    def do_OPTIONS(self): self._reply(405,{"error":"method_not_allowed"},"unknown",request_id())

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--service",choices=("app","control"),required=True)
    parser.add_argument("--check",action="store_true");parser.add_argument("--migrate",action="store_true")
    args=parser.parse_args();config=Config.load(args.config)
    store=Store(config.state_dir / "platform.sqlite3")
    if args.migrate: store.initialize()
    if args.check:
        if not store.ready(): raise SystemExit("schema/readiness check failed; run explicit --migrate first")
        print(json.dumps({"config":"valid","schema":"current","customer_ready":False}));return
    if not store.ready(): raise SystemExit("database not migrated; refusing startup")
    logging.basicConfig(level=logging.INFO,format="%(message)s")
    server=BoundedServer((config.bind,config.app_port if args.service=="app" else config.control_port),Handler,config=config,store=store,service=args.service)
    def stop(signum,frame): threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try: server.serve_forever(poll_interval=0.2)
    finally: server.server_close()

if __name__=="__main__": main()
