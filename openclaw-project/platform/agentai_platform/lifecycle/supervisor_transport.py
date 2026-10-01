"""Bounded local control protocol. Never publish this socket through HTTP.

Linux SO_PEERCRED authenticates the controller UID; filesystem ownership/mode
authenticates the server to the client. No enrollment, commands, paths or secret
fields are accepted. An IPC timeout is an uncertain result, never permission to
send the operation again.
"""
from dataclasses import asdict, fields
import json
import os
from pathlib import Path
import socket
import stat
import struct

from agentai_platform.adapters import CapabilityUnavailable
from .types import Conflict, Receipt
from .supervisor import decode_claim, OutcomeUncertain, SupervisorBusy, validate_receipt

MAX_BYTES=8192


def encode(payload):
    body=json.dumps(payload,separators=(',',':'),ensure_ascii=True).encode()+b'\n'
    if len(body)>MAX_BYTES: raise Conflict('message too large')
    return body


def read_message(conn):
    data=bytearray()
    while len(data)<MAX_BYTES:
        chunk=conn.recv(min(1024,MAX_BYTES-len(data)))
        if not chunk: raise Conflict('incomplete message')
        data.extend(chunk)
        if b'\n' in chunk:
            if not data.endswith(b'\n') or data.count(b'\n')!=1:
                raise Conflict('invalid framing')
            try:
                # Reject duplicate fields instead of silently selecting the last.
                def pairs(items):
                    value={}
                    for k,v in items:
                        if k in value: raise Conflict('duplicate field')
                        value[k]=v
                    return value
                value=json.loads(data,object_pairs_hook=pairs)
            except (ValueError,UnicodeDecodeError): raise Conflict('invalid JSON') from None
            if type(value) is not dict: raise Conflict('invalid envelope')
            return value
    raise Conflict('message too large')


def dispatch(supervisor,payload):
    if type(payload) is not dict or payload.get('action') not in {'check','execute','reconcile'}:
        raise Conflict('unsupported action')
    if payload['action']=='check':
        if set(payload)!={'action','kind'}: raise Conflict('invalid envelope')
        supervisor.check(payload['kind']);return {'ok':True}
    if set(payload)!={'action','claim'}: raise Conflict('invalid envelope')
    claim=decode_claim(payload['claim'])
    result=getattr(supervisor,payload['action'])(claim)
    return {'ok':True,'receipt':asdict(result) if result is not None else None}


def handle_connection(conn,supervisor,*,controller_uid):
    try:
        if not hasattr(socket,'SO_PEERCRED'): raise CapabilityUnavailable('Linux peer identity required')
        _,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
        if uid!=controller_uid: raise Conflict('peer denied')
        response=dispatch(supervisor,read_message(conn))
    except CapabilityUnavailable: response={'ok':False,'error':'capability_unavailable'}
    except Conflict: response={'ok':False,'error':'request_denied'}
    except SupervisorBusy: response={'ok':False,'error':'supervisor_busy'}
    except OutcomeUncertain: response={'ok':False,'error':'outcome_uncertain'}
    except Exception: response={'ok':False,'error':'outcome_uncertain'}
    conn.sendall(encode(response)) # No backend exception or output crosses IPC.


class SocketDriver:
    def __init__(self,path,*,server_uid=0,timeout_seconds=5):
        self.path=Path(path);self.server_uid=server_uid
        if not 0<timeout_seconds<=120: raise ValueError('invalid timeout')
        self.timeout=timeout_seconds

    def _call(self,payload):
        info=self.path.lstat();parent=self.path.parent.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=self.server_uid or stat.S_IMODE(info.st_mode)&0o007:
            raise PermissionError('untrusted supervisor socket')
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=self.server_uid or stat.S_IMODE(parent.st_mode)&0o022:
            raise PermissionError('untrusted socket directory')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.settimeout(self.timeout);conn.connect(str(self.path))
            # Linux checks the actual endpoint as well as its pathname.
            if hasattr(socket,'SO_PEERCRED'):
                _,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
                if uid!=self.server_uid: raise PermissionError('untrusted supervisor peer')
            conn.sendall(encode(payload));response=read_message(conn)
        if response.get('ok') is not True:
            error=response.get('error')
            if error=='capability_unavailable': raise CapabilityUnavailable('native lifecycle not verified')
            if error=='request_denied': raise Conflict('supervisor denied request')
            if error=='supervisor_busy': raise SupervisorBusy('supervisor busy')
            raise OutcomeUncertain('reconciliation required')
        return response

    def check(self,kind):
        response=self._call({'action':'check','kind':kind})
        if set(response)!={'ok'}: raise Conflict('invalid capability response')

    def _receipt(self,action,claim):
        claim=decode_claim(asdict(claim))
        response=self._call({'action':action,'claim':asdict(claim)})
        if set(response)!={'ok','receipt'}: raise Conflict('invalid receipt envelope')
        raw=response['receipt']
        if action=='reconcile' and raw is None: return None
        if type(raw) is not dict or set(raw)!={f.name for f in fields(Receipt)}:
            raise Conflict('invalid receipt schema')
        receipt=Receipt(**raw);validate_receipt(claim,receipt);return receipt

    def execute(self,claim): return self._receipt('execute',claim)
    def reconcile(self,claim): return self._receipt('reconcile',claim)
