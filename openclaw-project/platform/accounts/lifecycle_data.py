"""How long things are kept, taking your data with you, and leaving (roadmap #18 to #21).

    GET  /v1/retention                                 "How long we keep things": generated from the one retention table
    GET  /v1/exports                                   your exports
    POST /v1/exports                                   {"organization": "1"?}  ask for an archive of your data (an owner may ask for the whole organization)
    GET  /v1/exports/<id>                              one export
    POST /v1/exports/<id>/ticket                       a single-use download link that expires
    GET  /v1/exports/<id>/download?ticket=...          the archive (the link proves the caller; it works once)
    POST /v1/conversations/<id>/delete                 delete one chat
    GET  /v1/account/offboarding                       where closing the account stands, and what remains by design
    POST /v1/account/offboarding                       start closing the account
    POST /v1/account/offboarding/<export|skip|cancel>  export first / no export / changed my mind (possible until the deletion starts)

Export, deleting a chat and closing an account are behind the owner switch `account_self_service`. The retention page is always there.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.http import FileResponse, JsonResponse

from agentai_platform import retention as retention_rules
from agentai_platform.security import NotFound
from . import wiring
from .access import guarded
from .services import audit, rate
from .views import customer, endpoint


def _on():
    return wiring.switch_on('account_self_service')


def _off():
    return JsonResponse({'error': 'feature_off'}, status=503)


@endpoint(['GET'])
def retention(request):
    denied = customer(request)
    if denied:
        return denied
    return JsonResponse({'rules': retention_rules.public(), 'self_service': _on()})


@endpoint(['GET', 'POST'], ['organization'], field_limits={'organization': 1})
def exports(request, export_id=None):
    denied = customer(request)
    if denied:
        return denied
    if not _on():
        return _off()
    jobs, principal = wiring.account_jobs(), wiring.principal(request)
    if export_id is not None:
        found = jobs.get(principal, export_id)
        if found['kind'] != 'export':
            raise NotFound('unavailable')
        return JsonResponse({'export': found})
    if request.method == 'GET':
        return JsonResponse({'exports': jobs.listing(principal, 'export')})
    rate('data.export', request.account_id, 5, 86400)

    def run():
        job = jobs.request_export(principal, organization=request.input.get('organization') == '1')
        audit(request.user.pk, request.account_id, job['id'], 'data.export', 'pending', request.request_id)
        return JsonResponse({'export': job}, status=202)
    return guarded(run)


@endpoint(['POST'])
def export_ticket(request, export_id):
    denied = customer(request)
    if denied:
        return denied
    if not _on():
        return _off()
    rate('data.export.link', request.account_id, 20, 3600)
    return guarded(lambda: JsonResponse(wiring.account_jobs().export_ticket(wiring.principal(request), export_id)))


def export_download(request, export_id):
    """No session is needed or looked at: the single-use link proves the caller, as for a file download. Outside endpoint(): the body is a stream."""
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    jobs = wiring.account_jobs()
    parts, size = jobs.consume_export_ticket(export_id, request.GET.get('ticket', ''))        # NotFound -> 404 by the account middleware
    if jobs.storage is None:
        raise NotFound('unavailable')
    response = FileResponse(jobs.storage.open_private(parts), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="lumina-export.zip"'
    response['Content-Length'] = str(size)
    response['Cache-Control'] = 'no-store'
    return response


@endpoint(['POST'])
def delete_conversation(request, conversation_id):
    denied = customer(request)
    if denied:
        return denied
    if not _on():
        return _off()
    rate('data.delete', request.account_id, 30, 3600)

    def run():
        done = wiring.account_jobs().delete_conversation(wiring.principal(request), conversation_id)
        audit(request.user.pk, request.account_id, conversation_id, 'data.delete.conversation', 'completed', request.request_id)
        return JsonResponse({'deleted': done})
    return guarded(run)


@endpoint(['GET', 'POST'])
def offboarding(request, action=None):
    denied = customer(request)
    if denied:
        return denied
    if not _on():
        return _off()
    jobs, principal = wiring.account_jobs(), wiring.principal(request)
    if request.method == 'GET':
        if action is not None:
            return JsonResponse({'error': 'method_not_allowed'}, status=405)
        return JsonResponse({'offboarding': jobs.offboarding(principal), 'cooling_off_seconds': jobs.cooling_off})
    rate('account.offboarding', request.account_id, 10, 3600)
    if action not in (None, 'export', 'skip', 'cancel'):
        return JsonResponse({'error': 'invalid_request'}, status=400)

    def run():
        if action is None:
            view = jobs.start_offboarding(principal)
        elif action == 'cancel':
            view = jobs.cancel_offboarding(principal)
        else:
            view = jobs.choose_export(principal, action == 'export')
        audit(request.user.pk, request.account_id, request.account_id, 'account.offboarding.' + (action or 'start'), 'completed', request.request_id)
        return JsonResponse({'offboarding': view})
    return guarded(run)


def send_deletion_report(account_id, report) -> str:
    """The confirmation email of a finished deletion: fixed words and the counts of the verification, never content. Sent before the address itself is erased."""
    from django.contrib.auth.models import User
    users = list(User.objects.filter(identity__account_id=account_id, identity__role='customer').exclude(email='').exclude(email__endswith='@deleted.invalid'))
    if not users:
        return 'no_address'
    scan = report.get('verification') or {}
    lines = ['Your Lumina account has been deleted, as you asked.', '',
             'We checked every place your data was kept. ' + ('Nothing of yours is left in them.' if scan.get('clean') else 'Something could not be removed yet; we are looking at it and will write to you again.'),
             '', 'What remains, by design:'] + ['- ' + line for line in report.get('remains_by_design', [])] + ['', 'If you did not ask for this, reply to this message at once.']
    sent = 0
    for user in users:
        try:
            sent += send_mail('Your Lumina account has been deleted', '\n'.join(lines), settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        except Exception:
            pass                                            # the deletion itself does not wait for mail; the outcome is recorded in the job
    return 'sent' if sent else 'uncertain'
