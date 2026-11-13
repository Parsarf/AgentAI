"""Several browser tasks of one customer in one cell browser: who owns which tab, whose turn it is, and how many tabs are loaded at once.

Measured on a real 2 GiB cell (12 November 2026): the cell idles near 1.0 GiB, the browser adds about 0.35 GiB, and five light pages reach 1.97 GiB. So the owner's choice is:
up to ACTIVE_LIMIT tasks of a customer are active at once, but only LOADED_LIMIT of them have a tab loaded. A task whose turn comes while it has no tab gets its page opened
again at the address it was on; to make room, the task that has gone longest without a step has its tab closed. Sign-ins survive this (they live in the browser profile, which
every task of the customer shares); a half-filled form or a scroll position does not, and the task is told its page was reopened.

Steps are taken in turn: one lock per account covers a whole command (bring my tab to the front, act, read the result). That is what makes a new tab attributable (a tab
that appears during my step is mine) and keeps a picture or a click from landing in another task's page. Tasks are concurrent; their steps are not.

Tabs of one profile share cookies and storage. Two tasks on the same shop share its cart and its sign-in: that is the owner's decision, not isolation.
"""
from __future__ import annotations
import threading

ACTIVE_LIMIT = 5        # browser tasks of one customer running at once; more wait their turn
LOADED_LIMIT = 2        # of those, how many keep a tab loaded


class AccountTabs:
    """The tabs of one account's browser. Everything here is called with `lock` held (a runner takes it for each command)."""

    def __init__(self, loaded_limit=LOADED_LIMIT):
        self.lock, self.runners, self.loaded_limit = threading.RLock(), [], loaded_limit
        self.started, self.front = False, None      # is the browser up; the tab that was last brought to the front

    @property
    def shared(self):
        return len(self.runners) > 1

    def join(self, runner):
        with self.lock:
            if runner not in self.runners:
                self.runners.append(runner)

    def leave(self, runner) -> bool:
        """-> True when this was the account's last task: the browser itself may stop."""
        with self.lock:
            if runner in self.runners:
                self.runners.remove(runner)
            return not self.runners

    def owned(self):
        return {page for r in self.runners for page in r.pages}

    def make_room(self, runner):
        """Before `runner` loads a tab: close the tab of whoever has gone longest without a step, until there is room."""
        while True:
            loaded = [r for r in self.runners if r is not runner and r.pages]
            if len(loaded) < self.loaded_limit:
                return
            min(loaded, key=lambda r: r.last_used).unload()


class TabDesk:
    def __init__(self, loaded_limit=LOADED_LIMIT):
        self._accounts, self._guard, self.loaded_limit = {}, threading.Lock(), loaded_limit

    def account(self, account) -> AccountTabs:
        with self._guard:
            return self._accounts.setdefault(account, AccountTabs(self.loaded_limit))
