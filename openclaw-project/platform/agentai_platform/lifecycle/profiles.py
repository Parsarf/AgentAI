"""Measured trial profile and live host capacity. Read-only: never starts or stops anything.

Numbers come from the 2026-10-11 measurements on the 15.6 GiB / 4 vCPU host
(evidence/product/phase-04/20261011T235500Z): an idle gVisor Gateway cell raised
host memory use by about 0.46 GiB (container reported 0.74 GiB); a light Chromium
page peaked near 0.13 GiB. Admission does not rely on observed peaks: it reserves
the enforced caps (cell 2 GiB, worker ceiling 1.5 GiB), which the kernel cgroup
enforces, so a heavier page is killed rather than overcommitting the host.
"""
from datetime import datetime, timezone
import os

from agentai_platform.capacity import CapacityResult, assess

GIB = 1024 ** 3

PROFILE_ID = 'trial-measured-v1'
CELL_MEMORY = 2 * GIB            # enforced --memory; 1 GiB was OOM-killed in a real chat turn (peak ~1.4 GiB, 2026-10-12)
WORKER_MEMORY = int(1.5 * GIB)   # enforced ceiling for the one active worker stage
CELL_MILLIS = 1000               # enforced cell CPU cap
WORKER_MILLIS = 1500
CELL_PIDS, WORKER_PIDS = 256, 256
VOLUME_BYTES = 10 * GIB          # hard per-tenant state volume
RESERVE_MEMORY = 2 * GIB + 512 * 1024**2   # safety + platform services
RESERVE_MILLIS = 500             # owner/platform CPU headroom
RESERVE_DISK = 20 * GIB
RESERVE_PIDS = 512


def meminfo_available():
    with open('/proc/meminfo') as handle:
        for line in handle:
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) * 1024
    raise OSError('MemAvailable missing')


def host_capacity(*, now=None, running_cells=0, available=meminfo_available, cpus=os.cpu_count,
                  disk_free=lambda: os.statvfs('/var/lib').f_bavail * os.statvfs('/var/lib').f_frsize,
                  isolation_verified=True, tenant_peak_verified=True):
    """How many more tenants fit right now, from live host numbers and enforced caps.

    `running_cells` are already counted in MemAvailable, so only a cell about to
    start plus one worker stage is charged per tenant.
    """
    now = now or datetime.now(timezone.utc)
    per_tenant_memory = CELL_MEMORY + WORKER_MEMORY
    rows = {
        'memory': {'total': available(), 'fixed': 0, 'reserve': RESERVE_MEMORY, 'tenant': per_tenant_memory},
        'cpu': {'total': cpus() * 1000, 'fixed': 0, 'reserve': RESERVE_MILLIS, 'tenant': CELL_MILLIS + WORKER_MILLIS},
        'disk': {'total': disk_free(), 'fixed': 0, 'reserve': RESERVE_DISK, 'tenant': VOLUME_BYTES},
        'pids': {'total': 32768, 'fixed': 0, 'reserve': RESERVE_PIDS, 'tenant': CELL_PIDS + WORKER_PIDS},
    }
    return assess(rows, measured_at=now, now=now, isolation_verified=isolation_verified,
                  tenant_peak_verified=tenant_peak_verified, shared_host_selected=True)
