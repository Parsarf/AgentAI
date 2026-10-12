"""Customer chat surface: conversations, transcript, sends and task controls.

Every route rechecks identity/membership and scopes all queries by the
verified account. Execution stays disabled until the host connects a probed
gateway; budget/queue refusals are recorded without any native call.
"""
import json
import uuid
from django.db import connection
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from agentai_platform.budget import BudgetLedger, BudgetDenied
from agentai_platform.chat import ChatService, denial_category
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from .lifecycle import AccountStore
from .services import Denied
from .views import endpoint, customer

ERROR_CATEGORIES = {
    'budget_denied': 'Your plan allowance or task budget cannot fund this request. Nothing was charged or started.',
    'queue_full': 'You already have the maximum number of waiting requests.',
    'request_conflict': 'This send conflicts with an existing request or changed payload.',
    'conversation_conflict': 'Conversation limit reached for this project.',
    'project_limit_reached': 'Project limit reached.',
}


def execution_on():
    from django.conf import settings
    from agentai_platform.switches import SwitchStore
    return SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None).is_on('customer_execution')


def service():
    from django.conf import settings
    from agentai_platform.chat import FixedRoute
    store = AccountStore(connection.settings_dict['NAME'])
    live = execution_on()
    # Without the owner switch no route is priced, so a send waits unfunded exactly as before.
    kwargs = {'pricer': FixedRoute(settings.CUSTOMER_RESERVATION_MICROUSD, 'plan-reservation-v1')} if live else {}
    return ChatService(store, queue=RequestQueue(store, require_cell=live), ledger=BudgetLedger(store, service_limit_microusd=settings.SERVICE_ALLOCATION_MICROUSD if live else None),
                       execution=live, **kwargs)


def principal(request):
    return Principal(request.account_id, str(request.user.pk), 'customer')


def _error_redirect(request, conversation_id, error, category=None):
    from urllib.parse import quote
    target = '/account/chat/'
    if conversation_id:
        target += '?conversation=' + quote(conversation_id, safe='')
    target += ('&' if '?' in target else '?') + 'error=' + error
    if category:
        target += '&category=' + quote(category, safe='')
    request.form_redirect = target


@endpoint(['POST'], [])
def chat_archive(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        result = service().archive_conversation(principal(request), conversation_id)
        request.form_redirect = '/account/chat/'
        return JsonResponse({'conversation': result})
    except NotFound:
        raise Denied()


@endpoint(['GET', 'POST'], ['project_id'])
def chat_conversations(request, conversation_id=None):
    denied = customer(request)
    if denied:
        return denied
    try:
        s = service()
        p = principal(request)
        if request.method == 'POST':
            project_id = request.input.get('project_id', '')
            created = s.create_conversation(p, project_id)
            request.form_redirect = '/account/chat/?project=' + created['project_id'] + '&conversation=' + created['id']
            return JsonResponse({'conversation': created}, status=201)
        if conversation_id:
            found = s.conversation(p, conversation_id)
            request.form_redirect = '/account/chat/?conversation=' + conversation_id
            return JsonResponse({'conversation': found})
        listed = s.conversations(p, request.GET.get('project_id') or None)
        request.form_redirect = '/account/chat/'
        return JsonResponse({'conversations': listed})
    except NotFound:
        raise Denied()
    except Conflict:
        _error_redirect(request, conversation_id, 'conversation_conflict')
        return JsonResponse({'error': 'conversation_conflict'}, status=409)


@endpoint(['GET'])
def chat_messages(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    raw = request.GET.get('after', '0')
    after = int(raw) if raw.isdecimal() else -1
    try:
        return JsonResponse(service().messages(principal(request), conversation_id, after=after))
    except (ValueError,):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    except NotFound:
        raise Denied()


@endpoint(['POST'], ['message', 'key', 'mode'], field_limits={'message': 16000})
def chat_send(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        result = service().send(principal(request), conversation_id=conversation_id,
                                message=request.input.get('message', ''), key=request.input.get('key', ''),
                                mode=request.input.get('mode', 'auto'))
        request.form_redirect = '/account/chat/?conversation=' + conversation_id
        return JsonResponse({'request': result}, status=202)
    except NotFound:
        raise Denied()
    except Conflict:
        _error_redirect(request, conversation_id, 'request_conflict')
        if request.content_type == 'application/x-www-form-urlencoded':
            return HttpResponseRedirect(request.form_redirect)
        return JsonResponse({'error': 'request_conflict'}, status=409)
    except BudgetDenied as error:
        category = denial_category(error)
        _error_redirect(request, conversation_id, 'budget_denied', category)
        if request.content_type == 'application/x-www-form-urlencoded':
            return HttpResponseRedirect(request.form_redirect)
        return JsonResponse({'error': 'budget_denied', 'category': category, 'execution_enabled': False}, status=402)


@endpoint(['GET'])
def chat_task(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse({'task': service().task(principal(request), request_id)})
    except NotFound:
        raise Denied()


@endpoint(['POST'])
def chat_cancel(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        cancelled = service().cancel(principal(request), request_id)
        task_row = service().task(principal(request), request_id)
        request.form_redirect = '/account/chat/' + (('?conversation=' + task_row['conversation_id']) if task_row['conversation_id'] else '')
        return JsonResponse({'task': cancelled}, status=202)
    except NotFound:
        raise Denied()


@endpoint(['GET'])
def chat_page(request):
    denied = customer(request)
    if denied:
        return HttpResponseRedirect('/account/login/')
    s = service()
    p = principal(request)
    project_id = request.GET.get('project') or None
    conversation_id = request.GET.get('conversation') or None
    nothing_asked = not project_id and not conversation_id and not request.GET.get('error')
    projects = s.projects(p)
    if project_id and not any(item['id'] == project_id for item in projects):
        project_id = None
    conversations = s.conversations(p, project_id)
    if conversation_id and not any(item['id'] == conversation_id for item in conversations):
        conversation_id = None
    if nothing_asked and projects:
        # Open straight into a usable chat: the newest conversation of the first project, or a fresh one.
        project_id = projects[0]['id']
        conversations = s.conversations(p, project_id)
        if conversations:
            conversation_id = conversations[-1]['id']
        else:
            try:
                conversation_id = s.create_conversation(p, project_id)['id']
                conversations = s.conversations(p, project_id)
            except Conflict:
                pass   # account setup incomplete: keep the empty state
    transcript = s.messages(p, conversation_id) if conversation_id else None
    artifacts, project_files = [], []
    storage_ready = uploads_enabled = False
    if conversation_id and transcript:
        from agentai_platform.events import EventService
        events_service = EventService(AccountStore(connection.settings_dict['NAME']))
        for task in transcript['tasks'][:3]:
            try:
                task['events'] = [e for e in events_service.events(p, task['id'], after=0, limit=50)['events']
                                  if 'transcript update' not in str((e.get('payload') or {}).get('summary', ''))]
            except Exception:
                task['events'] = []
    if project_id:
        from django.conf import settings as dj
        storage_ready = bool(dj.STORAGE_DIR) and dj.STORAGE_READY
        uploads_enabled = storage_ready and dj.UPLOADS_ENABLED
        if storage_ready:
            try:
                from agentai_platform.files import FileService
                from agentai_platform.artifacts import ArtifactService
                from agentai_platform.storage import RootStore
                from .lifecycle import AccountStore as _AS
                store = _AS(connection.settings_dict['NAME'])
                project_files = FileService(store, storage=RootStore(dj.STORAGE_DIR)).list_files(p, project_id)
                artifacts = ArtifactService(store, storage=RootStore(dj.STORAGE_DIR),
                                            signing_key=dj.ARTIFACT_SIGNING_KEY.encode()).list_artifacts(p, project_id)
            except Exception:
                project_files, artifacts = [], []
    error = request.GET.get('error') if request.GET.get('error') in ERROR_CATEGORIES else None
    return render(request,'accounts/chat.html',{
        'projects': projects, 'conversations': conversations,
        'project_id': project_id, 'conversation_id': conversation_id,
        'transcript': transcript, 'send_key': uuid.uuid4().hex,
        'error': error, 'error_text': ERROR_CATEGORIES.get(error or ''),
        'category': request.GET.get('category', ''),
        'execution_enabled': execution_on(),
        'working': execution_on() and any(t.get('state') in ('waiting', 'starting', 'running', 'uncertain') for t in (transcript or {}).get('tasks', [])),
        'artifacts': artifacts, 'project_files': project_files,
        'live_streaming': False,
        'storage_ready': storage_ready, 'uploads_enabled': uploads_enabled,
        'nav': True, 'nav_here': 'chat', 'email': request.user.email})
