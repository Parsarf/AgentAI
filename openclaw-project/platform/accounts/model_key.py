"""Settings → your own model: save, see and remove the API key the assistant should use instead of Lumina's models. Scoped to the signed-in account.

The key is tested with one tiny request, then stored encrypted; it is never returned again (only its last four characters) and never logged. See agentai_platform/model_keys.py for
how it is kept and used, and for what the endpoint address must satisfy."""
from django.conf import settings
from django.http import JsonResponse
from agentai_platform import model_keys as mk
from .services import audit, rate
from .views import endpoint, customer


def store():
    return mk.ModelKeyStore(settings.MODEL_KEY_STORE, mk.ModelKeyring.derived(settings.SECRET_KEY, settings.MODEL_KEY_FILE or None))


def enabled(account_id) -> bool:
    return mk.enabled_for(mk.read_engine(settings.ENGINE_FILE), account_id)


def active(account_id) -> bool:
    """Is this account running on its own model key right now? Asked on every send: true only when they chose it AND their assistant is seen running on it. If anything is
    unreadable the answer is no, and Lumina's own limits apply."""
    try:
        return enabled(account_id) and mk.unmetered(mk.ModelKeyStore(settings.MODEL_KEY_STORE).public(account_id))
    except Exception:
        return False


def _facts(pub):
    return {'host': pub['host'], 'model': pub['model'], 'hint': pub['hint'], 'using': 'own' if pub['use_own'] else 'lumina', 'applied': pub['applied']}


@endpoint(['GET'])
def state(request):
    denied = customer(request)
    if denied:
        return denied
    if not enabled(request.account_id):
        return JsonResponse({'available': False, 'configured': False})
    pub = mk.ModelKeyStore(settings.MODEL_KEY_STORE).public(request.account_id)
    return JsonResponse({'available': True, 'configured': pub is not None, **(_facts(pub) if pub else {})})


@endpoint(['POST'], ['base_url', 'api_key', 'model'], field_limits={'base_url': 400, 'api_key': 600, 'model': 120})
def save(request):
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.save', request.account_id, 6, 600)
    if not enabled(request.account_id):
        return JsonResponse({'error': 'not_available'}, status=409)
    data = request.input
    try:
        endpoint_ = mk.parse_endpoint(data.get('base_url'))
        model, key = mk.clean_model(data.get('model')), mk.clean_key(data.get('api_key'))
        mk.probe(endpoint_, model, key)                                                          # one tiny request: the address, the key and the model name all have to work
        pub = store().put(request.account_id, endpoint_, model, key)
    except mk.ModelKeyError as exc:
        return JsonResponse({'error': 'model_key_invalid', 'message': str(exc), 'detail': str(exc)}, status=422)
    audit(request.user.pk, request.account_id, 'model_key', 'model_key.save', 'completed', request.request_id)      # the fact that it was saved; never what it was
    return JsonResponse({'configured': True, **_facts(pub), 'applies': 'the next time your assistant starts'})


@endpoint(['POST'], ['use'])
def use(request):
    """Switch between the saved own model ('own') and Lumina's models ('lumina'). The key stays saved. Takes effect when the assistant next starts."""
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.use', request.account_id, 30, 600)
    if not enabled(request.account_id):
        return JsonResponse({'error': 'not_available'}, status=409)
    choice = request.input.get('use')
    if choice not in ('own', 'lumina'):
        return JsonResponse({'error': 'invalid_request'}, status=400)
    pub = mk.ModelKeyStore(settings.MODEL_KEY_STORE).set_use(request.account_id, choice == 'own')
    if pub is None:
        return JsonResponse({'error': 'no_key', 'message': 'Save your own model key first.'}, status=409)
    audit(request.user.pk, request.account_id, 'model_key', 'model_key.use_' + choice, 'completed', request.request_id)
    return JsonResponse({'configured': True, **_facts(pub), 'applies': 'the next time your assistant starts'})


@endpoint(['POST'], [])
def remove(request):
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.remove', request.account_id, 12, 600)
    removed = mk.ModelKeyStore(settings.MODEL_KEY_STORE).delete(request.account_id)
    if removed:
        audit(request.user.pk, request.account_id, 'model_key', 'model_key.remove', 'completed', request.request_id)
    return JsonResponse({'configured': False, 'removed': removed, 'applies': 'the next time your assistant starts'})
