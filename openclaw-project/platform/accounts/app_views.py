"""An isolated app player and account-authorized immutable app source."""
import hashlib
from pathlib import Path
from django.http import HttpResponse, JsonResponse
from .views import customer
from . import files, wiring
from agentai_platform.apps import application, MAX_APP_BYTES


def player(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    denied = customer(request)
    if denied:
        return denied
    response = HttpResponse(Path(__file__).with_name('app_player.html').read_text(), content_type='text/html')
    # No same-origin authority inside this frame, even when opened directly.
    response['Content-Security-Policy'] = (
        "default-src 'none'; sandbox allow-scripts; script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net/pyodide/v0.27.7/full/; "
        "style-src 'unsafe-inline'; connect-src https://cdn.jsdelivr.net/pyodide/v0.27.7/full/; "
        "worker-src blob:; frame-src about:; img-src data: blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=(), usb=()'
    return response


def source(request, artifact_id, version):
    denial = files._guard(request)
    if denial:
        return denial
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    def run():
        if not version.isdecimal() or int(version) < 1:
            raise ValueError('invalid version')
        artifacts = wiring.artifact_service()
        with artifacts.store.connect() as con:
            row = artifacts._authorized_version(con, files._principal(request), artifact_id, int(version))
        runtime = {'.html': 'html', '.py': 'python', '.js': 'javascript'}.get(Path(row['display_name']).suffix.lower())
        if not runtime or row['size_bytes'] > MAX_APP_BYTES:
            return JsonResponse({'error': 'unsupported_app', 'detail': 'Open a standalone HTML, Python or browser JavaScript file up to 512 KiB.'}, status=422)
        try:
            data = artifacts.storage.read_private([request.account_id] + row['storage_ref'].split('/'), max_bytes=MAX_APP_BYTES)
        except FileNotFoundError:
            return JsonResponse({'error': 'unavailable'}, status=404)
        except OSError:
            return JsonResponse({'error': 'storage_unavailable'}, status=503)
        except ValueError:
            return JsonResponse({'error': 'invalid_app_source'}, status=422)
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            return JsonResponse({'error': 'invalid_app_source'}, status=422)
        # storage_ref is relative to the account, as with authorized downloads.
        try:
            app = application({'version': 1, 'title': row['display_name'][:120], 'runtime': runtime, 'code': data.decode('utf-8')})
        except ValueError:
            return JsonResponse({'error': 'invalid_app_source'}, status=422)
        return JsonResponse({'app': app})
    return files._mapped(run)
