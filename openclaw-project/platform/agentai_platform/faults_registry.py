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
    # -- one tool call (Part 3). Made by the tool that refused or failed, recorded by the tool relay with the call. The customer's sentence is what the step shows in the
    #    timeline; the assistant reads the tool's own words, which name the fix, and this table's only when the tool has none. -------------------------------------------
    'tool.bad_arguments': R('invalid', 'assistant', 'The assistant asked for this in a form the tool could not read. Nothing was changed; it can correct the call and try again.',
                            'The arguments were not valid for this tool. Nothing was changed. Read the tool description and send the call again with valid arguments.'),
    'tool.not_found': R('not_found', 'assistant', 'The assistant asked for something that is not there (a file, a message or an item). Nothing was changed.',
                        'That does not exist. Nothing was changed. Look up what exists first, then use its exact name or id.'),
    'tool.out_of_turn': R('conflict', 'assistant', 'The assistant sent a step the tool was not waiting for. Nothing was changed.',
                          'The tool was not waiting for this call. Nothing was changed.'),
    'tool.not_admitted': R('refused', 'nobody', 'This step did not belong to a running task, so nothing was done.',
                           'This tool call does not belong to an admitted live task. Nothing was started or changed. Do not retry this call in another task.'),
    'tool.origin_unavailable': R('internal', 'owner', 'Lumina could not confirm which task this step belonged to, so nothing was done. This is on our side and we have been told.',
                                 'This tool call does not belong to an admitted live task. Nothing was started or changed. Do not retry this call in another task.', alert=True),
    'tool.not_permitted': R('refused', 'customer', 'Your role or your organization does not allow this tool, so it was not used.',
                            'The customer\'s role or organization does not allow this tool. Nothing was done. Tell them, and carry on without it if you can.', expected=True),
    'tool.switched_off': R('refused', 'nobody', 'This is not switched on for your account, so the step was skipped.',
                           'This is not switched on for this customer. Nothing was done. Carry on without it and say what you would have done.', expected=True),
    'tool.unavailable': R('needs_owner', 'owner', 'A part of Lumina this step needs was not available, so it was not done. This is on our side and we have been told.',
                          'This is not available right now. Nothing was changed. Carry on without it, and tell the customer plainly what could not be done.', alert=True),
    'tool.not_answering': R('internal', 'owner', 'A part of Lumina this step needs did not answer, so it was not done. This is on our side and we have been told.',
                            'This did not answer right now. Nothing was changed. Try once more; if it fails again, tell the customer.', alert=True),
    'file.not_converted': R('invalid', 'assistant', 'The file could not be turned into the format asked for. The assistant can correct its source or deliver another format.',
                            'The file could not be converted. Nothing was delivered. Fix the source file, or deliver it in another format.'),
    'tool.busy': R('retry_later', 'nobody', 'Another step of the same kind was still running, so this one was held back.',
                   'Another tool call of this kind is still running for this task. Wait for it to finish, then send this call again.', expected=True),
    'tool.approval_needed': R('needs_customer', 'customer', 'This needs your approval before it runs. Nothing has run yet.',
                              'The customer must approve this exact call first. Nothing has run. Tell them briefly what you asked permission for and stop.', expected=True),
    'tool.approval_declined': R('refused', 'customer', 'This was declined or the approval ran out, so it did not run.',
                                'The customer declined this call, or its approval ran out. Nothing has run. Wait for a new instruction.', expected=True),
    'tool.needs_permission': R('needs_customer', 'customer', 'The connected account has not given Lumina permission for this. You can allow it on the connection\'s page.',
                               'The connected account has not given permission for this. Nothing was changed. Tell the customer where to allow it.', expected=True),
    'tool.stopped_with_task': R('refused', 'nobody', 'This step was stopped because the task was stopped.', 'The task was stopped, so this call was stopped. Nothing more was done.',
                                effect='unknown', expected=True),
    'tool.limit': R('limit', 'nobody', 'A limit for this task was reached, so this step was not run.',
                    'A limit for this task is reached. Nothing more was done. Answer with what you have and say what is left.', expected=True),
    'tool.refused': R('refused', 'nobody', 'This is not something Lumina does, so nothing was done.', 'This is not allowed. Nothing was done.'),
    'tool.storage_full': R('limit', 'customer', 'Your storage is full, so the file was not saved. Delete files you no longer need in Files.',
                           'The customer\'s storage is full. Nothing was saved. Tell them to delete files they no longer need in Files.', expected=True),
    'tool.remote_error': R('refused', 'nobody', 'The connected service answered with an error of its own.',
                           'The connected service answered with an error. Read its message; do not repeat a change without checking whether it already happened.'),
    'tool.unknown_outcome': R('unknown_outcome', 'nobody', 'It could not be confirmed whether this step went through in the connected service.',
                              'The outcome could not be confirmed. Check the service before doing anything further; do not retry automatically.', effect='unknown'),
    'tool.failed': R('internal', 'owner', 'This step failed on our side and we have been told. Nothing more was done by it.',
                     'Something went wrong on Lumina\'s side. Nothing was changed. Try once more; if it fails again, tell the customer.', effect='unknown', alert=True),
    # -- the runtime's own tools (web_fetch, web_search, exec), read from the result the runtime kept (faults.RUNTIME_TOOL_WORDS, the one table that matches text) ------
    'site.refused': R('refused', 'nobody', 'The website refused to show this page to the assistant.'),
    'site.not_found': R('not_found', 'nobody', 'That page does not exist on the website.'),
    'site.busy': R('retry_later', 'nobody', 'The website was limiting requests and did not answer.'),
    'site.error': R('retry_later', 'nobody', 'The website had an error of its own.'),
    'site.unreadable': R('invalid', 'nobody', 'The page opened but had nothing the assistant could read.'),
    'runtime.tool_not_offered': R('invalid', 'assistant', 'The assistant tried a tool that is not available in this task.'),
    'runtime.skipped_for_message': R('refused', 'nobody', 'This step was skipped because a new message from you arrived.', expected=True),
    'runtime.unreachable': R('retry_later', 'nobody', 'The connection dropped before this step could finish.'),
    'runtime.tool_failed': R('invalid', 'assistant', 'This step did not work. The assistant saw the error and could carry on.'),
    # -- anything nobody has classified yet: counted, alerted, and given a reason of its own in the next release ------------------------------------------------
    'internal.unclassified': R('internal', 'owner', 'Something went wrong on our side and we have been told. Please try again.', effect='unknown', alert=True),
}
del R
