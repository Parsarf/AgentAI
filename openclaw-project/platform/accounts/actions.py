"""Changes in connected services that wait for, or have had, the customer's decision (roadmap #26, #27, #28, #29, #83).

    GET  /v1/actions                       recent changes: prepared, approved, done, undone ...
    GET  /v1/actions/<id>                  one change with its preview (rendered from the stored payload) and its payload hash
    POST /v1/actions/<id>/approve          {"payload_hash": "..."}  approves exactly that payload, nothing else   (+ "account": a member's account, for an admin)
    POST /v1/actions/<id>/decline
    POST /v1/actions/<id>/undo             prepares the inverse as a new change (which is then approved like any other)
    POST /v1/actions/<id>/compensate       {"kind": "..."}  prepares a follow-up the write kind registered
    GET  /v1/workflows/<id>                a workflow with every step's preview
    POST /v1/workflows/<id>/approve        {"steps_hash": "..."}  one approval for all the steps
    POST /v1/workflows/<id>/decline
    GET  /v1/handoffs                      what is waiting for the customer (approvals and questions), and how long each kind of wait lasts
    POST /v1/handoffs/<id>/answer          {"answer": "..."}  answers a question

Approving only records the decision. The change itself is sent by the request worker's action pass, once (agentai_platform/actions.py).
"""
from django.http import JsonResponse

from agentai_platform import handoff
from . import wiring
from .access import guarded
from .services import audit, rate
from .views import customer, endpoint


def _services():
    return wiring.action_services()


@endpoint(['GET'])
def listing(request):
    denied = customer(request)
    if denied:
        return denied
    _c, _cl, actions, _w = _services()
    principal = wiring.principal(request)
    out = {'actions': actions.listing(principal, request_id=request.GET.get('request') or None)}
    if principal.org_role in ('owner', 'admin'):
        out['awaiting_admin'] = actions.awaiting_admin(principal)
    return JsonResponse(out)


@endpoint(['GET'])
def detail(request, action_id):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'action': _services()[2].get(wiring.principal(request), action_id)})


@endpoint(['POST'], ['payload_hash', 'account'], field_limits={'payload_hash': 64, 'account': 64})
def approve(request, action_id):
    denied = customer(request)
    if denied:
        return denied
    rate('action.decide', request.account_id, 60, 600)

    def run():
        action = _services()[2].approve(wiring.principal(request), action_id, request.input.get('payload_hash', ''), member_account=request.input.get('account') or None)
        audit(request.user.pk, request.account_id, action_id, 'action.approve', 'completed', request.request_id)
        return JsonResponse({'action': action})
    return guarded(run)


@endpoint(['POST'])
def decline(request, action_id):
    denied = customer(request)
    if denied:
        return denied
    return guarded(lambda: JsonResponse({'action': _services()[2].decline(wiring.principal(request), action_id)}))


@endpoint(['POST'])
def undo(request, action_id):
    denied = customer(request)
    if denied:
        return denied
    rate('action.decide', request.account_id, 60, 600)
    return guarded(lambda: JsonResponse({'action': _services()[2].undo(wiring.principal(request), action_id)}, status=201))


@endpoint(['POST'], ['kind'], field_limits={'kind': 40})
def compensate(request, action_id):
    denied = customer(request)
    if denied:
        return denied
    rate('action.decide', request.account_id, 60, 600)
    return guarded(lambda: JsonResponse({'action': _services()[2].compensate(wiring.principal(request), action_id, request.input.get('kind', ''))}, status=201))


@endpoint(['GET'])
def workflow(request, workflow_id):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'workflow': _services()[3].get(wiring.principal(request), workflow_id)})


@endpoint(['POST'], ['steps_hash'], field_limits={'steps_hash': 64})
def workflow_approve(request, workflow_id):
    denied = customer(request)
    if denied:
        return denied
    rate('action.decide', request.account_id, 60, 600)
    return guarded(lambda: JsonResponse({'workflow': _services()[3].approve(wiring.principal(request), workflow_id, request.input.get('steps_hash', ''))}))


@endpoint(['POST'])
def workflow_decline(request, workflow_id):
    denied = customer(request)
    if denied:
        return denied
    return guarded(lambda: JsonResponse({'workflow': _services()[3].decline(wiring.principal(request), workflow_id)}))


@endpoint(['GET'])
def handoffs(request):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'waiting': handoff.Handoffs(wiring.store()).pending(wiring.principal(request)), 'waits': handoff.waits_public()})


@endpoint(['POST'], ['answer'], field_limits={'answer': 2000})
def handoff_answer(request, handoff_id):
    denied = customer(request)
    if denied:
        return denied
    rate('action.decide', request.account_id, 60, 600)
    return guarded(lambda: JsonResponse({'handoff': handoff.Handoffs(wiring.store()).answer(wiring.principal(request), handoff_id, request.input.get('answer', ''))}))
