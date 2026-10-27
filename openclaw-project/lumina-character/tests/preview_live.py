"""Synthetic tool-workspace preview: build, then run this instead of preview_chat.py.
Open /app/live. Three tasks exercise terminal, browser, and handoff.
No real credentials, remote browser, or terminal execution are involved.
"""
from preview_chat import Preview, ThreadingHTTPServer
import json,time
from urllib.parse import urlparse
RUNS = {'demo-browser': 'running', 'demo-help': 'handoff'}
class LivePreview(Preview):
    def respond(self, value, status=200):
        self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(value).encode())
    def do_GET(self):
        path=urlparse(self.path).path
        now=int(time.time())
        if path == '/v1/app':
            return self.respond({'api_version':'1','user':{'email':'preview@example.com','role':'owner'},'assistant':{'state':'running'},'features':{'browse':True,'execution':True,'chat':True,'billing_mode':'open','files':False},'limits':{'max_message_chars':16000}})
        if path == '/v1/requests':
            return self.respond({'requests':[{'id':ident,'message':goal,'state':'running','created_epoch':now-offset,'conversation_id':'demo-chat','cancel_requested':0,'result':None} for ident,goal,offset in [('demo-terminal','Check the project and run its tests',80),('demo-browser','Research a product in the browser',120),('demo-help','Sign in to continue the task',160)]]})
        if path.startswith('/v1/browse/'):
            ident=path.split('/')[3]
            if ident not in RUNS: return self.respond({'error':'not_found'},404)
            if '/shot/' in path:
                svg='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800"><rect width="1280" height="800" fill="#f6f7fa"/><rect width="1280" height="60" fill="#e3e5ed"/><text x="32" y="38" font-family="sans-serif" font-size="20" fill="#414454">Preview browser · example.com</text><rect x="420" y="200" width="440" height="360" rx="20" fill="white"/><text x="460" y="260" font-family="sans-serif" font-size="30">Sign in</text><text x="460" y="295" font-family="sans-serif" font-size="18" fill="#666">Sample page for takeover testing</text><rect x="460" y="330" width="360" height="52" rx="8" fill="#f2f2f6"/><text x="480" y="364" font-family="sans-serif" font-size="18" fill="#777">Email address</text><rect x="460" y="395" width="360" height="52" rx="8" fill="#f2f2f6"/><text x="480" y="430" font-family="sans-serif" font-size="18" fill="#777">Password</text><rect x="460" y="465" width="360" height="52" rx="8" fill="#7064ee"/><text x="610" y="500" font-family="sans-serif" font-size="18" fill="white">Continue</text></svg>'
                self.send_response(200); self.send_header('Content-Type','image/svg+xml'); self.end_headers(); self.wfile.write(svg.encode()); return
            since='since=0' in self.path
            return self.respond({'request_id':ident,'goal':'Research a product' if ident=='demo-browser' else 'Sign in to continue','status':RUNS[ident],'created_epoch':now-120,'url':'https://example.com/login','takeover':RUNS[ident] in ['paused','handoff'],'pending_action':{'label':'Sign in to your account'} if RUNS[ident]=='handoff' else None,'reason':'Complete sign-in yourself, then continue.' if RUNS[ident]=='handoff' else None,'events':[{'n':1,'kind':'screenshot','file':'preview.svg'}] if since else []})
        if path.startswith('/v1/tasks/') and path.endswith('/events'):
            if 'after=0' not in self.path: return self.respond({'events':[]})
            terminal='demo-terminal' in path
            values=[('c1','command','Ran a command','npm test','Test Files  24 passed\nTests       128 passed\nDuration    6.4s','done'),('c2','command','Building the project','npm run build','Transforming modules…','running')] if terminal else [('b1','browse','Opened a page','https://example.com/login','','running')]
            return self.respond({'events':[{'sequence':i+1,'kind':'activity','created_at':'','payload':{'ref':ref,'category':cat,'label':label,'detail':detail,'output':out,'status':state}} for i,(ref,cat,label,detail,out,state) in enumerate(values)]})
        return super().do_GET()
    def do_POST(self):
        path=urlparse(self.path).path
        if path.endswith('/live'): return self.respond({'error':'preview_snapshots_only'},409)
        ident=path.split('/')[3] if path.startswith('/v1/browse/') else ''
        if path.endswith('/pause'): RUNS[ident]='paused'
        if path.endswith('/resume') or path.endswith('/release'): RUNS[ident]='running'
        return self.respond({'ok':True})
if __name__=='__main__': ThreadingHTTPServer(('127.0.0.1',5178),LivePreview).serve_forever()
