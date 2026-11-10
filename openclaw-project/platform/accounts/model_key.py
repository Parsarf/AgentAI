"""Account-scoped saved model keys and active model choice."""
from django.conf import settings
from django.db import connection, transaction
from django.http import JsonResponse
from agentai_platform import model_keys as mk, model_catalog
from .services import audit, rate
from .views import endpoint, customer


def store():
    return mk.ModelKeyStore(settings.MODEL_KEY_STORE, mk.ModelKeyring.derived(settings.SECRET_KEY, settings.MODEL_KEY_FILE or None))


def enabled(account_id):
    return mk.enabled_for(mk.read_engine(settings.ENGINE_FILE), account_id)


def active(account_id):
    try:
        return enabled(account_id) and mk.ModelKeyStore(settings.MODEL_KEY_STORE).public(account_id) is not None
    except Exception:
        return False


def _state(account):
    choices = mk.ModelKeyStore(settings.MODEL_KEY_STORE).choices(account)
    keys = [{k: row[k] for k in ('id', 'host', 'model', 'hint')} for row in choices['keys']]
    pub = next((row for row in keys if row['id'] == choices['selected']), None)
    return {'available': enabled(account), 'configured': bool(keys), 'keys': keys, 'selected': choices['selected'],
            'lumina_models': [{'id': m['id'], 'name': m['name']} for m in model_catalog.models()],
            **({k: pub[k] for k in ('host', 'model', 'hint')} if pub else {})}


def _busy(account):
    # Called inside the same IMMEDIATE database transaction used by enqueue.
    # Settings cannot change between admission and completion/settlement.
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM customer_requests WHERE account_id=%s AND state IN ('waiting','starting','running','uncertain') LIMIT 1", [account])
        return c.fetchone() is not None


def _conflict():
    return JsonResponse({'error': 'model_busy', 'detail': 'Finish or stop your pending tasks before changing models or keys.'}, status=409)


@endpoint(['GET'])
def state(request):
    denied = customer(request)
    if denied:
        return denied
    try:
        return JsonResponse(_state(request.account_id))
    except mk.ModelKeyError:
        return JsonResponse({'error': 'model_settings_unavailable'}, status=503)


@endpoint(['POST'], ['base_url', 'api_key', 'model'], field_limits={'base_url': 400, 'api_key': 600, 'model': 120})
def save(request):
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.save', request.account_id, 6, 600)
    if not enabled(request.account_id):
        return JsonResponse({'error': 'not_available'}, status=409)
    try:
        with transaction.atomic():
            if _busy(request.account_id):
                return _conflict()
        data = request.input
        endpoint_ = mk.parse_endpoint(data.get('base_url'))
        model, key = mk.clean_model(data.get('model')), mk.clean_key(data.get('api_key'))
        mk.probe(endpoint_, model, key)
        # Probe outside the transaction; recheck work admitted while it ran.
        with transaction.atomic():
            if _busy(request.account_id):
                return _conflict()
            saved = store().add(request.account_id, endpoint_, model, key)
    except mk.ModelKeyError as exc:
        return JsonResponse({'error': 'model_key_invalid', 'detail': str(exc), 'message': str(exc)}, status=422)
    audit(request.user.pk, request.account_id, 'model_key', 'model_key.save', 'completed', request.request_id)
    return JsonResponse({**_state(request.account_id), **{k: saved[k] for k in ('host', 'model', 'hint')}, 'saved_id': saved['id'], 'applies': 'your next task after selecting it'})


@endpoint(['POST'], ['id'])
def select(request):
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.select', request.account_id, 30, 600)
    choice = request.input.get('id', '')
    if choice.startswith('key:') and not enabled(request.account_id):
        return JsonResponse({'error': 'not_available'}, status=409)
    try:
        with transaction.atomic():
            if _busy(request.account_id):
                return _conflict()
            mk.ModelKeyStore(settings.MODEL_KEY_STORE).select(request.account_id, choice)
    except mk.ModelKeyError:
        return JsonResponse({'error': 'model_unavailable', 'detail': 'Choose an available model.'}, status=422)
    audit(request.user.pk, request.account_id, 'model_key', 'model_key.select', 'completed', request.request_id)
    return JsonResponse({**_state(request.account_id), 'applies': 'your next task'})


@endpoint(['POST'], ['id'])
def remove(request):
    denied = customer(request)
    if denied:
        return denied
    rate('model_key.remove', request.account_id, 12, 600)
    try:
        with transaction.atomic():
            if _busy(request.account_id):
                return _conflict()
            storage = mk.ModelKeyStore(settings.MODEL_KEY_STORE)
            # Compatibility: old clients without an id remove all their keys.
            removed = storage.remove_profile(request.account_id, request.input['id']) if 'id' in request.input else storage.delete(request.account_id)
    except mk.ModelKeyError:
        return JsonResponse({'error': 'model_unavailable'}, status=422)
    if removed:
        audit(request.user.pk, request.account_id, 'model_key', 'model_key.remove', 'completed', request.request_id)
    return JsonResponse({**_state(request.account_id), 'removed': removed, 'applies': 'your next task'})
