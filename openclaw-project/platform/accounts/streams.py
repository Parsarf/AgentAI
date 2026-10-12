"""Phase 9 task timeline routes: cursor polling, authenticated SSE stream.

The stream authenticates like every customer route, caps open streams at
three per account, emits heartbeats, rechecks identity and stream liveness
between batches (revocation ends the stream), and ends after a bounded
window so clients reconnect with their cursor — replay is gap-free from the
durable store.
"""
import json
import time
import uuid
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import connection
from django.http import JsonResponse, StreamingHttpResponse
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService
from agentai_platform.events import EventService
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from .lifecycle import AccountStore
from .services import Denied
from .views import endpoint, customer

STREAM_WINDOW_SECONDS = 45
STREAM_POLL_INTERVAL = 1.0


def _store():
    return AccountStore(connection.settings_dict['NAME'])


def _service():
    store = _store()
    return EventService(store, clock=time.time)


def _principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


@endpoint(['GET'])
def events(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    raw = request.GET.get('after', '0')
    limit_raw = request.GET.get('limit', '100')
    after = int(raw) if raw.isdecimal() else -1
    limit = int(limit_raw) if limit_raw.isdecimal() else -1
    try:
        return JsonResponse(_service().events(_principal(request), request_id, after=after, limit=limit))
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    except NotFound:
        raise Denied()


def _sse(payload: dict, event: str = 'task_event', seq: int | None = None) -> str:
    lines = [f'event: {event}']
    if seq is not None:
        lines.append(f'id: {seq}')
    lines.append(f'data: {json.dumps(payload)}')
    return '\n'.join(lines) + '\n\n'


@csrf_exempt
def stream(request, request_id):
    """Authenticated SSE. Bounded window; clients reconnect with their cursor.
    GET is read-only, so CSRF does not apply; identity is still required."""
    denied = customer(request)
    if denied:
        return denied
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    principal = _principal(request)
    service = _service()
    try:
        after = int(request.GET.get('after', '0') or 0)
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    stream_id = uuid.uuid4().hex
    try:
        service.open_stream(principal, request_id, stream_id)
    except Conflict:
        return JsonResponse({'error': 'stream_limit_reached'}, status=429,
                            headers={'Retry-After': '30'})
    except NotFound:
        raise Denied()

    def generator():
        cursor = after
        deadline = time.monotonic() + STREAM_WINDOW_SECONDS
        try:
            yield _sse({'stream_id': stream_id, 'task_id': request_id}, event='open')
            while time.monotonic() < deadline:
                if not service.stream_alive(principal, stream_id):
                    yield _sse({'reason': 'closed'}, event='bye')
                    return
                try:
                    page = service.events(principal, request_id, after=cursor, limit=100)
                except NotFound:
                    yield _sse({'reason': 'gone'}, event='bye')
                    return
                for item in page['events']:
                    cursor = item['sequence']
                    yield _sse({'kind': item['kind'], 'source': item['source'],
                                'payload': item['payload'], 'created_at': item['created_at']},
                               seq=item['sequence'])
                service.heartbeat_stream(stream_id)
                yield ': heartbeat\n\n'
                time.sleep(STREAM_POLL_INTERVAL)
            yield _sse({'cursor': cursor}, event='reopen')
        finally:
            service.close_stream(stream_id)

    response = StreamingHttpResponse(generator(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-store'
    response['X-Accel-Buffering'] = 'no'
    return response
