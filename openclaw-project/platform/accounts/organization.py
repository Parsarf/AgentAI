"""The caller's organization: its members with their roles, and what it decides for them (roadmap #12, #15).

    GET  /v1/organization                              members, your role, what you may do, and the policy (with which settings are set for you)
    POST /v1/organization/members/<actor>/role         {"role": "admin" | "member" | "viewer" | "owner"}
    POST /v1/organization/members/<actor>/remove       takes the person out and starts the offboarding of their account's data
    GET  /v1/organization/policy                       the policy
    POST /v1/organization/policy                       {"key": "...", "value": ...}   value null = the member decides again

Every customer is an organization of one today, whose owner they are. Inviting people comes later; the checks are already here.
"""
from django.http import JsonResponse

from . import wiring
from .access import guarded
from .services import audit, rate
from .views import customer, endpoint


@endpoint(['GET'])
def organization(request):
    denied = customer(request)
    if denied:
        return denied
    return guarded(lambda: JsonResponse({'organization': wiring.organization_service().view(wiring.principal(request))}))


@endpoint(['POST'], ['role'], field_limits={'role': 12})
def member_role(request, actor_id):
    denied = customer(request)
    if denied:
        return denied
    rate('organization.change', request.account_id, 30, 600)

    def run():
        service = wiring.organization_service()
        service.set_role(wiring.principal(request), actor_id, request.input.get('role', ''))
        audit(request.user.pk, request.account_id, actor_id, 'organization.role', 'completed', request.request_id)
        return JsonResponse({'organization': service.view(wiring.principal(request))})
    return guarded(run)


@endpoint(['POST'])
def member_remove(request, actor_id):
    denied = customer(request)
    if denied:
        return denied
    rate('organization.change', request.account_id, 30, 600)

    def run():
        service, principal = wiring.organization_service(), wiring.principal(request)
        account = service.remove_member(principal, actor_id)
        job = wiring.account_jobs().start_offboarding_by_operator(account, 'organization:' + principal.actor_id)      # the removed person's own data leaves with them
        audit(request.user.pk, request.account_id, actor_id, 'organization.remove', 'completed', request.request_id)
        return JsonResponse({'organization': service.view(principal), 'offboarding_job': job})
    return guarded(run)


@endpoint(['GET', 'POST'], ['key', 'value'], structured=True)
def policy(request):
    denied = customer(request)
    if denied:
        return denied
    service, principal = wiring.organization_service(), wiring.principal(request)
    if request.method == 'GET':
        return guarded(lambda: JsonResponse({'policy': service.view(principal)['policy']}))
    rate('organization.change', request.account_id, 30, 600)
    data = request.input
    if not isinstance(data.get('key'), str) or 'value' not in data:
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        view = service.set_policy(principal, data['key'], data['value'])
        from agentai_platform import safety
        from django.conf import settings
        if getattr(settings, 'SAFETY_SNAPSHOT_FILE', ''):
            try:
                with wiring.store().connect() as con:
                    safety.export_snapshot(con, settings.SAFETY_SNAPSHOT_FILE)      # the other processes read the organization scope from the same file
            except OSError:
                pass
        audit(request.user.pk, request.account_id, data['key'][:40], 'organization.policy', 'completed', request.request_id)
        return JsonResponse({'organization': view})
    return guarded(run)
