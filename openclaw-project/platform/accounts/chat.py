"""Customer chat surface: conversations, transcript, sends and task controls.

Every route rechecks identity/membership and scopes all queries by the
verified account. Execution stays disabled until the host connects a probed
gateway; budget/queue refusals are recorded without any native call.
"""
import uuid
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.budget import BudgetDenied
from agentai_platform.chat import denial_category, MAX_MESSAGE_CHARS
from agentai_platform import request_states, timing
from agentai_platform.security import NotFound
from agentai_platform.lifecycle.types import Conflict
from . import wiring
from .services import Denied, rate
from .views import endpoint, customer

ERROR_CATEGORIES = {
    'budget_denied': 'Your plan allowance or task budget cannot fund this request. Nothing was charged or started.',
    'queue_full': 'You already have the maximum number of waiting requests.',
    'request_conflict': 'This send conflicts with an existing request or changed payload.',
    'conversation_conflict': 'Conversation limit reached for this project.',
    'project_limit_reached': 'Project limit reached.',
}


def execution_on():
    return wiring.switch_on('customer_execution')


def browse_on():
    return wiring.switch_on('browse_tasks')


def service():
    """The chat service of this request (accounts/wiring.py builds it). Views call it through this name."""
    return wiring.chat_service()


principal = wiring.principal


def _error_redirect(request, conversation_id, error, category=None):
    from urllib.parse import quote
    target = '/account/chat/'
    if conversation_id:
        target += '?conversation=' + quote(conversation_id, safe='')
    target += ('&' if '?' in target else '?') + 'error=' + error
    if category:
        target += '&category=' + quote(category, safe='')
    request.form_redirect = target


@endpoint(['POST'], ['title'], field_limits={'title': 90}, form='chat')
def chat_rename(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'conversation': service().rename_conversation(principal(request), conversation_id, request.input.get('title', ''))})


@endpoint(['POST'], [], form='chat')
def chat_archive(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    result = service().archive_conversation(principal(request), conversation_id)
    request.form_redirect = '/account/chat/'
    return JsonResponse({'conversation': result})


@endpoint(['POST'], [], form='chat')
def chat_restore(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse({'conversation': service().restore_conversation(principal(request), conversation_id)})
    except Conflict:
        return JsonResponse({'error': 'conversation_conflict'}, status=409)


@endpoint(['GET', 'POST'], ['project_id'], form='chat')
def chat_conversations(request, conversation_id=None):
    denied = customer(request)
    if denied:
        return denied
    try:
        s = service()
        p = principal(request)
        if request.method == 'POST':
            project_id = request.input.get('project_id', '')
            if not project_id:                       # a new chat needs no project choice: use the account's first one
                projects = s.projects(p)
                project_id = projects[0]['id'] if projects else ''
            created = s.create_conversation(p, project_id)
            request.form_redirect = '/account/chat/?project=' + created['project_id'] + '&conversation=' + created['id']
            return JsonResponse({'conversation': created}, status=201)
        if conversation_id:
            found = s.conversation(p, conversation_id)
            request.form_redirect = '/account/chat/?conversation=' + conversation_id
            return JsonResponse({'conversation': found})
        raw_limit, raw_offset = request.GET.get('limit', '100'), request.GET.get('offset', '0')
        archived = request.GET.get('archived', '0')
        if not raw_limit.isdecimal() or not raw_offset.isdecimal() or archived not in ('0', '1') or not 1 <= int(raw_limit) <= 500:
            raise ValueError('invalid pagination')
        limit = int(raw_limit)
        listed = s.conversations(p, request.GET.get('project_id') or None, query=request.GET.get('q', ''), archived=archived == '1', limit=limit + 1, offset=int(raw_offset))
        request.form_redirect = '/account/chat/'
        return JsonResponse({'conversations': listed[:limit], 'has_more': len(listed) > limit, 'next_offset': int(raw_offset) + min(len(listed), limit)})
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
    raw_limit = request.GET.get('limit', '100')
    limit = int(raw_limit) if raw_limit.isdecimal() else -1
    try:
        return JsonResponse(service().messages(principal(request), conversation_id, after=after, limit=limit))
    except (ValueError,):
        return JsonResponse({'error': 'invalid_request'}, status=400)


@endpoint(['POST'], ['message', 'key', 'mode', 'goal', 'ui'], field_limits={'message': MAX_MESSAGE_CHARS}, form='chat')
def chat_send(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    goal = str(request.input.get('goal', '')).lower() in ('1', 'true', 'on', 'yes')          # fields are strings (a form sends 'on')
    try:
        result = service().send(principal(request), conversation_id=conversation_id,
                                message=request.input.get('message', ''), key=request.input.get('key', ''),
                                mode=request.input.get('mode', 'auto'), goal=goal, ui=request.input.get('ui', 'basic'))
        request.form_redirect = '/account/chat/?conversation=' + conversation_id
        timing.mark(result.get('id'), 'send_accepted', admission=result.get('admission', ''), steered=bool(result.get('steered')))
        return JsonResponse({'request': result}, status=202)
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


@endpoint(['POST'], ['action', 'key'], form='chat')
def chat_goal(request, conversation_id):
    """The customer's controls on a "Keep working until complete" goal: resume a paused, blocked or budget-limited one, or clear it."""
    denied = customer(request)
    if denied:
        return denied
    rate('task.create', request.account_id, 30, 3600)
    try:
        result = service().goal_action(principal(request), conversation_id, request.input.get('action', ''), key=request.input.get('key', ''))
        return JsonResponse({'goal': result.get('goal'), **({'request': result} if 'id' in result else {})}, status=202)
    except (Conflict, CapabilityUnavailable):
        return JsonResponse({'error': 'request_conflict'}, status=409)
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error), 'execution_enabled': False}, status=402)


@endpoint(['GET'])
def chat_task(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'task': service().task(principal(request), request_id)})


@endpoint(['POST'], form='chat')
def chat_cancel(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    cancelled = service().cancel(principal(request), request_id)
    task_row = service().task(principal(request), request_id)
    request.form_redirect = '/account/chat/' + (('?conversation=' + task_row['conversation_id']) if task_row['conversation_id'] else '')
    return JsonResponse({'task': cancelled}, status=202)


def _hold(request, request_id, action):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse({'request': getattr(service(), action)(principal(request), request_id)}, status=202)
    except NotFound:
        raise Denied()
    except Conflict:
        return JsonResponse({'error': 'request_conflict'}, status=409)


@endpoint(['POST'], form='chat')
def chat_pause(request, request_id):
    """Hold a task that has not started. A running task cannot be paused (the assistant has no safe stopping point mid-run); browser tasks have their own pause."""
    return _hold(request, request_id, 'pause')


@endpoint(['POST'], form='chat')
def chat_resume(request, request_id):
    return _hold(request, request_id, 'resume')


@endpoint(['POST'], form='chat')
def chat_retry(request, request_id):
    denied = customer(request)
    if denied:
        return denied
    try:
        rate('task.create', request.account_id, 30, 3600)          # a retry is a new task: same limit as sending one
        return JsonResponse({'request': service().retry(principal(request), request_id)}, status=202)
    except Conflict:
        return JsonResponse({'error': 'request_conflict'}, status=409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error), 'execution_enabled': False}, status=402)


def prewarm(account_id):
    """The customer opened the app: start their stopped cell now instead of when they send. Best effort; it never slows or breaks the page.
    It only queues a start. The lifecycle worker runs it and still respects the cell slot, so no other customer's working cell is stopped for it."""
    import time
    try:
        if not execution_on():
            return
        store = wiring.store()
        with store.connect() as con:
            cell = con.execute("SELECT d.generation FROM lifecycle_cells c JOIN deployments d ON d.account_id=c.account_id AND d.id=c.deployment_id "
                               "WHERE c.account_id=? AND c.observed_state='stopped'", (account_id,)).fetchone()
        if cell:
            from agentai_platform.lifecycle.coordinator import Coordinator
            Coordinator(store).request_system(account_id, key=f"presence-{cell['generation']}-{int(time.time()) // 600}", generation=cell['generation'], kind='start', presence=True)
    except Exception:
        pass      # Conflict (already starting, slot busy) or any lookup problem: the first message wakes the cell as before


@endpoint(['GET'])
def chat_page(request):
    denied = customer(request)
    if denied:
        return HttpResponseRedirect('/account/login/')
    prewarm(request.account_id)
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
        events_service = wiring.event_service()
        for task in transcript['tasks'][:3]:
            try:
                task['events'] = [e for e in events_service.events(p, task['id'], after=0, limit=50)['events']
                                  if 'transcript update' not in str((e.get('payload') or {}).get('summary', ''))]
            except Exception:
                task['events'] = []
    if project_id:
        storage_ready = wiring.storage_ready()
        uploads_enabled = wiring.uploads_on()
        if storage_ready:
            try:
                store = wiring.store()
                project_files = wiring.file_service(store).list_files(p, project_id)
                artifacts = wiring.artifact_service(store).list_artifacts(p, project_id)
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
        'working': execution_on() and any(t.get('state') in request_states.ACTIVE for t in (transcript or {}).get('tasks', [])),
        'artifacts': artifacts, 'project_files': project_files,
        'live_streaming': False,
        'storage_ready': storage_ready, 'uploads_enabled': uploads_enabled,
        'nav': True, 'nav_here': 'chat', 'email': request.user.email})
