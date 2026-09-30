"""Read-only capacity calculations. Never provision, stop or resize a resource."""
from __future__ import annotations
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass(frozen=True)
class CapacityResult:
    memory_slots: int | None
    cpu_slots: int | None
    disk_slots: int | None
    pid_slots: int | None
    admitted_slots: int
    blockers: tuple[str,...]

def slots(total: int | None, fixed: int | None, reserve: int | None, tenant: int | None) -> int | None:
    values=(total,fixed,reserve,tenant)
    if any(v is None for v in values):return None
    if any(type(v) is not int or v<0 for v in values) or tenant==0:raise ValueError('invalid resource units')
    return max(0,(total-fixed-reserve)//tenant)

def assess(resources: dict, *, measured_at: datetime, now: datetime,
           isolation_verified: bool, tenant_peak_verified: bool,
           shared_host_selected: bool) -> CapacityResult:
    required={'memory','cpu','disk','pids'}
    if set(resources)!=required:raise ValueError('resource matrix incomplete')
    if measured_at.tzinfo is None or now.tzinfo is None:raise ValueError('timezone required')
    capacities={}
    for k,row in resources.items():
        if set(row)!={'total','fixed','reserve','tenant'}:raise ValueError('resource row incomplete')
        capacities[k]=slots(**row)
    blockers=[]
    if measured_at<now-timedelta(minutes=15) or measured_at>now+timedelta(seconds=30):blockers.append('measurement_stale')
    if not shared_host_selected:blockers.append('architecture_not_selected')
    if not isolation_verified:blockers.append('isolation_unverified')
    if not tenant_peak_verified:blockers.append('tenant_peak_unverified')
    for k,n in capacities.items():
        if n is None:blockers.append(k+'_unknown')
        elif n==0:blockers.append(k+'_exhausted')
    admitted=0 if blockers else min(capacities.values())
    return CapacityResult(capacities['memory'],capacities['cpu'],capacities['disk'],capacities['pids'],admitted,tuple(blockers))
