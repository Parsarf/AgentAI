"""Serves a replacement front end from a directory, with its own (script-capable) content policy.

Drop a built single-page app into AGENTAI_UI_BUNDLE_DIR and it is live at /app/ — no backend change, no restart.
The server-rendered pages under /account/ keep working side by side. Only static files are served; all data comes
through the same authenticated /v1 API, so a new UI gets exactly the access the classic one has.
"""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def serve(request, path=''):
    if request.method not in ('GET', 'HEAD'):
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    root = Path(settings.UI_BUNDLE_DIR).resolve() if settings.UI_BUNDLE_DIR else None
    if root is None or not (root / 'index.html').is_file():
        return JsonResponse({'error': 'ui_not_installed'}, status=404)
    target = (root / path).resolve() if path else root / 'index.html'
    try:
        target.relative_to(root)
    except ValueError:
        return JsonResponse({'error': 'unavailable'}, status=404)
    if not target.is_file():
        if Path(path).suffix:                              # a missing asset is a 404, not the app shell
            return JsonResponse({'error': 'unavailable'}, status=404)
        target = root / 'index.html'                       # client-side routes fall back to the shell
    kind = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
    response = FileResponse(open(target, 'rb'), content_type=kind) if request.method == 'GET' else HttpResponse(content_type=kind)
    response['Content-Security-Policy'] = CSP
    response['Cache-Control'] = 'no-store' if target.name == 'index.html' else 'public, max-age=300'
    return response
