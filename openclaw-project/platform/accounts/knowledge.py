"""The customer's knowledge (roadmap Phase 4), commitments (#43) and memory correction (#42).

    GET  /v1/knowledge                                  the Sources page: every source with its state, and the sources others in the organization shared with this person
    POST /v1/knowledge/sources                          {"kind": "upload"|"made", "id", "project_id"?}  add a file to the index
    POST /v1/knowledge/sources/<id>/remove              remove a source: its passages go now (the file itself stays in Files)
    POST /v1/knowledge/sources/<id>/reindex             read it again
    POST /v1/knowledge/sources/<id>/share               {"scope": "account"|"organization", "audience"?, "project_id"?, "pinned"?, "origin"?}
    GET  /v1/knowledge/sources/<id>/document            the document view: blocks with pages and positions, and which blocks each passage covers
    GET  /v1/knowledge/search                           ?q=&project=   the same search the assistant uses
    GET  /v1/knowledge/passages/<id>                    one passage with its citation (a citation link opens here)
    GET  /v1/knowledge/compare                          ?first=&second=
    GET  /v1/organization/groups                        named groups of the organization (#40)
    POST /v1/organization/groups                        {"name"}
    POST /v1/organization/groups/<id>/members           {"actor_id", "member": true|false}
    POST /v1/organization/groups/<id>/delete
    GET  /v1/commitments                                ?state=active|proposed|open|done|dropped&person=
    POST /v1/commitments                                {"what", "owner"?, "due"?, "kind"?}   one the customer adds themselves
    POST /v1/commitments/<id>                           {"state"?, "what"?, "owner"?, "due"?}  confirm a suggestion, close, drop or edit
    POST /v1/longterm-memory/<id>/correct               {"content"}  correct a remembered note; what it said before stays in its history
    GET  /v1/longterm-memory/<id>/history

Every answer is scoped to the signed-in person's account (and, for shared sources, their organization and their audiences). An id of something they may not read is
"not found", whoever owns it.
"""
from django.http import JsonResponse

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound
from . import wiring
from .access import guarded
from .services import audit, rate
from .views import customer, endpoint


def _knowledge(request, key=None, limit=600):
    """-> (principal, service, None) or (None, None, the response to give)."""
    denied = customer(request)
    if denied:
        return None, None, denied
    if not wiring.knowledge_on(request.account_id):
        return None, None, JsonResponse({'error': 'feature_off'}, status=503)
    service = wiring.knowledge_service()
    if service is None:
        return None, None, JsonResponse({'error': 'feature_off'}, status=503)
    if key:
        rate(key, request.account_id, limit, 600)
    return wiring.principal(request), service, None


def _run(fn):
    def body():
        try:
            return JsonResponse(fn())
        except CapabilityUnavailable:
            return JsonResponse({'error': 'temporarily_unavailable'}, status=503)
        except PermissionError:
            return JsonResponse({'error': 'not_permitted'}, status=403)
    return guarded(body)


@endpoint(['GET'])
def overview(request):
    denied = customer(request)
    if denied:
        return denied
    if not wiring.knowledge_on(request.account_id) or wiring.knowledge_service() is None:
        return JsonResponse({'available': False, 'sources': [], 'shared_with_me': [], 'groups': []})
    principal, service, stop = _knowledge(request)
    if stop:
        return stop
    return _run(lambda: {'available': True, **service.sources(principal)})


@endpoint(['POST'], ['kind', 'id', 'project_id'], structured=True)
def add(request):
    principal, service, stop = _knowledge(request, 'knowledge.add', 300)
    if stop:
        return stop
    given = request.input
    if given.get('kind') not in ('upload', 'made') or not isinstance(given.get('id'), str) or (given.get('project_id') is not None and not isinstance(given['project_id'], str)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: {'source': service.add(principal, given['kind'], given['id'], project_id=given.get('project_id'))})


@endpoint(['POST'], [])
def remove(request, source_id):
    principal, service, stop = _knowledge(request, 'knowledge.remove', 300)
    if stop:
        return stop
    response = _run(lambda: service.remove(principal, source_id))
    if response.status_code == 200:
        audit(request.user.pk, request.account_id, 'knowledge', 'knowledge.remove', 'completed', request.request_id)
    return response


@endpoint(['POST'], [])
def reindex(request, source_id):
    principal, service, stop = _knowledge(request, 'knowledge.reindex', 120)
    if stop:
        return stop
    return _run(lambda: {'source': service.reindex(principal, source_id)})


@endpoint(['POST'], ['scope', 'audience', 'project_id', 'pinned', 'origin'], structured=True)
def share(request, source_id):
    principal, service, stop = _knowledge(request, 'knowledge.share', 300)
    if stop:
        return stop
    given = request.input
    if given.get('scope') not in ('account', 'organization') or (given.get('audience') is not None and not isinstance(given['audience'], str)) \
            or (given.get('pinned') is not None and type(given['pinned']) is not bool) or (given.get('origin') is not None and not isinstance(given['origin'], str)):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    kwargs = {'scope': given['scope'], 'audience': given.get('audience') or '', 'pinned': given.get('pinned'), 'origin': given.get('origin')}
    if 'project_id' in given:
        if given['project_id'] is not None and not isinstance(given['project_id'], str):
            return JsonResponse({'error': 'invalid_request'}, status=400)
        kwargs['project_id'] = given['project_id']
    response = _run(lambda: {'source': service.share(principal, source_id, **kwargs)})
    if response.status_code == 200:
        audit(request.user.pk, request.account_id, 'knowledge', 'knowledge.share', 'completed', request.request_id)
    return response


@endpoint(['GET'])
def document(request, source_id):
    principal, service, stop = _knowledge(request)
    if stop:
        return stop
    return _run(lambda: service.document(principal, source_id))


@endpoint(['GET'])
def search(request):
    principal, service, stop = _knowledge(request, 'knowledge.search', 600)
    if stop:
        return stop
    query, project = request.GET.get('q', ''), request.GET.get('project') or None
    if not query.strip() or len(query) > 500:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: service.search(principal, query, project_id=project, limit=12))


@endpoint(['GET'])
def passage(request, passage_id):
    principal, service, stop = _knowledge(request)
    if stop:
        return stop
    return _run(lambda: {'passage': service.passage(principal, passage_id)})


@endpoint(['GET'])
def compare(request):
    principal, service, stop = _knowledge(request, 'knowledge.compare', 120)
    if stop:
        return stop
    first, second = request.GET.get('first', ''), request.GET.get('second', '')
    if not first or not second or first == second:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: service.compare(principal, first, second, detail_limit=200))


# ---- named groups of an organization (#40) ----------------------------------------------------------------------------------------------------------
@endpoint(['GET', 'POST'], ['name'])
def groups(request):
    denied = customer(request)
    if denied:
        return denied
    principal, service = wiring.principal(request), wiring.organization_service()
    if request.method == 'GET':
        return _run(lambda: {'groups': service.groups(principal)})
    rate('organization.group', request.account_id, 60, 600)
    return _run(lambda: {'group': service.create_group(principal, request.input.get('name', ''))})


@endpoint(['POST'], ['actor_id', 'member'], structured=True)
def group_member(request, group_id):
    denied = customer(request)
    if denied:
        return denied
    rate('organization.group', request.account_id, 60, 600)
    given = request.input
    if not isinstance(given.get('actor_id'), str) or type(given.get('member')) is not bool:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: wiring.organization_service().set_group_member(wiring.principal(request), group_id, given['actor_id'], given['member']))


@endpoint(['POST'], [])
def group_delete(request, group_id):
    denied = customer(request)
    if denied:
        return denied
    rate('organization.group', request.account_id, 60, 600)
    return _run(lambda: wiring.organization_service().delete_group(wiring.principal(request), group_id))


# ---- commitments (#43) ------------------------------------------------------------------------------------------------------------------------------
def _commitments_on(account_id):
    return wiring.knowledge_on(account_id) or wiring.hub_on(account_id)


def _zone(request, principal):
    try:
        return wiring.hub_service().settings(principal)['timezone'] or 'UTC'
    except Exception:
        return 'UTC'


@endpoint(['GET', 'POST'], ['what', 'owner', 'due', 'kind', 'zone'], structured=True)
def commitments(request):
    denied = customer(request)
    if denied:
        return denied
    if not _commitments_on(request.account_id):
        return JsonResponse({'available': False, 'items': [], 'counts': {}}) if request.method == 'GET' else JsonResponse({'error': 'feature_off'}, status=503)
    principal, service = wiring.principal(request), wiring.commitment_service()
    if request.method == 'GET':
        state = request.GET.get('state') or 'active'
        return _run(lambda: {'available': True, **service.list(principal, state=state, person=request.GET.get('person') or None)})
    rate('commitments.write', request.account_id, 120, 600)
    given = request.input
    if not isinstance(given.get('what'), str) or any(given.get(k) is not None and not isinstance(given[k], str) for k in ('owner', 'due', 'kind', 'zone')):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return _run(lambda: {'item': service.record(principal, what=given['what'], owner=given.get('owner') or '', due_on=given.get('due') or None,
                                                zone=given.get('zone') or _zone(request, principal), source_kind='customer', kind=given.get('kind') or 'commitment', by='customer')})


@endpoint(['POST'], ['state', 'what', 'owner', 'due', 'zone'], structured=True)
def commitment(request, item_id):
    denied = customer(request)
    if denied:
        return denied
    if not _commitments_on(request.account_id):
        return JsonResponse({'error': 'feature_off'}, status=503)
    rate('commitments.write', request.account_id, 120, 600)
    given = request.input
    if any(given.get(k) is not None and not isinstance(given[k], str) for k in ('state', 'what', 'owner', 'due', 'zone')):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    principal = wiring.principal(request)
    kwargs = {k: given[k] for k in ('state', 'what', 'owner') if given.get(k) is not None}
    if 'due' in given:
        kwargs['due_on'], kwargs['zone'] = given['due'] or None, given.get('zone') or _zone(request, principal)
    return _run(lambda: {'item': wiring.commitment_service().change(principal, item_id, by='customer', **kwargs)})


# ---- memory correction (#42) ------------------------------------------------------------------------------------------------------------------------
@endpoint(['POST'], ['content'], field_limits={'content': 600})
def memory_correct(request, entry_id):
    denied = customer(request)
    if denied:
        return denied
    rate('memory.correct', request.account_id, 60, 600)
    memory = wiring.memory_service() if wiring.memory_on(request.account_id) else None
    if memory is None:
        return JsonResponse({'error': 'not_available'}, status=409)
    from agentai_platform import longterm_memory as ltm
    try:
        memory.correct(request.account_id, entry_id, request.input.get('content', ''), by='customer')
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
    except ValueError as error:
        return JsonResponse({'error': 'invalid_request', 'message': str(error)[:200]}, status=400)
    except ltm.MemoryError_:
        return JsonResponse({'error': 'temporarily_unavailable'}, status=503)
    audit(request.user.pk, request.account_id, 'memory', 'memory.correct', 'completed', request.request_id)
    return JsonResponse({'ok': True, 'history': memory.history(request.account_id, entry_id)})


@endpoint(['GET'])
def memory_history(request, entry_id):
    denied = customer(request)
    if denied:
        return denied
    memory = wiring.memory_service() if wiring.memory_on(request.account_id) else None
    if memory is None:
        return JsonResponse({'error': 'not_available'}, status=409)
    try:
        return JsonResponse({'history': memory.history(request.account_id, entry_id)})
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
