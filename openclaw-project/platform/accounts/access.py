"""What your assistant can access, and the connected services built on the connector contract (roadmap #13, #14, #17).

    GET  /v1/controls                                  the whole picture: connections with what each may reach, tools, saved logins, the model key, memory, what acts without you
    GET  /v1/integrations                              the services that can be connected and the ones that are
    GET  /v1/integrations/<id>                         one connection: its grants, freshness, kinds of change, automatic approvals
    GET  /v1/integrations/<id>/resources               what the service offers to choose from (the picker)
    POST /v1/integrations/<id>/grants                  {"grants":[{"kind","id","name","access"}]}  replaces what it may reach ("*" = everything of a kind)
    POST /v1/integrations/<id>/remove                  ends the connection; answers with the receipt of what was stopped
    POST /v1/integrations/<id>/auto-approve            {"kind","enabled","include_irreversible"}
    POST /v1/integrations/synthetic/connect            test only (owner switch `synthetic_connector`): connects the fake service

Every line is generated from the records enforcement reads (agentai_platform/access.py). Tokens never appear in a response.
"""
from django.http import JsonResponse

from agentai_platform.connector_kit import ConnectorFault
from agentai_platform.connectors import ConnectorError, ConnectorNotConfigured
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.permissions import NotPermitted
from agentai_platform.workflows import WorkflowRefused
from . import wiring
from .services import audit, rate
from .views import customer, endpoint

FAULT_STATUS = {'refused': 403, 'not_found': 404, 'needs_customer': 409, 'conflict': 409, 'invalid': 400, 'retry_later': 503}


def guarded(fn):
    """Run a view body, turning the layer's own refusals into one fixed answer each (never a provider's text, never an exception's)."""
    try:
        return fn()
    except ConnectorFault as fault:
        return JsonResponse({'error': 'connector_' + fault.kind, 'message': fault.words, **({'retry_at': fault.retry_at} if fault.retry_at else {})}, status=FAULT_STATUS[fault.kind])
    except NotPermitted as refused:
        return JsonResponse({'error': 'not_permitted', 'needs': refused.action}, status=403)
    except WorkflowRefused as refused:
        return JsonResponse({'error': 'workflow_refused', 'message': str(refused)}, status=400)
    except Conflict as conflict:
        return JsonResponse({'error': 'request_conflict', 'message': str(conflict)[:200]}, status=409)
    except ConnectorNotConfigured:
        return JsonResponse({'error': 'connector_not_configured'}, status=503)
    except ConnectorError:
        return JsonResponse({'error': 'invalid_request'}, status=400)


def _off():
    return JsonResponse({'error': 'feature_off'}, status=503)


@endpoint(['GET'])
def controls(request):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse(wiring.access_overview().view(wiring.principal(request)))


def _one(principal, connection_id):
    view = wiring.access_overview().view(principal)
    return next((c for c in view['connections'] if c['id'] == connection_id), None)


@endpoint(['GET'])
def integrations(request, connection_id=None):
    denied = customer(request)
    if denied:
        return denied
    principal = wiring.principal(request)
    if connection_id is not None:
        found = _one(principal, connection_id)
        if found is None:
            return JsonResponse({'error': 'unavailable'}, status=404)
        return JsonResponse({'connection': found})
    connectors = wiring.connector_service()
    on = wiring.connectors_on(request.account_id)
    available = []
    for provider in connectors.registry.providers():
        declared = connectors.registry.declaration(provider)
        if provider == 'synthetic' and not wiring.switch_on('synthetic_connector'):
            continue
        available.append({'service': provider, 'label': declared.label, 'disclosure': declared.disclosure, 'resource_kinds': list(declared.resource_kinds),
                          'implementation': declared.implementation, 'can_change_things': bool(declared.write_kinds)})
    view = wiring.access_overview().view(principal)
    return JsonResponse({'available': available if on else [], 'connections': view['connections'], 'remote_tools': view['remote_tools'], 'linking_available': on,
                         'changes_available': wiring.writes_on(request.account_id)})


@endpoint(['GET'])
def resources(request, connection_id):
    denied = customer(request)
    if denied:
        return denied
    if not wiring.connectors_on(request.account_id):
        return _off()
    return guarded(lambda: JsonResponse({'resources': wiring.connector_client().resources(wiring.principal(request), connection_id)}))


@endpoint(['POST'], ['grants'], structured=True)
def grants(request, connection_id):
    denied = customer(request)
    if denied:
        return denied
    if not wiring.connectors_on(request.account_id):
        return _off()
    rate('connector.grants', request.account_id, 30, 600)
    principal = wiring.principal(request)

    def run():
        wiring.connector_service().set_grants(principal, connection_id, request.input.get('grants'))
        audit(request.user.pk, request.account_id, connection_id, 'connector.grants', 'completed', request.request_id)
        return JsonResponse({'connection': _one(principal, connection_id)})
    return guarded(run)


@endpoint(['POST'])
def remove(request, connection_id):
    """Always available, whatever the switches say: a connection can always be ended."""
    denied = customer(request)
    if denied:
        return denied
    return guarded(lambda: JsonResponse({'removed': True, 'receipt': wiring.connector_service().revoke(wiring.principal(request), connection_id, 'customer')}))


@endpoint(['POST'], ['kind', 'enabled', 'include_irreversible'], structured=True)
def auto_approve(request, connection_id):
    denied = customer(request)
    if denied:
        return denied
    if not wiring.writes_on(request.account_id):
        return _off()
    _connectors, _client, actions, _workflows = wiring.action_services()
    data = request.input
    if not isinstance(data.get('kind'), str):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    return guarded(lambda: JsonResponse({'automatic_approvals': actions.set_auto(wiring.principal(request), connection_id, data['kind'], data.get('enabled'),
                                                                                include_irreversible=bool(data.get('include_irreversible', False)))}))


@endpoint(['POST'])
def synthetic_connect(request):
    """Test only. Connects the fake service to the caller's account, with a token made here. Refused unless the owner switch is on and custody is set up."""
    denied = customer(request)
    if denied:
        return denied
    if not wiring.switch_on('synthetic_connector'):
        return _off()
    from agentai_platform.synthetic_connector import SyntheticBench
    principal = wiring.principal(request)

    def run():
        connection = wiring.connector_service().connect_declared(principal, 'synthetic', 'test@synthetic.lumina', tokens=SyntheticBench.tokens(request.account_id),
                                                                 scopes=('notes', 'messages'), expires_in=3600)
        return JsonResponse({'connection': _one(principal, connection)}, status=201)
    return guarded(run)
