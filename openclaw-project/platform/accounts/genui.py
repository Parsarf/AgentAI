"""Generative-UI endpoints: list blocks, save edits, submit a form, launch a plan. The complete list of what a block can do."""
from django.db import connection
from django.http import JsonResponse
from agentai_platform.budget import BudgetDenied
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound
from .chat import denial_category, principal, service
from .services import Denied, rate
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


def _run(fn):
    try:
        return fn()
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
