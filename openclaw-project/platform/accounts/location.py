"""Session/CSRF protected customer-device location handoff."""
from django.http import JsonResponse
from agentai_platform.location import Locations
from . import wiring
from .services import rate
from .views import customer, endpoint


def service():
    return Locations(wiring.store())


@endpoint(['GET'])
def pending(request):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'request': service().pending(request.account_id)})


@endpoint(['POST'], ['client_id', 'action', 'status', 'position'], structured=True)
def answer(request, location_id):
    denied = customer(request)
    if denied:
        return denied
    rate('location.answer', request.account_id, 300, 600)
    return JsonResponse(service().answer(request.account_id, location_id, request.input))
