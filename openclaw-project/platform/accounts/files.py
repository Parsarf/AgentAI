"""Phase 8 routes: uploads (when the scan capability is enabled), artifact
versions, authorized downloads and project bundles. Every request rechecks
identity and ownership; downloads require single-use tickets. Upload and
bundle views accept multipart/form posts directly and bypass the JSON-only
endpoint wrapper on purpose."""
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService
from agentai_platform.files import FileService, Rejected, MAX_PREVIEW_BYTES
from agentai_platform.artifacts import ArtifactService
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.storage import RootStore
from agentai_platform.lifecycle.types import Conflict
from .lifecycle import AccountStore
from .services import Denied
from .views import endpoint, customer


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _ready():
    return bool(settings.STORAGE_DIR) and settings.STORAGE_READY


def _store():
    return AccountStore(connection.settings_dict['NAME'])


def _services():
    store = _store()
    chat = ChatService(store, queue=RequestQueue(store), ledger=BudgetLedger(store))
    files = FileService(store, storage=RootStore(settings.STORAGE_DIR))
    key = settings.ARTIFACT_SIGNING_KEY
    artifacts = ArtifactService(store, storage=RootStore(settings.STORAGE_DIR),
                                signing_key=key.encode() if isinstance(key, str) else key)
    return store, chat, files, artifacts


def _principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


def _guard(request):
    """Returns a denial response or None. Identity, configuration, method."""
    denied = customer(request)
    if denied:
        return denied
    if not _ready():
        return JsonResponse({'error': 'storage_not_configured'}, status=503)
    return None


def _mapped(fn):
    try:
        return fn()
    except Rejected as error:
        return JsonResponse({'error': 'rejected', 'reason': str(error)}, status=422)
    except Conflict:
        return JsonResponse({'error': 'quota_exceeded'}, status=409)
    except NotFound:
        # Same public shape on both endpoint-decorated and plain views.
        return JsonResponse({'error': 'unavailable'}, status=404)
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)


@csrf_exempt
def upload(request, project_id):
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not settings.UPLOADS_ENABLED:
        return JsonResponse({'error': 'uploads_not_enabled'}, status=503)
    if not request.FILES:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    if len(request.FILES) > 10:
        return JsonResponse({'error': 'rejected', 'reason': 'batch must contain 1 to 10 files'}, status=422)
    import json as _json
    try:
        hints = _json.loads(request.POST.get('filenames', '[]'))
    except ValueError:
        hints = []
    entries = []
    for field in request.FILES.values():
        for index, item in enumerate(field):
            # Upload handlers may hand over an UploadedFile or raw bytes.
            data = item.read() if hasattr(item, 'read') else item
            if len(data) > MAX_UPLOAD_BYTES:
                return JsonResponse({'error': 'rejected', 'reason': 'file exceeds 10MiB'}, status=422)
            name = getattr(item, 'name', '') or (hints[index] if index < len(hints) else '')
            entries.append((name or 'upload.bin', getattr(item, 'content_type', '') or '', data))

    def run():
        store, chat, files, artifacts = _services()
        return JsonResponse({'result': files.upload(_principal(request), project_id, entries)}, status=201)
    return _mapped(run)


@csrf_exempt
def files_route(request, project_id):
    if request.method == 'POST':
        return upload(request, project_id)
    if request.method == 'GET':
        return listing(request, project_id)
    return JsonResponse({'error': 'method_not_allowed'}, status=405)


@endpoint(['GET'])
def listing(request, project_id):
    denied = customer(request)
    if denied:
        return denied
    if not _ready():
        return JsonResponse({'error': 'storage_not_configured'}, status=503)

    def run():
        store, chat, files, artifacts = _services()
        return JsonResponse({'files': files.list_files(_principal(request), project_id),
                             'artifacts': artifacts.list_artifacts(_principal(request), project_id)})
    return _mapped(run)


class _Bytes:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, n=-1):
        if n == -1:
            rest, self.pos = self.data[self.pos:], len(self.data)
            return rest
        rest = self.data[self.pos:self.pos + n]
        self.pos += len(rest)
        return rest


def preview(request, project_id, file_id):
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    def run():
        store, chat, files, artifacts = _services()
        parts, media = files.open_parts(_principal(request), project_id, file_id)
        data = files.storage.read_private(parts, max_bytes=MAX_PREVIEW_BYTES)
        response = FileResponse(_Bytes(data), content_type=media)
        # Previews never execute in the dashboard origin: fully sandboxed.
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'no-store'
        return response
    return _mapped(run)


@csrf_exempt
def download(request, artifact_id, version):
    """Ticket-authenticated: no session needed; ticket consumed atomically."""
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not _ready():
        return JsonResponse({'error': 'unavailable'}, status=503)
    ticket_value = request.GET.get('ticket', '')
    if not version.isdecimal() or not ticket_value:
        return JsonResponse({'error': 'unavailable'}, status=404)
    try:
        artifacts = _services()[3]
        parts, name, media = artifacts.consume_ticket(artifact_id, int(version), ticket_value)
        data = artifacts.storage.read_private(parts)
    except (NotFound, ValueError):
        return JsonResponse({'error': 'unavailable'}, status=404)
    response = FileResponse(_Bytes(data), content_type=media)
    safe_name = name.replace('"', '')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}"'
    response['Cache-Control'] = 'no-store'
    return response


@endpoint(['POST'])
def ticket(request, artifact_id, version):
    denial = _guard(request)
    if denial:
        return denial
    if not version.isdecimal():
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        artifacts = _services()[3]
        minted = artifacts.mint_ticket(_principal(request), artifact_id, int(version))
        if request.content_type == 'application/x-www-form-urlencoded':
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(minted['path'])
        return JsonResponse({'download': minted}, status=201)
    return _mapped(run)


@csrf_exempt
def bundle(request, project_id):
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    def run():
        artifacts = _services()[3]
        result = artifacts.build_bundle(_principal(request), project_id)
        request.form_redirect = '/account/chat/?project=' + project_id
        if request.content_type == 'application/x-www-form-urlencoded':
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(request.form_redirect)
        return JsonResponse({'bundle': result}, status=201)
    return _mapped(run)
