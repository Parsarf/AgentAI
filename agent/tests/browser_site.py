"""A tiny login-gated test site on 127.0.0.1 (stdlib http.server, ephemeral
port) so browser tests never depend on Docker or a third-party site.

GET  /        → login form (or "Welcome back" when the session cookie is set)
POST /login   → form post: username/password; wrong creds re-show the form
GET  /account → second gated page (for multi-step tasks)
"""

from __future__ import annotations

import secrets as _secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

USERNAME = "site-user-1"
PASSWORD = "super-secret-pass-9f3"  # the leak canary's needle

_FORM = """
<html><head><title>Test site — sign in</title></head><body>
<h1>Sign in</h1>
<form method="post" action="/login">
  <input type="text" name="username" placeholder="Username">
  <input type="password" name="password" placeholder="Password">
  <button type="submit">Sign in</button>
</form>
{extra}
</body></html>
"""


class LoginSite:
    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.thread: threading.Thread | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> LoginSite:
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _session_of(self, handler: BaseHTTPRequestHandler) -> str | None:
        raw = handler.headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        token = cookie["session"].value if "session" in cookie else None
        return token if token in self.sessions else None

    def _handler(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence test output
                return

            def _html(self, body: str, status: int = 200, headers: dict | None = None):
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/account":
                    if not site._session_of(self):
                        return self._html(_FORM.format(extra=""), status=303,
                                          headers={"Location": "/"})
                    return self._html(
                        "<html><body><h1>Account</h1><p>private page content</p>"
                        f"<a href='/'>{USERNAME}</a></body></html>"
                    )
                # "/"
                if site._session_of(self):
                    return self._html(
                        f"<html><body><h1>Welcome back, {USERNAME}!</h1>"
                        "<a href='/account'>Account</a></body></html>"
                    )
                self._html(_FORM.format(extra=""))

            def do_POST(self):
                if self.path != "/login":
                    return self._html("not found", status=404)
                length = int(self.headers.get("Content-Length", 0))
                form = parse_qs(self.rfile.read(length).decode())
                user = (form.get("username") or [""])[0]
                password = (form.get("password") or [""])[0]
                if user == USERNAME and password == PASSWORD:
                    token = _secrets.token_urlsafe(16)
                    site.sessions.add(token)
                    return self._html(
                        "<html><body>redirecting</body></html>", status=303,
                        headers={"Location": "/", "Set-Cookie": f"session={token}; Path=/"},
                    )
                self._html(_FORM.format(extra="<p class=error>Bad credentials</p>"))

        return Handler
