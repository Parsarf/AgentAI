"""Authenticated transport for lifecycle metadata; contains no host credentials."""
from django.http import JsonResponse
from agentai_platform.security import Principal
from agentai_platform.lifecycle.coordinator import Coordinator
from agentai_platform.lifecycle.types import Conflict
from .services import operator_scope
from .views import endpoint, customer

from . import wiring


def coordinator(): return Coordinator(wiring.store())

@endpoint(['GET'])
def operations(request, operation_id=None):
    denied=customer(request)
    if denied: return denied
    result=coordinator().get(wiring.principal(request),operation_id)
    return JsonResponse({'operation':result} if operation_id else {'operations':result})

@endpoint(['POST'], ['kind','key','generation','profile','backup_ref'])
def provision(request, account):
    if not request.user.is_authenticated: return JsonResponse({'error':'authentication_required'},status=401)
    kind=request.input.get('kind','')
    from agentai_platform.lifecycle.types import KINDS
    if kind not in KINDS: raise ValueError('unsupported operation')
    operator_scope(request,account,'lifecycle_'+kind)
    generation=request.input.get('generation')
    if generation is not None:
        if not generation.isdecimal() or len(generation)>10: raise ValueError('invalid generation')
        generation=int(generation)
    try:
        result=coordinator().request(Principal(account,str(request.user.pk),'operator'),kind=kind,
            key=request.input.get('key',''),generation=generation,
            target_profile=request.input.get('profile','trial-unmeasured-v1'),
            backup_ref=request.input.get('backup_ref'))
        return JsonResponse({'operation':result,'runtime_enabled':False},status=202)
    except Conflict: return JsonResponse({'error':'operation_conflict'},status=409)

@endpoint(['POST'])
def retry(request, account, operation_id):
    if not request.user.is_authenticated: return JsonResponse({'error':'authentication_required'},status=401)
    # Scope rechecked in the coordinator. Lookup never crosses account bindings.
    try:
        with coordinator().store.connect() as con: row=coordinator()._row(con,account,operation_id)
        operator_scope(request,account,'lifecycle_'+row['kind'])
        result=coordinator().retry(Principal(account,str(request.user.pk),'operator'),operation_id)
        return JsonResponse({'operation':result,'runtime_enabled':False},status=202)
    except Conflict: return JsonResponse({'error':'operation_conflict'},status=409)
