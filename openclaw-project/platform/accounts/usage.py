from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from agentai_platform.budget import BudgetLedger,BudgetDenied
from agentai_platform.security import Principal,NotFound
from .lifecycle import AccountStore
from .services import Denied
from .views import endpoint,customer

@endpoint(['GET'])
def usage(request, page=False):
    denied=customer(request)
    if denied:return denied
    try:
        result=BudgetLedger(AccountStore(connection.settings_dict['NAME'])).summary(
            Principal(request.account_id,str(request.user.pk),'customer'))
        # Running estimates need a metered route adapter, not the task reservation.
        result['estimated_microusd']=None
        if page:
            def dollars(value):
                whole,fraction=divmod(value,1000000)
                digits=f'{fraction:06d}'.rstrip('0')
                return f'{whole}.{digits.ljust(2,"0")}'
            return render(request,'accounts/usage.html',{'usage':result,
                'reported_usd':dollars(result['reported_microusd']),
                'held_usd':dollars(result['held_microusd']),
                'remaining_usd':dollars(result['period_remaining_microusd'])})
        return JsonResponse(result)
    except BudgetDenied:
        if page:return render(request,'accounts/usage.html',{'unconfigured':True})
        return JsonResponse({'error':'usage_not_configured','live_provider_accounting_verified':False},status=503)
    except NotFound:raise Denied()
