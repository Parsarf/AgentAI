"""The assistant panel beside every page of the web app (UI remodel, phase 2).

    POST /v1/assistant/ask     {"conversation_id","message","key","looking_at"?}   a message to the assistant from the panel, with what is selected in the page (ids only)

It is an ordinary message in an ordinary chat (same queue, admission and limits as Chat); what is selected goes with it as ids the server checked
(agentai_platform/selection.py). Mail and calendar selections pass only while that feature is on; with it off they are dropped and the message still goes.
"""
from django.http import JsonResponse

from agentai_platform import selection
from . import wiring
from .services import rate
from .views import customer, endpoint


@endpoint(['POST'], ['conversation_id', 'message', 'key', 'looking_at'], structured=True)
def ask(request):
    denied = customer(request)
    if denied:
        return denied
    rate('assistant.ask', request.account_id, 120, 600)
    from agentai_platform.budget import BudgetDenied
    from agentai_platform.chat import denial_category
    from agentai_platform.lifecycle.types import Conflict
    from agentai_platform.security import NotFound
    from .chat import service as chat_service
    given = request.input
    message, conversation, key = given.get('message'), given.get('conversation_id'), given.get('key')
    if not all(isinstance(v, str) and v for v in (message, conversation, key)) or len(message) > 16000:
        return JsonResponse({'error': 'invalid_request'}, status=400)
    principal = wiring.principal(request)
    try:
        hub = wiring.hub_service() if wiring.hub_on(request.account_id) else None
        looking = selection.check(wiring.store(), principal, given.get('looking_at'), hub=hub)
        result = chat_service().send(principal, conversation_id=conversation, message=message, key=key, mode='text', ui='basic', dashboard_context=looking)
        return JsonResponse({'request': result, 'looking_at': looking}, status=202)
    except Conflict:
        return JsonResponse({'error': 'request_conflict'}, status=409)
    except BudgetDenied as error:
        return JsonResponse({'error': 'budget_denied', 'category': denial_category(error)}, status=402)
    except NotFound:
        return JsonResponse({'error': 'not_found'}, status=404)
    except ValueError:
        return JsonResponse({'error': 'invalid_request'}, status=400)
