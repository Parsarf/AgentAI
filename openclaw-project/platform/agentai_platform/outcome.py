"""What Lumina can say about how a task ended, from facts it holds itself. The runtime owns the run; this module owns the customer-facing verdict.

Two questions that used to be one:

* Did the run finish? The runtime answers (agent.wait). That is execution completion.
* Did the customer get what they asked for? Only evidence Lumina holds can say so: the browser's own end state and the steps it took, files saved during the
  task, and the goal state the runtime keeps. The assistant's own words are never evidence, so a run that ends with a confident "all done" and nothing behind it is
  reported as completed but unverified, and a browser that stopped at a page it could not pass is never worded as success.

Everything is a fixed vocabulary: no model writes the verdict, and no page text reaches it.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

OUTCOMES = ('completed', 'partial', 'blocked', 'failed', 'cancelled')
VERIFICATION = ('verified', 'unverified', 'not_applicable')
CART_ADD = re.compile(r'\b(add|cart|basket|bag|buy)\b', re.I)
CART_URL = re.compile(r'(cart|basket|bag|checkout)', re.I)
GOAL_HELD = ('paused', 'budget_limited', 'usage_limited')

BROWSER_WORDS = {
    'handoff': 'the browser stopped where it needs you (a payment, a sign-in or a check only a person can do); nothing was purchased or submitted',
    'blocked': 'the browser was not allowed to open that site',
    'budget': 'the browser stopped because the spending limit for this task was reached',
    'stuck': 'the browser got stuck repeating the same step',
    'deadline': 'the browser ran out of time',
    'max_steps': 'the browser reached its step limit',
    'error': 'the browser run failed',
    'stopped': 'the browser could not complete this',
    'cancelled': 'the browser was stopped',
}


@dataclass(frozen=True)
class Verdict:
    outcome: str            # completed | partial | blocked | failed | cancelled
    verification: str       # verified | unverified | not_applicable
    note: str               # one plain sentence, from the fixed vocabulary
    line: str               # added after the assistant's last reply when the task did not simply succeed ('' otherwise)


def cart_facts(steps) -> bool:
    """Did a click on an add/cart control change the page? Labels and results only: the stored steps hold no page text."""
    return any(r.get('action') == 'click' and r.get('result') == 'ok' and r.get('changed') is True and CART_ADD.search(str(r.get('label') or '')) for r in steps or [])


def browser_evidence(jobs, steps) -> tuple:
    """-> (the last job's end state or '', what that supports): 'verified' (a cart page and a click that added to it), 'unverified' (a claim the page does not back, or a job that did not
    finish), 'not_applicable' (looking something up: there is nothing to confirm). `jobs` are the request's browser jobs, oldest first, each {'state','url','reason'}."""
    if not jobs:
        return '', 'not_applicable'
    last = jobs[-1]
    state = str(last.get('state') or '')
    if state != 'done':
        return state, 'unverified'
    if CART_URL.search(str(last.get('url') or '')):
        return state, 'verified' if cart_facts(steps) else 'unverified'
    return state, 'not_applicable'


def judge(*, native, goal=None, jobs=(), steps=(), artifacts=0, cancelled=False, reply=True, goal_continuing=False) -> Verdict:
    """native: the last wait() result {'status','aborted','error'}; goal: the runtime's goal {'status', 'note'} or None; jobs/steps: the request's browser evidence;
    artifacts: files saved during the task; reply: the run produced something to show; goal_continuing: Lumina is about to admit another turn of the goal."""
    if cancelled:
        return Verdict('cancelled', 'not_applicable', 'Stopped at your request.', '')
    if native.get('status') != 'ok':
        why = 'The assistant took too long and was stopped.' if 'timeout' in str(native.get('error') or '') else 'The run ended with an error before it finished.'
        return Verdict('failed', 'unverified', why, '')
    state, verification = browser_evidence(jobs, steps)
    if not jobs and artifacts > 0:
        verification = 'verified'                        # a file the task was meant to produce exists
    if goal and goal.get('status') == 'blocked':
        note = 'The assistant reports it is blocked' + (': ' + goal['note'] if goal.get('note') else '') + '.'
        return Verdict('blocked', 'unverified', note, 'Stopped: ' + note)
    if goal and goal.get('status') in GOAL_HELD:
        note = 'The goal was paused before it was reached' if goal['status'] == 'paused' else 'The goal stopped because its budget was used up'
        return Verdict('partial', 'unverified', note + '.', 'Stopped: ' + note + '.')
    if goal and goal.get('status') == 'active':
        note = 'Still working towards the goal.' if goal_continuing else 'The goal is not reached yet.'
        return Verdict('partial', 'unverified', note, '' if goal_continuing else 'Stopped: ' + note)
    if jobs and state != 'done':
        note = BROWSER_WORDS.get(state, 'the browser did not finish')
        blocked = state == 'blocked' or 'verify you are human' in str(jobs[-1].get('reason') or '')
        text = note[0].upper() + note[1:] + '.'
        return Verdict('blocked' if blocked else 'partial', 'unverified', text, 'Stopped: ' + note + '.')
    if not reply:
        return Verdict('partial', 'unverified', 'The assistant finished without a reply.', '')
    if goal and goal.get('status') == 'complete' and verification == 'not_applicable':
        return Verdict('completed', 'unverified', 'The assistant reports the goal is met; nothing Lumina can check confirms it.', '')
    if verification == 'unverified':
        return Verdict('completed', 'unverified', "Done, but I couldn't confirm it from the page.", "Done, but I couldn't confirm it from the page.")
    return Verdict('completed', verification, 'Done.', '')
