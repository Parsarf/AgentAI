"""Offline Phase 5 ledger/admission core; no provider or native dispatch.

Lumina sets no spending limit of its own. The only limits admission checks are the ones the customer chose in Settings (spend_limits.py): per task, per day and
per billing period. An account with none is admitted whatever it has spent. The entitlement still decides WHETHER the account may run work (trial, active, grace);
the amounts in its `limits_json` are no longer read as allowances, only its period start and its queue length.

Input prices, upper bounds and receipts must come from trusted route adapters.
No HTTP endpoint exposes these trust assertions. Unknown pricing or service
allocation denies admission. Restoring a DB cannot by itself authorize spending:
provider-key backstops and receipt reconciliation are still required for activation.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from agentai_platform import safety, spend_limits
from agentai_platform.lifecycle.coordinator import Coordinator, identifier
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound

OWN_KEY_AMOUNT = 1                    # micro-dollars: the nominal reservation of a task that runs on the customer's own model key (nothing about their model is limited or charged here)

class BudgetDenied(Exception): pass

class BudgetLedger:
    def __init__(self, store, *, service_limit_microusd=None, clock=time.time):
        if service_limit_microusd is not None and (type(service_limit_microusd) is not int or service_limit_microusd<=0):
            raise ValueError('invalid service allocation')
        self.store=store;self.clock=clock;self.service_limit=service_limit_microusd
        self.transactions=Coordinator(store,clock=clock)

    def _entry(self, con, account, task, kind, amount, reference, provider='admission', price_version='task-allocation-v1'):
        con.execute('''INSERT INTO usage_entries(account_id,task_id,id,provider,provider_request_id,kind,amount_microusd,currency,price_version)
            VALUES (?,?,?,?,?,?,?,'USD',?)''',(account,task,uuid.uuid4().hex,provider,reference,kind,amount,price_version))

    def _limits(self, con, account, *, for_admission=True):
        rows=con.execute('''SELECT * FROM entitlements WHERE account_id=? AND status IN ('trial','active','grace')
            AND julianday(valid_until)>julianday(?,'unixepoch')''',(account,self.clock())).fetchall()
        if not for_admission:
            rows=con.execute('SELECT * FROM entitlements WHERE account_id=? ORDER BY julianday(valid_until) DESC,id DESC LIMIT 1',(account,)).fetchall()
        if len(rows)!=1: raise BudgetDenied('entitlement unavailable or ambiguous')
        row=rows[0]
        limits=json.loads(row['limits_json'])
        fields={'period_start_epoch','period_microusd','daily_microusd','task_microusd','max_queued_tasks'}
        if set(limits)!=fields or any(type(x) is not int or x<0 for x in limits.values()):
            raise BudgetDenied('entitlement limits unverified')
        if limits['period_start_epoch']>self.clock() or any(limits[k]==0 for k in fields-{'period_start_epoch'}):
            raise BudgetDenied('invalid entitlement limits')
        return row,limits

    def _spend(self, con, account=None, since=None):
        sql='SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE 1=1';args=[]
        if account is not None:sql+=' AND account_id=?';args.append(account)
        if since is not None:sql+=' AND observed_epoch>=?';args.append(since)
        return con.execute(sql,args).fetchone()[0]

    def _holds(self, con, account=None):
        # Reported spend consumes a reservation before the remainder is released.
        # Counting the whole reservation plus receipts would count usage twice.
        sql='''SELECT coalesce(sum(max(0,r.amount_microusd-coalesce((SELECT sum(p.amount_microusd)
            FROM provider_receipts p WHERE p.account_id=r.account_id AND p.task_id=r.task_id),0))),0)
            FROM task_reservations r WHERE r.state IN ('active','uncertain') AND r.amount_microusd<?''';args=[spend_limits.NO_LIMIT]      # a no-limit reservation is a marker, not money held
        if account is not None:sql+=' AND r.account_id=?';args.append(account)
        return con.execute(sql,args).fetchone()[0]

    def admit(self, principal, *, task, project, conversation, key, amount_microusd,
              upper_bound_verified=False, currency='USD', unmetered=False):
        """The only spending limits checked are the customer's own (Settings > Usage): a day or a period that is already used up refuses the task. No limit set, nothing checked.
        `unmetered`: the account runs on the customer's OWN model key, so even their Lumina limits do not apply to the model's cost. The task still gets its reservation row,
        because the rest of the platform (the browser tool among it) looks for one. The limit on how many tasks may wait in the queue stays: it protects Lumina's servers, not a budget."""
        for value in [task,project,conversation,key]:identifier(value)
        if currency!='USD' or type(amount_microusd) is not int or amount_microusd<=0:
            raise ValueError('invalid allocation')
        if upper_bound_verified is not True or self.service_limit is None:raise BudgetDenied('allocation not verified')
        body=json.dumps({'task':task,'project':project,'conversation':conversation,'amount':amount_microusd,'currency':currency},sort_keys=True)
        digest=hashlib.sha256(body.encode()).hexdigest();account=principal.account_id
        with self.transactions.transaction() as con:
            self.store._authorize(con,principal)
            existing=con.execute('SELECT * FROM task_reservations WHERE account_id=? AND idempotency_key=?',(account,key)).fetchone()
            if existing:
                if existing['request_hash']!=digest:raise Conflict('allocation payload changed')
                return dict(existing)
            entitlement,limits=self._limits(con,account)
            own=spend_limits.get(con,account)
            if not con.execute('SELECT 1 FROM conversations WHERE account_id=? AND project_id=? AND id=?',(account,project,conversation)).fetchone():
                raise NotFound()
            queued=con.execute("SELECT count(*) FROM tasks WHERE account_id=? AND state='queued'",(account,)).fetchone()[0]
            if queued>=limits['max_queued_tasks'] and safety.is_on(con,account,'queue_limit'):raise BudgetDenied('queue full')       # the plan's queue limit is the same `queue_limit` switch as the queue's own
            holds=self._holds(con,account)
            for bound,since in ([] if unmetered else [('period',limits['period_start_epoch']),('daily',self.clock()-86400)]):
                # The customer's own limit: reached means the next task waits for them to raise it (or for the day or period to turn over). A new task is never refused for what it
                # MIGHT cost, only for what has already been spent or is held by a task with a limit of its own.
                if own[bound] is not None and self._spend(con,account,since)+holds>=own[bound]:raise BudgetDenied('account allowance exhausted')
            con.execute('''INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd)
                VALUES (?,?,?,?,'queued',?)''',(account,project,conversation,task,amount_microusd))
            con.execute("INSERT INTO task_reservations VALUES (?,?,?,?,?,?,'active',?)",
                        (account,task,key,digest,entitlement['id'],amount_microusd,int(self.clock())))
            self._entry(con,account,task,'reserved',amount_microusd if spend_limits.limited(amount_microusd) else 0,key)      # the no-limit marker is never written as money
            self.transactions._audit(con,account,principal.actor_id,task,'budget_admit','completed')
            return dict(con.execute('SELECT * FROM task_reservations WHERE account_id=? AND task_id=?',(account,task)).fetchone())

    def receipt(self, *, account, task, provider, request, amount_microusd, observed_epoch,
                price_version, payload_hash):
        # Host/service adapter path only, not customer authority. Store real
        # overrun receipts rather than rejecting evidence of already-incurred cost.
        for value in [account,task,provider,request,price_version]:identifier(value)
        if type(amount_microusd) is not int or amount_microusd<0:raise ValueError('invalid usage')
        if type(observed_epoch) is not int or not 0<=observed_epoch<=self.clock()+30:raise ValueError('invalid receipt time')
        if not isinstance(payload_hash,str) or len(payload_hash)!=64 or any(c not in '0123456789abcdef' for c in payload_hash):raise ValueError('invalid receipt hash')
        with self.transactions.transaction() as con:
            reservation=con.execute('SELECT * FROM task_reservations WHERE account_id=? AND task_id=?',(account,task)).fetchone()
            if not reservation:raise NotFound()
            if observed_epoch<reservation['created_epoch']:raise ValueError('receipt predates admission')
            existing=con.execute('SELECT * FROM provider_receipts WHERE account_id=? AND provider=? AND provider_request_id=?',(account,provider,request)).fetchone()
            if existing:
                if (existing['task_id'],existing['amount_microusd'],existing['observed_epoch'],existing['payload_hash'],existing['price_version'])!=(task,amount_microusd,observed_epoch,payload_hash,price_version):
                    raise Conflict('provider receipt changed')
                return False
            con.execute('INSERT INTO provider_receipts VALUES (?,?,?,?,?,?,?,?)',(account,task,provider,request,payload_hash,price_version,amount_microusd,observed_epoch))
            if reservation['state'] in {'settled','cancelled'}:
                con.execute("UPDATE task_reservations SET state='uncertain' WHERE account_id=? AND task_id=?",(account,task))
            self._entry(con,account,task,'reported',amount_microusd,request,provider,price_version)
            self.transactions._audit(con,account,'receipt-adapter',task,'budget_receipt','completed')
            return True

    def settle(self, *, account, task, effects_quiesced=False, all_routes_reconciled=False):
        with self.transactions.transaction() as con:
            row=con.execute('SELECT * FROM task_reservations WHERE account_id=? AND task_id=?',(account,task)).fetchone()
            if not row:raise NotFound()
            if row['state'] in {'settled','cancelled'}:return False
            if effects_quiesced is not True or all_routes_reconciled is not True:
                con.execute("UPDATE task_reservations SET state='uncertain' WHERE account_id=? AND task_id=?",(account,task))
                self.transactions._audit(con,account,'receipt-adapter',task,'budget_settle','uncertain')
                return False
            spent=con.execute('SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE account_id=? AND task_id=?',(account,task)).fetchone()[0]
            con.execute("UPDATE task_reservations SET state='settled' WHERE account_id=? AND task_id=?",(account,task))
            prior_released=con.execute("SELECT coalesce(sum(amount_microusd),0) FROM usage_entries WHERE account_id=? AND task_id=? AND kind='released'",(account,task)).fetchone()[0]
            reference='settle-'+uuid.uuid4().hex
            self._entry(con,account,task,'reconciled',spent,reference)
            self._entry(con,account,task,'released',(max(0,row['amount_microusd']-spent)-prior_released) if spend_limits.limited(row['amount_microusd']) else 0,reference)
            self.transactions._audit(con,account,'receipt-adapter',task,'budget_settle','completed')
            return True

    def summary(self, principal):
        with self.transactions.transaction() as con:
            self.store._authorize(con,principal)
            entitlement,limits=self._limits(con,principal.account_id,for_admission=False)
            eligible=entitlement['status'] in {'trial','active','grace'} and con.execute("SELECT julianday(?)>julianday(?,'unixepoch')",(entitlement['valid_until'],self.clock())).fetchone()[0]
            spent=self._spend(con,principal.account_id,limits['period_start_epoch']);held=self._holds(con,principal.account_id)
            own=spend_limits.get(con,principal.account_id);cap=own['period']      # the customer's own limit for the period, or None: Lumina has none
            return {'reported_microusd':spent,'held_microusd':held,'period_remaining_microusd':(max(0,cap-spent-held) if eligible else 0) if cap is not None else None,
                    'period_limit_microusd':cap,'period_start_epoch':limits['period_start_epoch'],
                    'plan_period_microusd':limits['period_microusd'],      # the usage the plan was sold with; a fact about the plan, not a limit anything enforces
                    'day_reported_microusd':self._spend(con,principal.account_id,self.clock()-86400),
                    'limits':{'run_microusd':own['task'],'day_microusd':own['daily'],'period_microusd':own['period']},      # the customer's own (spend_limits.py); None = no limit
                    'admission_eligible':bool(eligible),
                    'usage_pending':bool(con.execute("SELECT 1 FROM task_reservations WHERE account_id=? AND state='uncertain'",(principal.account_id,)).fetchone()),
                    'currency':'USD','live_provider_accounting_verified':False}
