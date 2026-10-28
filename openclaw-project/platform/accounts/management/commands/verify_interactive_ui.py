"""Bounded owner-only acceptance through the real admitted model route; never provisions a customer."""
import json
import time
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from accounts.chat import service, execution_on
from accounts.models import Identity
from agentai_platform.genui.artifacts import ArtifactStore, nodes
from agentai_platform.security import Principal


class Command(BaseCommand):
    help = 'Verify a real-model interactive artifact loop in an isolated owner conversation (paid, existing caps apply).'

    def add_arguments(self, parser):
        parser.add_argument('--run-live', action='store_true')
        parser.add_argument('--timeout', type=int, default=300)

    def handle(self, *args, **options):
        if not options['run_live']:
            raise CommandError('Pass --run-live to admit two bounded real-model requests against the configured owner account.')
        if not 30 <= options['timeout'] <= 600:
            raise CommandError('timeout must be from 30 to 600 seconds')
        owner = settings.SAFETY_OWNER_ACCOUNT
        identity = Identity.objects.filter(account_id=owner).first() if owner else None
        if not identity or not execution_on():
            raise CommandError('An existing owner identity and enabled customer_execution are required; no switches were changed.')
        principal = Principal(owner, str(identity.user_id), 'customer')
        chat = service()
        # All operations use the normal membership, entitlement, queue and reservation checks.
        project = next((p for p in chat.projects(principal) if p['name'] == 'Interactive UI launch acceptance'), None) or chat.create_project(principal, 'Interactive UI launch acceptance')
        conversation = chat.create_conversation(principal, project['id'])['id']
        self.stdout.write(json.dumps({'stage': 'created_isolated_owner_conversation', 'conversation_id': conversation}))
        run = uuid.uuid4().hex
        current = None
        def wait(request_id):
            deadline = time.monotonic() + options['timeout']
            while time.monotonic() < deadline:
                task = chat.task(principal, request_id)
                if task['state'] in ('completed', 'failed', 'cancelled'):
                    if task['state'] != 'completed' or task.get('outcome') not in ('completed', None):
                        raise CommandError('Acceptance request ended without completing; inspect its owner conversation.')
                    return task
                time.sleep(2)
            chat.cancel(principal, request_id)
            raise CommandError('Timed out; native cancellation requested. Inspect the owner task before retrying.')
        try:
            prompt = ('This is a launch acceptance test with illustrative data. Do not browse, contact anyone, schedule anything or change files except a draft for your UI validator. '
                      'Use Interactive answer style. Present one lumina-doc artifact containing a form with one required number field: id quantity, label Quantity, default 2, min 1, max 20; '
                      'submit label Calculate total, agent.request message Calculate the sample total at 10 USD per item. Also show a scenario_simulator with price 10 and quantity 2 using multiply. '
                      'Consult your lumina-ui component definitions and validate your document. On submission, update this SAME artifact with artifactId/baseVersion from server context, '
                      'preserve the form and node ids, and add a metric_card id total with the numeric calculated value in USD. Do not make a new artifact for the result.')
            current = chat.send(principal, conversation_id=conversation, message=prompt, key='launch-create-' + run, mode='auto', ui='interactive')['id']
            first = wait(current)
            self.stdout.write(json.dumps({'stage': 'first_request_completed'}))
            artifacts = [b for b in chat.blocks.list(principal, conversation) if b['kind'] == 'document']
            if len(artifacts) != 1: raise CommandError('Expected exactly one generated artifact; inspect the acceptance conversation.')
            artifact = artifacts[0]
            form = next((n for n in nodes(artifact['spec']) if n['type'] == 'form' and any(f['id'] == 'quantity' for f in n['props']['fields'])), None)
            if not form: raise CommandError('Model did not create the required interactive form.')
            store = ArtifactStore(chat.store)
            event = {'id': 'launch-event-' + run, 'node_id': form['id'], 'action_id': 'submit', 'version': artifact['version'], 'values': {'quantity': 4}}
            sent = store.event(principal, artifact['id'], event, chat)
            if store.event(principal, artifact['id'], event, chat) != sent: raise CommandError('Duplicate event did not replay the same result.')
            current = sent['id']; second = wait(current)
            reopened = [b for b in chat.blocks.list(principal, conversation) if b['kind'] == 'document']
            if len(reopened) != 1 or reopened[0]['id'] != artifact['id'] or reopened[0]['version'] <= artifact['version']:
                raise CommandError('Continuation did not update the same artifact.')
            final = reopened[0]
            if final['state'].get(form['id'], {}).get('values', {}).get('quantity') != 4:
                raise CommandError('Submitted input did not survive the update.')
            if not any(n['type'] == 'metric_card' and n['props'].get('value') == 40 for n in nodes(final['spec'])):
                raise CommandError('Model did not return the expected calculated total.')
            self.stdout.write(json.dumps({'result': 'passed', 'conversation_id': conversation, 'artifact_id': artifact['id'], 'version': final['version'],
                                          'same_artifact': True, 'saved_input': True, 'duplicate_event_replayed': True,
                                          'reported_cost_microusd': sum((t.get('usage') or {}).get('cost_microusd') or 0 for t in (first, second))}))
        except Exception:
            if current:
                task = chat.task(principal, current)
                if task['state'] not in ('completed', 'failed', 'cancelled'): chat.cancel(principal, current)
            raise
        # Preserve this clearly named conversation as operator evidence. Never delete billing receipts.
