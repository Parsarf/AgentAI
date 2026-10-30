"""Idle sleep and on-demand wake planning; pure decisions, no effects.

The trial profile allows at most one running customer cell. These functions turn
observed facts (supplied by the app/ledger, re-verified by the supervisor's own
admission) into a fixed plan. A cell is only ever stopped after a safe drain
point: nothing running, nothing mid-approval, nothing queued. Waking never stops
a cell that has live work, and never touches the owner workload.
"""
from dataclasses import dataclass

IDLE_AFTER_SECONDS = 45 * 60      # an assistant cell with nothing running, queued or waiting is stopped after this long (was 15 minutes)


@dataclass(frozen=True)
class CellFacts:
    account_id: str
    state: str                  # 'running' | 'stopped'
    last_activity_epoch: float
    running_tasks: int
    queued_tasks: int
    pending_approvals: int
    maintenance: bool = False   # backup/upgrade/restore in flight


def can_sleep(facts: CellFacts, now: float, *, idle_after=IDLE_AFTER_SECONDS) -> bool:
    if facts.state != 'running' or facts.maintenance:
        return False
    if facts.running_tasks or facts.queued_tasks or facts.pending_approvals:
        return False
    return now - facts.last_activity_epoch >= idle_after


def wake_plan(target: CellFacts, running: list, now: float, *, idle_after=IDLE_AFTER_SECONDS):
    """Plan to run work for `target`: ('start',) | ('stop', other, 'start') | ('wait', reason)."""
    if target.state == 'running':
        return ('ready',)
    others = [c for c in running if c.state == 'running' and c.account_id != target.account_id]
    if not others:
        return ('start',)
    if len(others) > 1:
        return ('wait', 'multiple cells running; reconciliation required')
    other = others[0]
    if can_sleep(other, now, idle_after=idle_after):
        return ('stop', other.account_id, 'start')
    return ('wait', 'another account has active work')  # never discloses which
