"""Phase 8 routes: uploads (when the scan capability is enabled), artifact
versions, authorized downloads and project bundles. Every request rechecks
identity and ownership; downloads require single-use tickets. Upload and
bundle views accept multipart/form posts directly and bypass the JSON-only
endpoint wrapper on purpose."""
import re
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, JsonResponse, FileResponse
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt
from agentai_platform.files import Rejected, MAX_PREVIEW_BYTES
from agentai_platform.security import NotFound
from agentai_platform.lifecycle.types import Conflict
from . import wiring
from .services import Denied, Limited, rate
from .views import endpoint, customer


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _limits_on(request):
    """The account's `upload_limits` switch (agentai_platform/safety.py). Fails closed: any error means the limit applies."""
    return wiring.safety_on(request.account_id, 'upload_limits')


_ready = wiring.storage_ready
_store = wiring.store
_principal = wiring.principal


def _services():
    store = _store()
    return store, wiring.file_service(store), wiring.artifact_service(store)


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
            if len(data) > MAX_UPLOAD_BYTES and _limits_on(request):
                return JsonResponse({'error': 'rejected', 'reason': 'file exceeds 10MiB'}, status=422)
            name = getattr(item, 'name', '') or (hints[index] if index < len(hints) else '')
            entries.append((name or 'upload.bin', getattr(item, 'content_type', '') or '', data))

    def run():
        store, files, artifacts = _services()
        return JsonResponse({'result': files.upload(_principal(request), project_id, entries)}, status=201)
    return _mapped(run)


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
        store, files, artifacts = _services()
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
        store, files, artifacts = _services()
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
        artifacts = wiring.artifact_service()
        parts, name, media = artifacts.consume_ticket(artifact_id, int(version), ticket_value)
        handle = artifacts.storage.open_private(parts)             # streamed from disk: a large file is never held in memory
    except (NotFound, ValueError, OSError):
        return JsonResponse({'error': 'unavailable'}, status=404)
    # Always a download, never rendered in the app's origin, whatever the format is.
    response = FileResponse(handle, content_type=media if media != 'text/html' else 'application/octet-stream')
    response['Content-Disposition'] = content_disposition_header(True, name.rsplit('/', 1)[-1])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['Cache-Control'] = 'no-store'
    return response


@endpoint(['POST'], form='json')
def ticket(request, artifact_id, version):
    denial = _guard(request)
    if denial:
        return denial
    if not version.isdecimal():
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        artifacts = wiring.artifact_service()
        minted = artifacts.mint_ticket(_principal(request), artifact_id, int(version))
        if request.content_type == 'application/x-www-form-urlencoded':
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(minted['path'])
        return JsonResponse({'download': minted}, status=201)
    return _mapped(run)


def bundle(request, project_id):
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    def run():
        artifacts = wiring.artifact_service()
        result = artifacts.build_bundle(_principal(request), project_id)
        request.form_redirect = '/account/chat/?project=' + project_id
        if request.content_type == 'application/x-www-form-urlencoded':
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(request.form_redirect)
        return JsonResponse({'bundle': result}, status=201)
    return _mapped(run)


@endpoint(['GET'])
def account_files(request):
    """Every file made for this account, newest first, with how much storage is used. One query for the Files page and for chat."""
    denial = _guard(request)
    if denial:
        return denial
    return _mapped(lambda: JsonResponse(wiring.artifact_service().list_account(_principal(request))))


@endpoint(['POST'], form='json')
def account_bundle(request):
    """A ZIP of the newest version of every file in the account."""
    denial = _guard(request)
    if denial:
        return denial
    return _mapped(lambda: JsonResponse({'bundle': wiring.artifact_service().build_bundle(_principal(request))}, status=201))


@endpoint(['POST'], form='json')
def delete_artifact(request, artifact_id):
    """Permanently delete a file and all its versions. There is no trash."""
    denial = _guard(request)
    if denial:
        return denial
    return _mapped(lambda: JsonResponse({'deleted': wiring.artifact_service().delete(_principal(request), artifact_id)}))


INLINE_IMAGES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
TEXT_PREVIEW = {'application/json', 'application/xml', 'application/yaml', 'image/svg+xml'}       # shown as source text, never rendered
MAX_INLINE_IMAGE = 20 * 1024 * 1024
MAX_RENDER_PREVIEW = 20 * 1024 * 1024
RENDERED = ('.pdf', '.docx', '.doc', '.odt', '.rtf', '.xlsx', '.xls', '.ods', '.pptx', '.ppt', '.odp')


def artifact_preview(request, artifact_id, version):
    """What one file looks like, for the signed-in owner: the picture itself, the first lines of a text file, or a picture of the first page of a document.
    Never the document itself in the app's origin: the reply is an image or plain text, served sandboxed. 404 with `no_preview` when there is nothing to show."""
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not version.isdecimal():
        return JsonResponse({'error': 'unavailable'}, status=404)

    def run():
        artifacts = wiring.artifact_service()
        parts, row = artifacts.open_version(_principal(request), artifact_id, int(version))
        media, name, size = row['media_type'], row['display_name'], row['size_bytes']
        if media in INLINE_IMAGES and size <= MAX_INLINE_IMAGE:
            body, kind = artifacts.storage.read_private(parts, max_bytes=MAX_INLINE_IMAGE), media
        elif media.startswith('text/') or media in TEXT_PREVIEW:
            handle = artifacts.storage.open_private(parts)
            try:
                body, kind = handle.read(MAX_PREVIEW_BYTES).decode('utf-8', errors='replace').encode(), 'text/plain; charset=utf-8'
            finally:
                handle.close()
        elif name.lower().endswith(RENDERED):
            body = artifacts.read_preview(request.account_id, artifact_id, int(version))
            renderer = wiring.renderer()
            if body is None and renderer is not None and size <= MAX_RENDER_PREVIEW:
                rate('files.preview', request.account_id, 120, 600)
                from agentai_platform.adapters import CapabilityUnavailable
                from agentai_platform.render.client import RenderRefused
                try:
                    body = renderer.convert('file' + name[name.rfind('.'):].lower(), None, {'file' + name[name.rfind('.'):].lower(): artifacts.storage.read_private(parts, max_bytes=MAX_RENDER_PREVIEW)})['preview']
                except (RenderRefused, CapabilityUnavailable):
                    body = None
                if body:
                    artifacts.save_preview(request.account_id, artifact_id, int(version), body)
            kind = 'image/jpeg'
        else:
            body, kind = None, ''
        if not body:
            return JsonResponse({'error': 'no_preview'}, status=404)
        response = HttpResponse(body, content_type=kind)
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=300'       # versions never change
        return response
    try:
        return _mapped(run)
    except Limited:
        return JsonResponse({'error': 'rate_limited'}, status=429, headers={'Retry-After': '600'})


# ---- "Download as": an answer, a whole conversation or a table, in the format asked for. Made on the spot and sent back; nothing is stored. -------------

EXPORT_FORMATS = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'md': 'text/markdown; charset=utf-8',
                  'txt': 'text/plain; charset=utf-8', 'html': 'text/html; charset=utf-8'}
TABLE_FORMATS = {'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'csv': 'text/csv; charset=utf-8'}
PROTOCOL_BLOCK = re.compile(r'```lumina-[a-z]+\n.*?(?:```|\Z)', re.S)        # interface and app blocks are instructions to the app, not part of what was written


def _attachment(body, kind, name):
    response = HttpResponse(body, content_type=kind)
    response['Content-Disposition'] = content_disposition_header(True, name)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-store'
    return response


def _convert(source_name, target, data):
    """One conversion through the render service, mapped to this file's public errors."""
    from agentai_platform.adapters import CapabilityUnavailable
    from agentai_platform.render.client import RenderRefused
    renderer = wiring.renderer()
    if renderer is None:
        return None, JsonResponse({'error': 'convert_not_available'}, status=503)
    try:
        return renderer.convert(source_name, target, {source_name: data}, preview=False)['data'], None
    except RenderRefused as error:
        return None, JsonResponse({'error': 'rejected', 'reason': str(error)}, status=422)
    except CapabilityUnavailable:
        return None, JsonResponse({'error': 'convert_not_available'}, status=503)


def _export_text(request, title, text, target):
    text = PROTOCOL_BLOCK.sub('', text).strip()
    if not text:
        return JsonResponse({'error': 'rejected', 'reason': 'There is no text to export.'}, status=422)
    name = (re.sub(r'[^\w .-]+', ' ', title, flags=re.UNICODE).strip()[:80] or 'Lumina') + '.' + target
    if target in ('md', 'txt'):
        return _attachment(text.encode(), EXPORT_FORMATS[target], name)
    body, failed = _convert('answer.md', target, text.encode())
    return failed or _attachment(body, EXPORT_FORMATS[target], name)


@endpoint(['POST'], ['format', 'message'], form='json')
def export_conversation(request, conversation_id):
    """`format` pdf | docx | md | txt | html. With `message` (a message id) only that answer; without, the whole conversation as it reads in the chat."""
    denied = customer(request)
    if denied:
        return denied
    target, message = request.input.get('format', 'pdf'), request.input.get('message', '')
    if target not in EXPORT_FORMATS or (message and not message.isdecimal()):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    rate('files.export', request.account_id, 40, 600)

    def run():
        store = _store()
        actor = _principal(request)
        with store.connect() as con:
            store._authorize(con, actor)
            chat = con.execute('SELECT title FROM conversations WHERE account_id=? AND id=?', (actor.account_id, conversation_id)).fetchone()
            if chat is None:
                raise NotFound('unavailable')
            if message:
                rows = con.execute('SELECT provenance,content FROM chat_messages WHERE account_id=? AND conversation_id=? AND id=?',
                                   (actor.account_id, conversation_id, int(message))).fetchall()
            else:
                rows = con.execute("SELECT provenance,content FROM chat_messages WHERE account_id=? AND conversation_id=? AND provenance IN ('customer','agent','telegram') ORDER BY id LIMIT 2000",
                                   (actor.account_id, conversation_id)).fetchall()
        if not rows:
            raise NotFound('unavailable')
        title = (chat['title'] or 'Conversation').strip() or 'Conversation'
        if message:
            return _export_text(request, title, rows[0]['content'], target)
        parts = [f'# {title}']
        for row in rows:
            body = PROTOCOL_BLOCK.sub('', row['content']).strip()
            if body:
                parts.append(('**Lumina**' if row['provenance'] == 'agent' else '**You**') + '\n\n' + body)
        return _export_text(request, title, '\n\n---\n\n'.join(parts), target)
    return _mapped(run)


@endpoint(['POST'], ['format', 'name', 'columns', 'rows'], structured=True, form='json')
def export_table(request):
    """A table shown in the chat as a real Excel workbook (or CSV): `columns` a list of headings, `rows` a list of rows of text or numbers."""
    denied = customer(request)
    if denied:
        return denied
    data = request.input
    target, columns, rows = data.get('format', 'xlsx'), data.get('columns'), data.get('rows')
    cell = lambda v: v is None or (isinstance(v, (str, int, float)) and not isinstance(v, bool) and len(str(v)) <= 2000)
    if (target not in TABLE_FORMATS or not isinstance(columns, list) or not 0 < len(columns) <= 100 or not all(isinstance(c, str) and len(c) <= 200 for c in columns)
            or not isinstance(rows, list) or len(rows) > 5000 or not all(isinstance(r, list) and len(r) <= 100 and all(cell(v) for v in r) for r in rows)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    rate('files.export', request.account_id, 40, 600)
    title = data.get('name') if isinstance(data.get('name'), str) else ''
    name = (re.sub(r'[^\w .-]+', ' ', title, flags=re.UNICODE).strip()[:80] or 'Table') + '.' + target
    # Text that looks like a formula stays text: this is what was on screen, not something to calculate.
    plain = lambda v: ("'" + v) if isinstance(v, str) and v[:1] in ('=', '+', '@') else v
    import json as _json
    spec = _json.dumps({'sheets': [{'name': title[:31] or 'Table', 'columns': [plain(c) for c in columns], 'rows': [[plain(v) for v in r] for r in rows]}]}).encode()
    body, failed = _convert('table.json', target, spec)
    return failed or _attachment(body, TABLE_FORMATS[target], name)


def gen_asset(request, artifact_id):
    """Resolve a stored document's file reference within its own authorized project."""
    denial = _guard(request)
    if denial:
        return denial
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    from agentai_platform.genui.document import _safe_file
    import json
    path = request.GET.get('path', '')
    if not _safe_file(path):
        return JsonResponse({'error': 'invalid_file_reference'}, status=400)

    def run():
        store, files, artifacts = _services()
        actor = _principal(request)
        with store.connect() as con:
            store._authorize(con, actor)
            row = con.execute("SELECT d.spec_json,c.project_id FROM data_blocks d JOIN conversations c ON c.account_id=d.account_id AND c.id=d.conversation_id WHERE d.account_id=? AND d.id=? AND d.kind='document'", (actor.account_id, artifact_id)).fetchone()
        if row is None:
            raise NotFound('unavailable')
        # The file must be explicitly referenced by this document, not an arbitrary query parameter.
        def references(value):
            if isinstance(value, dict):
                return any((k == 'assetRef' and v == 'file:' + path) or (value.get('kind') == 'file.download' and k == 'path' and v == path) or references(v) for k, v in value.items())
            return isinstance(value, list) and any(references(v) for v in value)
        if not references(json.loads(row['spec_json'])):
            raise NotFound('unavailable')
        candidates = [r for r in artifacts.list_artifacts(actor, row['project_id']) if r['display_name'] == path]
        if candidates:
            latest = max(candidates, key=lambda r: r['version'])
            minted = artifacts.mint_ticket(actor, latest['id'], latest['version'])
            from urllib.parse import parse_qs, urlparse
            ticket_value = parse_qs(urlparse(minted['path']).query)['ticket'][0]
            parts, name, media = artifacts.consume_ticket(latest['id'], latest['version'], ticket_value)
            data = artifacts.storage.read_private(parts, max_bytes=MAX_PREVIEW_BYTES)
        else:
            matched = next((r for r in files.list_files(actor, row['project_id']) if r['display_name'] == path and r['state'] == 'scanned'), None)
            if matched is None:
                raise NotFound('unavailable')
            parts, media = files.open_parts(actor, row['project_id'], matched['id'])
            data = files.storage.read_private(parts, max_bytes=MAX_PREVIEW_BYTES)
            name = path
        allowed = {'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf', 'text/plain', 'audio/mpeg', 'audio/wav', 'audio/ogg', 'video/mp4', 'video/webm', 'model/gltf-binary'}
        if request.GET.get('download') != '1' and media not in allowed:
            raise NotFound('unsupported preview type')
        response = FileResponse(_Bytes(data), content_type=media if media in allowed else 'application/octet-stream')
        response['X-Frame-Options'] = 'SAMEORIGIN'
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'no-store'
        if request.GET.get('download') == '1':
            from django.utils.http import content_disposition_header
            response['Content-Disposition'] = content_disposition_header(True, name)
        return response
    return _mapped(run)
