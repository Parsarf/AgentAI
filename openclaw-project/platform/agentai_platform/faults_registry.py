"""Every reason something can fail or stop for, in one table (reliability plan, Part 1). Data only; `faults.py` is the code that uses it.

A reason is `feature.cause`. Each one says what KIND of failure it is (the closed list in faults.KINDS, which decides whether it may be tried again), WHO must act, the one
sentence the customer reads (what happened, who acts, the next step), the one the assistant reads (naming the fix), whether the owner is told at once, and whether it is an
expected stop rather than an error (a limit the customer set, a wait for the customer): expected stops are counted, but never in an error rate.

A reason that is not in this table cannot be raised (faults.Fault refuses it, and tests/test_faults.py checks every row), so a new failure cannot appear without its
sentence. Sentences name no provider, host or person and carry no text from a page, a message or the runtime.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    kind: str                # one of faults.KINDS
    actor: str               # assistant | customer | owner | nobody
    customer: str            # what the customer reads
    assistant: str = ''      # what the assistant reads when the failure reaches it as a tool reply ('' = it never does)
    effect: str = 'nothing_changed'   # nothing_changed | partly_done | unknown: the default; a fault may say otherwise
    alert: bool = False      # tell the owner at once, with the request number
    expected: bool = False   # an expected stop, not an error


R = Reason
REASONS: dict[str, Reason] = {
    # -- the model provider (seen by Lumina's own model relay as a status code) ------------------------------------------------------------------------------
    'model.rate_limited': R('retry_later', 'nobody', 'The model provider was too busy to finish this task, even after waiting. Nothing is wrong with your request. '
                            'Please send it again in a minute; what was already done is kept in this conversation.', effect='partly_done'),
    'model.provider_error': R('retry_later', 'nobody', 'The model provider had a problem of its own and the task could not finish. Please send it again in a minute; '
                              'what was already done is kept in this conversation.', effect='partly_done'),
    'model.not_offered': R('needs_customer', 'customer', 'The model you chose could not be used for this task. Open Settings > Assistant > Models and choose another model, '
                           'or switch back to Lumina, then send your message again. Nothing was run.'),
    'model.own_key_refused': R('needs_customer', 'customer', 'Your own model provider refused the key saved in Lumina. Check or replace the key in Settings > Assistant > Models, '
                               'or switch back to Lumina, then send your message again.'),
    'model.lumina_key_refused': R('needs_owner', 'owner', 'Lumina could not reach its model provider. This is on our side and we have been told. Nothing more will run; '
                                  'please try again in a few minutes.', alert=True),
    'model.allowance_exhausted': R('limit', 'customer', 'Your Lumina model allowance is exhausted. Choose a saved personal model in Settings or contact the owner to review the allowance.',
                                   expected=True),
    'model.unreachable': R('internal', 'owner', 'Lumina could not reach its model service. This is on our side and we have been told. Please try again shortly.', alert=True),
    'model.bad_request': R('invalid', 'owner', 'The assistant could not finish this request because of a problem on our side, and we have been told. Please try again.', alert=True),
    'model.selection_changed': R('conflict', 'customer', 'Your model choice changed while this task was starting. Send your message again and it will use the model you selected.'),
    'model.too_many_calls': R('retry_later', 'nobody', 'The assistant was making model calls faster than is allowed and was slowed down. Please send your message again in a minute.'),
    # -- the run itself -----------------------------------------------------------------------------------------------------------------------------------
    'run.timeout': R('limit', 'customer', 'The assistant took too long and was stopped. Please try a smaller request.', effect='partly_done'),
    'run.unclassified': R('internal', 'owner', 'The assistant could not finish this request. Nothing more will run; please try again.', effect='unknown', alert=True),
    'cell.stopped_under_task': R('internal', 'owner', 'The assistant stopped unexpectedly. Please try again.', effect='unknown', alert=True),
    'cell.unreachable': R('internal', 'owner', 'The assistant could not be reached for this request, so it was stopped. Please try again.', effect='unknown', alert=True),
    'cell.not_started': R('internal', 'owner', 'Your request could not be started. Nothing was charged. Please send it again.', alert=True),
    # -- expected stops of a task ----------------------------------------------------------------------------------------------------------------------------
    'task.spending_limit': R('limit', 'customer', 'Your spending limit for this task was reached, so the work was stopped. You can change or remove the limit in Settings > Usage.',
                             effect='partly_done', expected=True),
    'task.waited_too_long': R('limit', 'customer', 'The task waited too long for you, so it was stopped.', effect='partly_done', expected=True),
    'task.needed_customer_unattended': R('needs_customer', 'customer', 'This scheduled run needed you, so it stopped. Open it to carry on.', effect='partly_done', expected=True),
    'task.goal_blocked': R('needs_customer', 'customer', 'The assistant reports it is blocked.', effect='partly_done', expected=True),
    'task.goal_held': R('limit', 'customer', 'The goal stopped before it was reached.', effect='partly_done', expected=True),
    'task.no_reply': R('internal', 'owner', 'The assistant finished without a reply.', effect='unknown', alert=True),
    # -- the browser, by the state its job ended in (browse/job_states.py). Part 3 splits `browser.failed` by cause. --------------------------------------------
    'browser.failed': R('internal', 'owner', 'The browser run failed.', 'The browser run failed. Do not retry the same browser task; use web_search and web_fetch for what can be read, '
                        'and say what could not be done.', effect='partly_done', alert=True),
    'browser.stopped': R('refused', 'nobody', 'The browser could not complete this.', effect='partly_done'),
    'browser.site_not_allowed': R('refused', 'nobody', 'The browser was not allowed to open that site.', effect='partly_done', expected=True),
    'browser.human_check': R('needs_customer', 'customer', 'The site asked to verify you are human, which only you can do.', effect='partly_done', expected=True),
    'browser.stuck': R('internal', 'nobody', 'The browser got stuck repeating the same step.', effect='partly_done'),
    'browser.deadline': R('limit', 'nobody', 'The browser ran out of time.', effect='partly_done'),
    'browser.max_steps': R('limit', 'nobody', 'The browser reached its step limit.', effect='partly_done'),
    'browser.interrupted': R('internal', 'owner', 'The browser task was interrupted by a restart of the browser service; what it had done is kept, and it was not resumed.',
                             effect='partly_done', alert=True),
    'browser.spending_limit': R('limit', 'customer', 'The browser stopped because the spending limit for this task was reached.', effect='partly_done', expected=True),
    'browser.needs_customer': R('needs_customer', 'customer', 'The browser stopped where it needs you (a payment, a sign-in or a check only a person can do); nothing was purchased or submitted.',
                                effect='partly_done', expected=True),
    'browser.stopped_with_task': R('refused', 'nobody', 'The browser was stopped.', effect='partly_done', expected=True),
    # -- connected services: the six kinds of the connector contract (connector_kit.FAULT_WORDS says the same to the assistant) --------------------------------
    'connector.retry_later': R('retry_later', 'nobody', 'The connected service stayed busy. Nothing was changed. It can be tried again later.',
                               'The service is busy or limiting requests right now. Nothing was changed. It can be tried again later.'),
    'connector.needs_customer': R('needs_customer', 'customer', 'The connection needs you (reconnect it in Settings). Nothing was changed.',
                                  'This connection needs the customer: it must be reconnected or given a permission it does not have.', expected=True),
    'connector.refused': R('refused', 'customer', 'This is not allowed by the connection, your choices or your organization. Nothing was changed.',
                           'This is not allowed: the connection, the customer\'s choices or their organization do not permit it.', expected=True),
    'connector.not_found': R('not_found', 'assistant', 'The item no longer exists in the connected service. Nothing was changed.',
                             'That item does not exist in the connected service, or this connection may not reach it.'),
    'connector.conflict': R('conflict', 'assistant', 'The item changed in the connected service since it was read. Nothing was overwritten.',
                            'The record changed in the connected service since it was read. Nothing was overwritten.'),
    'connector.invalid': R('invalid', 'assistant', 'The request was not valid for the connected service. Nothing was changed.',
                           'The request was not valid for the connected service. Nothing was changed.'),
    # -- anything nobody has classified yet: counted, alerted, and given a reason of its own in the next release ------------------------------------------------
    'internal.unclassified': R('internal', 'owner', 'Something went wrong on our side and we have been told. Please try again.', effect='unknown', alert=True),
}
del R
