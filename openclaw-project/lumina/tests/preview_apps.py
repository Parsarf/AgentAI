"""Synthetic chat fixture plus the production player and its exact CSP."""
import ast
from pathlib import Path
from http.server import ThreadingHTTPServer
from preview_chat import Preview
accounts = Path(__file__).resolve().parents[2] / 'platform/accounts'
tree = ast.parse((accounts / 'app_views.py').read_text())
policy = next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == 'Content-Security-Policy' for t in n.targets))
class AppsPreview(Preview):
    def do_GET(self):
        if self.path == '/v1/apps/player':
            data = (accounts / 'app_player.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Security-Policy', policy); self.end_headers(); self.wfile.write(data)
        else:
            super().do_GET()
if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 5182), AppsPreview).serve_forever()
