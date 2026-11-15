"""GET /v1/estimates/<kind>: how long and how much a task of this kind is likely to take, from finished tasks (agentai_platform/estimates.py). Informational only."""
from django.http import JsonResponse

from agentai_platform import estimates
from . import wiring
from .views import customer, endpoint


@endpoint(['GET'])
def estimate(request, kind):
    denied = customer(request)
    if denied:
        return denied
    with wiring.store().connect() as con:
        found = estimates.estimate(con, request.account_id, kind)      # ValueError (unknown kind) -> 400 by the wrapper
    return JsonResponse({'estimate': found})
