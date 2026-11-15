"""Generative-UI endpoints: list blocks, save edits, submit a form, launch a plan. The complete list of what a block can do."""
from django.db import connection
from django.http import JsonResponse
from agentai_platform.budget import BudgetDenied
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound
from .chat import denial_category, principal, service
from .services import Denied, rate, audit
from .views import endpoint, customer


def _version(request):
    v = request.input.get('version')
    if type(v) is not int or isinstance(v, bool) or v < 1:
        raise ValueError('invalid version')
    return v


def _guard(request, name):
    denied = customer(request)
    if denied:
        return denied
    rate(name, request.account_id, 600 if name == 'block.write' else 60, 3600)
    return None


from agentai_platform.genui.artifacts import FieldErrors


def _run(fn):
    try:
        return fn()
    except FieldErrors as error:
        return JsonResponse({'error': 'invalid_ui_values', 'field_errors': error.errors}, status=400)
    except ValueError as error:
        return JsonResponse({'error': 'invalid_ui_document', 'detail': str(error)[:300]}, status=400)
    except NotFound:
        raise Denied()
    except Conflict:
        return JsonResponse({'error': 'version_conflict'}, status=409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error)}, status=402)


@endpoint(['GET'])
def blocks(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    return _run(lambda: JsonResponse({'blocks': service().blocks.list(principal(request), conversation_id)}))


@endpoint(['POST'], ['version', 'state'], structured=True)
def block_state(request, block_id):
    denied = _guard(request, 'block.write')
    if denied:
        return denied
    state = request.input.get('state')
    return _run(lambda: JsonResponse({'block': service().blocks.save_state(principal(request), block_id, _version(request), state)}))


@endpoint(['POST'], ['version'], structured=True)
def block_submit(request, block_id):
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    return _run(lambda: JsonResponse(service().submit_block(principal(request), block_id, _version(request)), status=202))


@endpoint(['POST'], ['version'], structured=True)
def block_launch(request, block_id):
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    return _run(lambda: JsonResponse(service().launch_plan(principal(request), block_id, _version(request)), status=202))


@endpoint(['POST'], ['version', 'plan'], structured=True)
def block_live(request, block_id):
    """Edit phases of a running plan that have not started."""
    denied = _guard(request, 'block.write')
    if denied:
        return denied
    return _run(lambda: JsonResponse({'block': service().runner.edit(principal(request), block_id, _version(request), request.input.get('plan'))}))


@endpoint(['POST'], ['phase_id', 'action'])
def block_phase(request, block_id):
    """Approve, skip or retry one phase of a running plan."""
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    return _run(lambda: JsonResponse({'block': service().runner.act(principal(request), block_id, request.input.get('phase_id', ''), request.input.get('action', ''))}))


@endpoint(['POST'], [])
def block_stop(request, block_id):
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    return _run(lambda: JsonResponse({'block': service().runner.stop(principal(request), block_id)}))


@endpoint(['POST'], ['trigger', 'instruction'], field_limits={'trigger': 20, 'instruction': 2000})
def block_replan(request, block_id):
    """Ask the assistant to revise a running plan (a phase failed, an earlier result changes what comes next, or the customer wants a change). The answer arrives as a proposal."""
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    trigger = request.input.get('trigger') or 'instruction'
    result = _run(lambda: JsonResponse(service().runner.request_replan(principal(request), block_id, trigger, request.input.get('instruction') or ''), status=202))
    return result


@endpoint(['POST'], ['proposal_id', 'action'], field_limits={'proposal_id': 64, 'action': 12})
def block_proposal(request, block_id):
    """Approve or decline a suggested revision of a running plan."""
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    action, proposal = request.input.get('action', ''), request.input.get('proposal_id', '')
    if action not in ('approve', 'decline'):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    runner = service().runner
    fn = runner.approve_proposal if action == 'approve' else runner.decline_proposal
    return _run(lambda: JsonResponse({'block': fn(principal(request), block_id, proposal)}))


@endpoint(['POST'], ['enabled'], structured=True)
def block_auto_replan(request, block_id):
    """Let the assistant revise this plan by itself when a phase fails (a few times at most), or turn that off again."""
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    return _run(lambda: JsonResponse({'block': service().runner.set_auto_replan(principal(request), block_id, request.input.get('enabled'))}))


@endpoint(['GET'])
def component_registry(request):
    denied = customer(request)
    if denied:
        return denied
    from agentai_platform.genui.document import registry
    reg = registry()
    if request.GET.get('root') == '1':
        return JsonResponse(reg['blockSchema'])
    component = request.GET.get('component')
    if component:
        option = next((o for o in reg['blockSchema'].get('oneOf', []) if o.get('properties', {}).get('type', {}).get('const') == component), None)
        if not option:
            return JsonResponse({'error': 'unknown_component'}, status=404)
        return JsonResponse({'component': component, 'schema': option, 'recursiveSchemaUrl': '/v1/genui/registry?root=1', **reg['entries'].get(component, {})})
    return JsonResponse({'version': reg['schemaVersion'], 'components': reg['catalogCompact'], 'limits': reg['limits']})


@endpoint(['POST'], ['version', 'state_revision', 'state'], structured=True)
def artifact_state(request, artifact_id):
    denied = _guard(request, 'block.write')
    if denied:
        return denied
    from agentai_platform.genui.artifacts import ArtifactStore
    return _run(lambda: JsonResponse(ArtifactStore(service().store).state(principal(request), artifact_id, _version(request), request.input.get('state_revision'), request.input.get('state'))))


@endpoint(['POST'], ['id', 'node_id', 'action_id', 'version', 'values'], structured=True)
def artifact_event(request, artifact_id):
    denied = _guard(request, 'block.action')
    if denied:
        return denied
    from agentai_platform.genui.artifacts import ArtifactStore
    return _run(lambda: JsonResponse(ArtifactStore(service().store).event(principal(request), artifact_id, request.input, service()), status=202))


@endpoint(['POST'], ['version', 'document'], structured=True)
def artifact_update(request, artifact_id):
    denied = _guard(request, 'block.write')
    if denied:
        return denied
    from agentai_platform.genui.artifacts import ArtifactStore
    return _run(lambda: JsonResponse(ArtifactStore(service().store).update(principal(request), artifact_id, _version(request), request.input.get('document'))))


@endpoint(['POST'], ['version', 'kind', 'category'], structured=True)
def artifact_diagnostic(request, artifact_id):
    """Authenticated, bounded operational metadata; never accept document or field contents."""
    denied = _guard(request, 'block.diagnostic')
    if denied: return denied
    kinds = {'render_failed', 'save_failed', 'submit_failed', 'invalid_document'}
    categories = {'renderer', 'validation', 'session', 'admission', 'permission', 'unavailable', 'conflict', 'rate_limit', 'server', 'network'}
    if request.input.get('kind') not in kinds or request.input.get('category') not in categories:
        return JsonResponse({'error': 'invalid_diagnostic'}, status=400)
    def record():
        _version(request)
        with service().store.connect() as con:
            service().store._authorize(con, principal(request))
            row = con.execute("SELECT conversation_id FROM data_blocks WHERE account_id=? AND id=? AND kind='document'", (request.account_id, artifact_id)).fetchone()
            if row is None: raise NotFound('unavailable')
        service().blocks.list(principal(request), row['conversation_id'])
        audit(request.user.pk, request.account_id, artifact_id, 'genui.' + request.input['kind'] + '.' + request.input['category'], 'failed', request.request_id)
        return JsonResponse({'recorded': True}, status=202)
    return _run(record)
