"""Long jobs the customer can see and steer: GET /v1/objectives, GET/POST /v1/objectives/<id>, POST /v1/objectives/<id>/cancel.

An objective is the durable record of one "keep working until complete" job (agentai_platform/goal_objectives.py): its checkpoints, how many turns and how much time it
has used against the budget, why it is paused, and whether an interrupted turn waits for the customer or is resumed for them. Resuming itself stays where it was:
POST /v1/conversations/<id>/goal {"action": "resume"}.
"""
from django.http import JsonResponse

from agentai_platform.goal_objectives import GoalObjectives
from agentai_platform.lifecycle.types import Conflict
from . import wiring
from .services import audit
from .views import customer, endpoint

FIELDS = ('resume_policy', 'max_turns', 'max_hours')


def _service():
    return GoalObjectives(wiring.store())


@endpoint(['GET'])
def listing(request):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'objectives': _service().listing(wiring.principal(request))})


def _number(text, low, high):
    if not text.isdigit() or not low <= int(text) <= high:
        raise ValueError('out of range')
    return int(text)


@endpoint(['GET', 'POST'], fields=FIELDS, field_limits={name: 8 for name in FIELDS})
def detail(request, objective_id):
    denied = customer(request)
    if denied:
        return denied
    service, principal = _service(), wiring.principal(request)
    if request.method == 'GET':
        return JsonResponse(service.get(principal, objective_id))
    data = request.input
    if not data:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    policy = data.get('resume_policy')
    turns = _number(data['max_turns'], 1, 500) if 'max_turns' in data else None
    seconds = _number(data['max_hours'], 1, 720) * 3600 if 'max_hours' in data else None
    try:
        view = service.configure(principal, objective_id, resume_policy=policy, max_turns=turns, max_seconds=seconds)
    except Conflict:
        return JsonResponse({'error': 'request_conflict'}, status=409)
    audit(request.user.pk, request.account_id, objective_id, 'objective.configure', 'completed', request.request_id)
    return JsonResponse(view)


@endpoint(['POST'])
def cancel(request, objective_id):
    """Cancel a job for good: it never continues or resumes. Its running or waiting turn is stopped like any task."""
    denied = customer(request)
    if denied:
        return denied
    service, principal = _service(), wiring.principal(request)
    view = service.get(principal, objective_id)                 # 404 for someone else's
    children = service.cancel(principal, objective_id)
    chat = wiring.chat_service()
    stopped = 0
    for request_id in children + [c['receipt_id'] for c in view['checkpoints'][-1:] if c.get('receipt_id')]:
        try:
            chat.cancel(principal, request_id)
            stopped += 1
        except Exception:
            pass                                                # already over, or not a request: nothing to stop
    audit(request.user.pk, request.account_id, objective_id, 'objective.cancel', 'completed', request.request_id)
    return JsonResponse({**service.get(principal, objective_id), 'stopped': stopped})
