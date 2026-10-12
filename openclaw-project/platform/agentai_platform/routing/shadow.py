"""Shadow routing: classify each claimed request beside the real path and record what would have been chosen.

Failure-proof by construction: every error is swallowed (the request runs exactly as before), the classifier has a
short deadline and no retry, and nothing it returns is used to run anything.
"""
from __future__ import annotations
import threading
import time

from . import config as routing_config
from .classifier import ClassifierUnavailable, classify
from .decision import Rejected
from .policy import evaluate
from .store import RouteLog


class ShadowRouter:
    def __init__(self, store, *, config_path, key_path, switch_on, transport=None, clock=time.time):
        self.store, self.config_path, self.key_path, self.switch_on, self.clock = store, config_path, key_path, switch_on, clock
        self.transport = transport
        self.log = RouteLog(store, clock)
        self._started = {}
        self._threads = {}

    def _config(self):
        cfg = routing_config.load(self.config_path)
        return cfg if cfg['enabled'] else None

    def config_deadline(self):
        try:
            return routing_config.load(self.config_path)['deadline_s']
        except Exception:
            return 5

    def _key(self):
        try:
            with open(self.key_path) as handle:
                return handle.read().strip() or None
        except OSError:
            return None

    def before(self, claim):
        """Starts the classification in the background: the real request never waits for the classifier."""
        try:
            if not self.switch_on():
                return
            self._started[claim.request_id] = self.clock()
            thread = threading.Thread(target=self._classify, args=(claim,), daemon=True)
            self._threads[claim.request_id] = thread
            thread.start()
        except Exception:
            return

    def _classify(self, claim):
        try:
            if not self.switch_on():
                return
            cfg = self._config()
            if cfg is None:
                return
            cfg = {**cfg, 'mode': 'shadow'}      # canary/live are not built: nothing may influence execution yet
            kwargs = {'transport': self.transport} if self.transport else {}
            try:
                decision, latency = classify(claim.message, cfg, self._key(), **kwargs)
            except ClassifierUnavailable:
                self.log.record(claim.account_id, claim.request_id, cfg, status='unavailable')
                return
            except Rejected:
                self.log.record(claim.account_id, claim.request_id, cfg, status='rejected')
                return
            outcome = evaluate(decision, claim.message, cfg)
            self.log.record(claim.account_id, claim.request_id, cfg, status='classified', decision=decision,
                            outcome=outcome, latency_ms=latency)
        except Exception:
            return

    def after(self, claim, receipt):
        try:
            started = self._started.pop(claim.request_id, None)
            thread = self._threads.pop(claim.request_id, None)
            if thread is not None:
                thread.join(timeout=self.config_deadline() + 2)
            if started is None:
                return
            with self.store.connect() as con:
                spent = con.execute('SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE account_id=? AND task_id=?',
                                    (claim.account_id, claim.request_id)).fetchone()[0]
            self.log.finish(claim.account_id, claim.request_id, outcome=receipt.state, task_cost_microusd=int(spent),
                            task_seconds=int(self.clock() - started))
        except Exception:
            return
