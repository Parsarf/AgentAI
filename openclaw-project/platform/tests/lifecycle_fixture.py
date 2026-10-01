"""Disposable file-backed driver. Not a native sandbox or production adapter."""
from dataclasses import asdict
import json
from pathlib import Path
import re
from agentai_platform.lifecycle.types import Receipt, Conflict

class FixtureDriver:
    def __init__(self, root):
        self.root=Path(root); self.root.mkdir(mode=0o700)
        self.fail_before=False; self.fail_after=False; self.effects=0
    def check(self, kind): pass
    def _paths(self, claim):
        if not re.fullmatch(r'aa-[a-f0-9]{32}',claim.tenant_ref): raise Conflict('bad fixture binding')
        leaf=self.root/claim.tenant_ref
        if leaf.is_symlink(): raise Conflict('unsafe fixture path')
        leaf.mkdir(mode=0o700,exist_ok=True)
        return leaf,leaf/'state.json',leaf/(claim.operation_id+'.receipt.json')
    def execute(self, claim):
        leaf,state_path,receipt_path=self._paths(claim)
        if receipt_path.exists(): return Receipt(**json.loads(receipt_path.read_text()))
        state=json.loads(state_path.read_text()) if state_path.exists() else {
            'account':claim.account_id,'deployment':claim.deployment_id,
            'state':'absent','generation':1,'canary':claim.account_id+'-private-canary',
            'channels_enabled':False,
        }
        if (state['account'],state['deployment'],state['generation'])!=(claim.account_id,claim.deployment_id,claim.generation):
            raise Conflict('fixture target mismatch')
        if self.fail_before:
            return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                           state['state'],False,state['state']!='running',fence=claim.fence)
        kind=claim.kind
        target={'create':'stopped','start':'running','stop':'stopped','backup':'stopped',
                'restore':'stopped','upgrade':'running','delete':'absent'}[kind]
        if kind=='backup':
            (leaf/(claim.operation_id+'.backup.json')).write_text(json.dumps(state))
        if kind=='restore':
            # Offline staging before replacement; not proof of native restore isolation.
            saved=json.loads((leaf/(claim.backup_ref+'.backup.json')).read_text())
            if saved['account']!=claim.account_id: raise Conflict('foreign backup')
            saved['generation']=claim.generation; saved['channels_enabled']=False
            state=saved
        state['state']=target
        if kind in {'upgrade','restore'}:state['generation']+=1
        state_path.write_text(json.dumps(state))
        self.effects+=1
        receipt=Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                        target,True,target!='running',claim.operation_id if kind=='backup' else None,fence=claim.fence)
        receipt_path.write_text(json.dumps(asdict(receipt)))
        if self.fail_after: raise TimeoutError('synthetic lost response')
        return receipt
    def reconcile(self, claim):
        _,_,receipt=self._paths(claim)
        return Receipt(**json.loads(receipt.read_text())) if receipt.exists() else None
