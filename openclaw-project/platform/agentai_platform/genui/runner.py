"""Runs a launched plan one phase at a time through the normal request queue.

Each enabled phase is its own request (same chat, same runtime session), so progress, approval gates and edits to
phases that have not started are all real. Nothing here talks to the runtime directly: it only creates requests, exactly
like a customer message, and reads their outcome. All entry points are idempotent and safe to run concurrently.
"""
from __future__ import annotations
import json
import uuid
import time

from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal

from . import replan, schema

LOCKED = ('running', 'completed', 'failed')           # phases whose content can no longer change
OPEN = ('pending', 'awaiting_approval')


class PlanRunner:
    def __init__(self, chat, *, clock=time.time):
        self.chat, self.clock = chat, clock
        self.store, self.blocks = chat.store, chat.blocks
        self.replans = replan.Replanner(self.store, self.blocks, clock=clock)

    # ------------------------------------------------------------------ helpers
    def _rows(self, con, account, block):
        return {r['phase_id']: r for r in con.execute('SELECT * FROM plan_phase_runs WHERE account_id=? AND block_id=? ORDER BY position', (account, block)).fetchall()}

    def _block(self, con, account, block_id):
        row = con.execute('SELECT * FROM ui_blocks WHERE account_id=? AND id=?', (account, block_id)).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    def _plan(self, row):
        return json.loads(row['state_json'])['plan']

    def _principal(self, row):
        return Principal(row['account_id'], row['actor_id'], 'customer')

    # ------------------------------------------------------------------ start
    def start(self, con, account, block_id, plan):
        """Create a pending row for every enabled phase (called inside the launch transaction)."""
        for pos, phase in enumerate(schema.execution_order(plan)):
            con.execute("INSERT OR IGNORE INTO plan_phase_runs(account_id,block_id,phase_id,position,state) VALUES (?,?,?,?,'pending')",
                        (account, block_id, phase['id'], pos))

    # ------------------------------------------------------------------ progress
    def sync(self):
        """Fold finished requests into their phase rows."""
        with self.store.connect() as con:
            running = con.execute("""SELECT p.account_id,p.block_id,p.phase_id,r.state,r.result FROM plan_phase_runs p
                JOIN customer_requests r ON r.account_id=p.account_id AND r.id=p.request_id
                WHERE p.state='running' AND r.state IN ('completed','failed','cancelled')""").fetchall()
        for row in running:
            state = {'completed': 'completed', 'failed': 'failed', 'cancelled': 'cancelled'}[row['state']]
            with self.blocks.coordinator.transaction() as con:
                con.execute("UPDATE plan_phase_runs SET state=?,summary=?,finished_epoch=? WHERE account_id=? AND block_id=? AND phase_id=? AND state='running'",
                            (state, (row['result'] or '')[:4000], int(self.clock()), row['account_id'], row['block_id'], row['phase_id']))

    def tick(self):
        """Worker entry: record finished phases, then start whatever is ready. Returns how many phases were started."""
        self.sync()
        with self.store.connect() as con:
            blocks = con.execute("""SELECT DISTINCT account_id,block_id FROM plan_phase_runs WHERE state IN ('pending','awaiting_approval') LIMIT 50""").fetchall()
        started = 0
        for b in blocks:
            started += 1 if self.advance(b['account_id'], b['block_id']) else 0
        self._announce_completions()
        self._automatic_replans()
        return started

    def advance(self, account_id, block_id):
        """Start the next ready phase if none is running. Returns the new request id, or None."""
        with self.store.connect() as con:
            row = self._block(con, account_id, block_id)
            if row['status'] != 'launched':
                return None
            rows, plan = self._rows(con, account_id, block_id), self._plan(row)
        if any(r['state'] == 'running' for r in rows.values()):
            return None
        order = schema.execution_order(plan)
        done = {i for i, r in rows.items() if r['state'] in ('completed', 'skipped')}
        for n, phase in enumerate(order, 1):
            r = rows.get(phase['id'])
            if r is None or r['state'] in ('completed', 'skipped', 'cancelled'):
                continue
            if r['state'] == 'failed':
                return None                                   # the user decides: retry or skip
            if not all(d in done or not self._enabled(plan, d) for d in phase['dependsOn']):
                return None                                   # waiting on something that is not finished
            if r['state'] == 'awaiting_approval':
                return None
            if phase['requiresApproval'] and r['approved_epoch'] is None:
                with self.blocks.coordinator.transaction() as con:
                    con.execute("UPDATE plan_phase_runs SET state='awaiting_approval' WHERE account_id=? AND block_id=? AND phase_id=? AND state='pending'",
                                (account_id, block_id, phase['id']))
                return None
            return self._spawn(row, plan, phase, n, len(order), r)
        return None

    @staticmethod
    def _enabled(plan, phase_id):
        return any(p['id'] == phase_id and p['enabled'] for p in plan['phases'])

    def _spawn(self, row, plan, phase, n, total, r):
        account, block = row['account_id'], row['id']
        with self.blocks.coordinator.transaction() as con:      # atomic claim: only one caller wins the pending -> running move
            won = con.execute("UPDATE plan_phase_runs SET state='running',attempts=attempts+1,started_epoch=?,summary=NULL,finished_epoch=NULL "
                              "WHERE account_id=? AND block_id=? AND phase_id=? AND state='pending'", (int(self.clock()), account, block, phase['id'])).rowcount
            attempts = con.execute('SELECT attempts FROM plan_phase_runs WHERE account_id=? AND block_id=? AND phase_id=?', (account, block, phase['id'])).fetchone()[0]
        if not won:
            return None
        try:
            result = self.chat._spawn(self._principal(row), row['conversation_id'], message=f'Phase {n}: {phase["title"]}'[:200],
                                      key=f'phase-{block}-{phase["id"]}-{attempts}', intent='phase', context={'block': block, 'phase': phase['id']},
                                      shown=f'Running phase {n} of {total}: {phase["title"]}')
        except Exception as exc:                              # budget, queue full, storage: show it, let the user retry
            with self.blocks.coordinator.transaction() as con:
                con.execute("UPDATE plan_phase_runs SET state='failed',summary=?,finished_epoch=? WHERE account_id=? AND block_id=? AND phase_id=?",
                            (f'Could not start this phase ({type(exc).__name__}).', int(self.clock()), account, block, phase['id']))
            return None
        with self.blocks.coordinator.transaction() as con:
            con.execute('UPDATE plan_phase_runs SET request_id=? WHERE account_id=? AND block_id=? AND phase_id=?', (result['id'], account, block, phase['id']))
            con.execute('UPDATE ui_blocks SET launched_request_id=coalesce(launched_request_id,?) WHERE account_id=? AND id=?', (result['id'], account, block))
        return result['id']

    def _announce_completions(self):
        with self.store.connect() as con:
            blocks = con.execute("""SELECT b.account_id,b.id,b.conversation_id,b.spec_json FROM ui_blocks b WHERE b.kind='task_plan' AND b.status='launched'
                AND EXISTS (SELECT 1 FROM plan_phase_runs p WHERE p.account_id=b.account_id AND p.block_id=b.id)
                AND NOT EXISTS (SELECT 1 FROM plan_phase_runs p WHERE p.account_id=b.account_id AND p.block_id=b.id AND p.state NOT IN ('completed','skipped'))
                LIMIT 20""").fetchall()
        for b in blocks:
            text = f'Plan finished: {json.loads(b["spec_json"])["title"]}. Open the plan above to read each phase’s result.'
            with self.blocks.coordinator.transaction() as con:
                if not con.execute('SELECT 1 FROM chat_messages WHERE account_id=? AND conversation_id=? AND provenance=\'agent\' AND content=?',
                                   (b['account_id'], b['conversation_id'], text)).fetchone():
                    con.execute("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,NULL,'agent',?)",
                                (b['account_id'], b['conversation_id'], text))

    # ------------------------------------------------------------------ user actions (each re-authorizes)
    def _own(self, principal, block_id):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = self._block(con, principal.account_id, block_id)
        if row['kind'] != 'task_plan' or row['status'] != 'launched':
            raise Conflict('this plan is not running')
        return row

    def _audit(self, principal, object_id, action, outcome):
        """Every approve / skip / retry / stop attempt, allowed or refused, lands in audit_events (the platform's existing trail). Never fails the action."""
        try:
            with self.blocks.coordinator.transaction() as con:
                con.execute('INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id) VALUES (?,?,?,?,?,?,?)',
                            (principal.account_id, uuid.uuid4().hex, principal.actor_id, object_id[:200], action, outcome, uuid.uuid4().hex))
        except Exception:
            pass

    def act(self, principal: Principal, block_id: str, phase_id: str, action: str):
        label = f'block.phase.{action}'[:60]
        try:
            out = self._act(principal, block_id, phase_id, action)
        except (Conflict, NotFound, ValueError):
            self._audit(principal, f'{block_id}/{phase_id}', label, 'denied')
            raise
        except Exception:
            self._audit(principal, f'{block_id}/{phase_id}', label, 'failed')
            raise
        self._audit(principal, f'{block_id}/{phase_id}', label, 'completed')
        return out

    def _act(self, principal: Principal, block_id: str, phase_id: str, action: str):
        row = self._own(principal, block_id)
        if action not in ('approve', 'skip', 'retry'):
            raise ValueError('unknown action')
        with self.blocks.coordinator.transaction() as con:
            r = self._rows(con, principal.account_id, block_id).get(phase_id)
            if r is None:
                raise NotFound('unavailable')
            if action == 'approve':
                if r['state'] not in ('awaiting_approval', 'pending'):
                    raise Conflict('this phase is not waiting for approval')
                con.execute("UPDATE plan_phase_runs SET approved_epoch=?,state='pending' WHERE account_id=? AND block_id=? AND phase_id=?",
                            (int(self.clock()), principal.account_id, block_id, phase_id))
            elif action == 'retry':
                if r['state'] != 'failed':
                    raise Conflict('only a failed phase can be retried')
                con.execute("UPDATE plan_phase_runs SET state='pending',summary=NULL WHERE account_id=? AND block_id=? AND phase_id=?", (principal.account_id, block_id, phase_id))
            else:
                if r['state'] not in ('pending', 'awaiting_approval', 'failed'):
                    raise Conflict('this phase cannot be skipped now')
                plan = self._plan(row)
                for p in plan['phases']:
                    if p['id'] == phase_id:
                        p['enabled'] = False
                self._save_plan(con, principal.account_id, row, plan)
                con.execute("UPDATE plan_phase_runs SET state='skipped' WHERE account_id=? AND block_id=? AND phase_id=?", (principal.account_id, block_id, phase_id))
        self.advance(principal.account_id, block_id)
        return self.blocks.get(principal, block_id)

    def _save_plan(self, con, account, row, plan, source='user'):
        state = json.loads(row['state_json']); state['plan'] = plan; state['revision'] = state['revision'] + 1
        con.execute('UPDATE ui_blocks SET state_json=?,version=version+1,updated_epoch=? WHERE account_id=? AND id=?', (json.dumps(state), int(self.clock()), account, row['id']))
        con.execute('INSERT OR REPLACE INTO plan_revisions VALUES (?,?,?,?,?,?)', (account, row['id'], state['revision'], source, json.dumps(plan), int(self.clock())))

    def stop(self, principal: Principal, block_id: str):
        try:
            out = self._stop(principal, block_id)
        except (Conflict, NotFound, ValueError):
            self._audit(principal, block_id, 'block.plan.stop', 'denied')
            raise
        self._audit(principal, block_id, 'block.plan.stop', 'completed')
        return out

    def _stop(self, principal: Principal, block_id: str):
        self._own(principal, block_id)
        with self.blocks.coordinator.transaction() as con:
            running = [r['request_id'] for r in self._rows(con, principal.account_id, block_id).values() if r['state'] == 'running' and r['request_id']]
            con.execute("UPDATE plan_phase_runs SET state='cancelled',finished_epoch=? WHERE account_id=? AND block_id=? AND state IN ('pending','awaiting_approval')",
                        (int(self.clock()), principal.account_id, block_id))
        for request_id in running:
            try:
                self.chat.queue.cancel(principal, request_id)
            except Exception:
                pass
        return self.blocks.get(principal, block_id)

    def edit(self, principal: Principal, block_id: str, version: int, new_plan) -> dict:
        """Change phases that have not started. Started or finished phases must stay exactly as they were."""
        return self._apply_edit(principal, block_id, version, new_plan)

    def _apply_edit(self, principal: Principal, block_id: str, version: int, new_plan, *, source='user', switch_off_failed=False, base_revision=None) -> dict:
        row = self._own(principal, block_id)
        if type(version) is not int:
            raise ValueError('invalid version')
        plan = schema.validate_plan(new_plan, launch=True)
        with self.blocks.coordinator.transaction() as con:
            fresh = self._block(con, principal.account_id, block_id)
            if fresh['version'] != version:
                raise Conflict('version conflict')
            rows, old = self._rows(con, principal.account_id, block_id), self._plan(fresh)
            old_by, new_by = {p['id']: p for p in old['phases']}, {p['id']: p for p in plan['phases']}
            if base_revision is not None and json.loads(fresh['state_json'])['revision'] != base_revision:
                raise Conflict('the plan changed since this revision was suggested')
            for pid, r in rows.items():
                if r['state'] in LOCKED and old_by.get(pid) != new_by.get(pid):
                    if switch_off_failed and r['state'] == 'failed' and pid in old_by and new_by.get(pid) == {**old_by[pid], 'enabled': False}:
                        continue                          # a revision may switch a failed phase off (it is then replaced by a new one)
                    raise Conflict('a phase that has started or finished cannot be changed')
            for pid, p in new_by.items():
                if pid in old_by and p != old_by[pid] and rows.get(pid) and rows[pid]['state'] in OPEN:
                    con.execute("UPDATE plan_phase_runs SET approved_epoch=NULL,state='pending' WHERE account_id=? AND block_id=? AND phase_id=?",
                                (principal.account_id, block_id, pid))                 # any change to a gated phase needs a fresh approval
            for pid in list(rows):
                if pid not in new_by and rows[pid]['state'] in OPEN + ('skipped', 'cancelled'):
                    con.execute('DELETE FROM plan_phase_runs WHERE account_id=? AND block_id=? AND phase_id=?', (principal.account_id, block_id, pid))
            for pos, p in enumerate(schema.execution_order(plan)):
                if p['id'] in rows:
                    con.execute('UPDATE plan_phase_runs SET position=? WHERE account_id=? AND block_id=? AND phase_id=?', (pos, principal.account_id, block_id, p['id']))
                else:
                    con.execute("INSERT INTO plan_phase_runs(account_id,block_id,phase_id,position,state) VALUES (?,?,?,?,'pending')", (principal.account_id, block_id, p['id'], pos))
            for pid, p in new_by.items():
                r = rows.get(pid)
                if r and not p['enabled'] and (r['state'] in OPEN or (switch_off_failed and r['state'] == 'failed')):
                    con.execute("UPDATE plan_phase_runs SET state='skipped' WHERE account_id=? AND block_id=? AND phase_id=?", (principal.account_id, block_id, pid))
                elif r and p['enabled'] and r['state'] == 'skipped':
                    con.execute("UPDATE plan_phase_runs SET state='pending' WHERE account_id=? AND block_id=? AND phase_id=?", (principal.account_id, block_id, pid))
            self._save_plan(con, principal.account_id, fresh, plan, source)
        self.advance(principal.account_id, block_id)
        return self.blocks.get(principal, block_id)

    # ------------------------------------------------------------------ adaptation (roadmap #11)
    def request_replan(self, principal: Principal, block_id: str, trigger: str, instruction: str = '', *, auto: bool = False):
        """Ask the assistant for a revision of this running plan. -> the proposal (state 'requested'; it becomes 'proposed' when the assistant's reply has been checked)."""
        if trigger not in replan.TRIGGERS:
            raise ValueError('invalid trigger')
        if not isinstance(instruction, str) or len(instruction) > 2000 or '\x00' in instruction:
            raise ValueError('invalid instruction')
        if trigger == 'instruction' and not instruction.strip():
            raise ValueError('say what should change')
        row = self._own(principal, block_id)
        proposal = uuid.uuid4().hex
        with self.blocks.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if con.execute("SELECT 1 FROM plan_proposals WHERE account_id=? AND block_id=? AND state='requested'", (principal.account_id, block_id)).fetchone():
                raise Conflict('a revision is already being prepared')
            con.execute("UPDATE plan_proposals SET state='superseded',decided_epoch=? WHERE account_id=? AND block_id=? AND state='proposed'", (int(self.clock()), principal.account_id, block_id))
            con.execute("INSERT INTO plan_proposals(account_id,block_id,id,trigger,instruction,base_revision,state,auto,created_epoch) VALUES (?,?,?,?,?,?,'requested',?,?)",
                        (principal.account_id, block_id, proposal, trigger, instruction.strip(), json.loads(row['state_json'])['revision'], 1 if auto else 0, int(self.clock())))
        try:
            result = self.chat._spawn(principal, row['conversation_id'], message=('Revise the plan: ' + json.loads(row['state_json'])['plan']['title'])[:200], key=f'replan-{proposal}',
                                      intent='replan', context={'block': block_id, 'proposal': proposal}, shown='Asking the assistant to revise the plan…')
        except Exception as exc:                          # budget, queue full: the proposal never started; say so and let the customer try again
            with self.blocks.coordinator.transaction() as con:
                con.execute("UPDATE plan_proposals SET state='failed',summary=?,decided_epoch=? WHERE account_id=? AND block_id=? AND id=?",
                            (f'The assistant could not be asked right now ({type(exc).__name__}). Try again in a moment.', int(self.clock()), principal.account_id, block_id, proposal))
            raise
        with self.blocks.coordinator.transaction() as con:
            con.execute('UPDATE plan_proposals SET request_id=? WHERE account_id=? AND block_id=? AND id=?', (result['id'], principal.account_id, block_id, proposal))
        return {'proposal': proposal, 'request_id': result['id']}

    def approve_proposal(self, principal: Principal, block_id: str, proposal_id: str):
        """The customer approves a revision: it is applied exactly as stored (and re-checked against what has happened since)."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            found = con.execute('SELECT * FROM plan_proposals WHERE account_id=? AND block_id=? AND id=?', (principal.account_id, block_id, proposal_id)).fetchone()
        if not found:
            raise NotFound('unavailable')
        if found['state'] != 'proposed':
            raise Conflict('this revision is not waiting for a decision')
        return self._apply_proposal(principal, block_id, found)

    def _apply_proposal(self, principal, block_id, found):
        plan = json.loads(found['plan_json'])
        with self.store.connect() as con:
            block = self._block(con, principal.account_id, block_id)
            runs, old = self._rows(con, principal.account_id, block_id), self._plan(block)
        try:
            replan.check_against_runs(runs, old, plan)
            view = self._apply_edit(principal, block_id, block['version'], plan, source='approved', switch_off_failed=True, base_revision=found['base_revision'])
        except (replan.ReplanRefused, Conflict) as exc:
            with self.blocks.coordinator.transaction() as con:
                con.execute("UPDATE plan_proposals SET state='superseded',summary=?,decided_epoch=? WHERE account_id=? AND block_id=? AND id=?",
                            (('This revision no longer fits the plan: ' + str(exc))[:300], int(self.clock()), principal.account_id, block_id, found['id']))
            raise Conflict('this revision no longer fits the plan') from None
        with self.blocks.coordinator.transaction() as con:
            con.execute("UPDATE plan_proposals SET state='applied',decided_epoch=? WHERE account_id=? AND block_id=? AND id=?", (int(self.clock()), principal.account_id, block_id, found['id']))
        return view

    def decline_proposal(self, principal: Principal, block_id: str, proposal_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM plan_proposals WHERE account_id=? AND block_id=? AND id=?', (principal.account_id, block_id, proposal_id)).fetchone():
                raise NotFound('unavailable')
        self.replans.decline(principal.account_id, block_id, proposal_id)
        return self.blocks.get(principal, block_id)

    def set_auto_replan(self, principal: Principal, block_id: str, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError('invalid setting')
        self._own(principal, block_id)
        with self.blocks.coordinator.transaction() as con:
            con.execute("""INSERT INTO plan_settings(account_id,block_id,auto_replan,updated_epoch) VALUES (?,?,?,?)
                ON CONFLICT(account_id,block_id) DO UPDATE SET auto_replan=excluded.auto_replan,updated_epoch=excluded.updated_epoch""",
                        (principal.account_id, block_id, 1 if enabled else 0, int(self.clock())))
            self.blocks.coordinator._audit(con, principal.account_id, principal.actor_id, block_id, 'block.plan.auto_replan.' + ('on' if enabled else 'off'), 'completed')
        return self.blocks.get(principal, block_id)

    def settings(self, con, account, block) -> dict:
        row = con.execute('SELECT auto_replan,auto_used FROM plan_settings WHERE account_id=? AND block_id=?', (account, block)).fetchone()
        return {'auto_replan': bool(row['auto_replan']) if row else False, 'auto_used': row['auto_used'] if row else 0, 'auto_limit': replan.MAX_AUTO_REPLANS}

    def _automatic_replans(self):
        """For plans whose customer chose automatic replanning: ask for a revision when a phase has failed (bounded), and apply a revision that came back checked."""
        with self.store.connect() as con:
            failed = con.execute("""SELECT DISTINCT p.account_id,p.block_id FROM plan_phase_runs p JOIN plan_settings s ON s.account_id=p.account_id AND s.block_id=p.block_id
                JOIN ui_blocks b ON b.account_id=p.account_id AND b.id=p.block_id
                WHERE p.state='failed' AND s.auto_replan=1 AND s.auto_used<? AND b.status='launched'
                AND NOT EXISTS (SELECT 1 FROM plan_proposals q WHERE q.account_id=p.account_id AND q.block_id=p.block_id AND q.state IN ('requested','proposed'))
                AND NOT EXISTS (SELECT 1 FROM plan_phase_runs r WHERE r.account_id=p.account_id AND r.block_id=p.block_id AND r.state='running') LIMIT 20""", (replan.MAX_AUTO_REPLANS,)).fetchall()
            ready = con.execute("""SELECT q.* FROM plan_proposals q JOIN plan_settings s ON s.account_id=q.account_id AND s.block_id=q.block_id
                WHERE q.state='proposed' AND q.auto=1 AND s.auto_replan=1 LIMIT 20""").fetchall()
        for f in failed:
            try:
                with self.store.connect() as con:
                    principal = self._principal(self._block(con, f['account_id'], f['block_id']))
                with self.blocks.coordinator.transaction() as con:
                    con.execute("""UPDATE plan_settings SET auto_used=auto_used+1,updated_epoch=? WHERE account_id=? AND block_id=?""", (int(self.clock()), f['account_id'], f['block_id']))
                self.request_replan(principal, f['block_id'], 'failure', 'A phase of this plan failed. Suggest how to carry on.', auto=True)
            except Exception:
                pass                                          # the customer can still ask for a revision themselves
        for q in ready:
            try:
                with self.store.connect() as con:
                    principal = self._principal(self._block(con, q['account_id'], q['block_id']))
                self._apply_proposal(principal, q['block_id'], q)
            except Exception:
                pass                                          # it becomes superseded, with the reason, or stays for the customer
