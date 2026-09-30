#!/usr/bin/env python3
"""Reproduce observed capacity bound; projections are explicitly unmeasured."""
import json
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'platform'))
from agentai_platform.capacity import assess
BASE=Path(__file__).resolve().parent
x=json.loads((BASE/'phase-04-inventory.json').read_text())
checks=json.loads((BASE/'phase-04-host-checks.json').read_text())
samples=x['samples'];total=samples[0]['memory_bytes']['MemTotal']
available=min(s['memory_bytes']['MemAvailable'] for s in samples)
platform_reserve=256*1024**2;safety_reserve=512*1024**2
native_default_ram=2*1024**3
# Current inspected snapshot proves a memory bound, not tenant/task peaks.
rows={'memory':{'total':total,'fixed':total-available,'reserve':platform_reserve+safety_reserve,'tenant':native_default_ram},
      'cpu':{'total':samples[0]['cpu_count']*1000,'fixed':None,'reserve':250,'tenant':2000},
      'disk':{'total':None,'fixed':None,'reserve':10*1024**3,'tenant':None},
      'pids':{'total':None,'fixed':None,'reserve':64,'tenant':None}}
timestamp=datetime.fromisoformat(x['observed_at'])
result=assess(rows,measured_at=timestamp,now=timestamp,isolation_verified=False,tenant_peak_verified=False,shared_host_selected=True)
# Report age is historical; live admission must pass current clock freshness too.
output={'observed_at':x['observed_at'],'source':'phase-04-inventory.json (three short read-only samples; no load benchmark)',
 'memory_total_bytes':total,'memory_available_min_bytes':available,'memory_available_max_bytes':max(s['memory_bytes']['MemAvailable'] for s in samples),
 'fixed_unavailable_snapshot_highwater_bytes':total-available,
 'planned_platform_reserve_bytes':platform_reserve,'planned_safety_headroom_bytes':safety_reserve,
 'remaining_after_reserves_bytes':max(0,available-platform_reserve-safety_reserve),
 'fleet_default_container_limit_bytes':native_default_ram,
 'swap_total_bytes':samples[0]['memory_bytes']['SwapTotal'],'swap_free_min_bytes':min(s['memory_bytes']['SwapFree'] for s in samples),
 'resource_matrix':rows,'assessment':asdict(result),
 'planned_16gib_scenario':{'status':'UNMEASURED allocation proposal; not admitted capacity',
 'ram_gib':16,'vcpus':4,'beta_accounts':2,'global_running_tasks':1,'ram_envelope_gib':{'owner_services':4,'product_services':0.5,'safety':2,'two_gateway_cells':4,'one_active_worker_set':3},
 'sum_envelopes_gib':13.5,'remaining_gib':2.5,'cpu_capacity':None},
 'storage_mount':checks['disk_mount']['output'].strip(),'native_default_runtime':checks['docker_runtime_metadata']['default_runtime']}
(BASE/'phase-04-capacity.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps({k:output[k] for k in ['remaining_after_reserves_bytes','assessment','planned_16gib_scenario']},indent=2))
