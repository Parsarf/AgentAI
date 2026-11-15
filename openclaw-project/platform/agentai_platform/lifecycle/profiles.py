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


def meminfo_total():
    with open('/proc/meminfo') as handle:
        for line in handle:
            if line.startswith('MemTotal:'):
                return int(line.split()[1]) * 1024
    raise OSError('MemTotal missing')


def cpu_oversubscription():
    """How many cells may share one CPU's worth of reservation (default 2). A cell is capped at one CPU by its cgroup, but an assistant mostly waits on the model provider,
    so reserving a full CPU per cell would admit one customer on a four-CPU host. The cap is not changed: a busy cell can still use a whole CPU. Owner setting
    `cpu_oversubscribe` in the signup settings file, 1 to 4."""
    from .capacity import setting
    value = setting('cpu_oversubscribe', 2)
    return value if type(value) in (int, float) and 1 <= value <= 4 else 2


def host_capacity(*, now=None, running_cells=0, available=meminfo_available, cpus=os.cpu_count, total=None,
                  disk_free=lambda: os.statvfs('/var/lib').f_bavail * os.statvfs('/var/lib').f_frsize,
                  isolation_verified=True, tenant_peak_verified=True, oversubscribe=None):
    """How many MORE cells fit right now, from live host numbers and the enforced caps.

    A flexible host, not a fixed pool: the answer follows memory, CPU, disk and process limits, so a bigger server admits more cells with no code change.
    * memory: the smaller of what the kernel says is available (running cells are already in it) and what is left after every running cell is charged its full
      enforced cap (a cell that grows to its cap must not push the host into the OOM killer), minus one worker stage (the broker runs at most one at a time).
    * CPU: a cell is charged `CELL_MILLIS / oversubscribe` of reservation; running cells and the one worker stage are deducted first.
    `running_cells` is the number of cells already running: they are in MemAvailable, but the CPU and cap arithmetic must subtract them.
    """
    now = now or datetime.now(timezone.utc)
    ratio = oversubscribe if oversubscribe is not None else cpu_oversubscription()
    cell_millis = max(1, int(CELL_MILLIS / ratio))
    try:
        host_total = (total or meminfo_total)()
    except OSError:
        host_total = None                 # no /proc (a development machine): MemAvailable alone decides
    avail = available()
    capped_free = avail if host_total is None else max(0, host_total - running_cells * CELL_MEMORY)
    rows = {
        'memory': {'total': min(avail, capped_free), 'fixed': WORKER_MEMORY, 'reserve': RESERVE_MEMORY, 'tenant': CELL_MEMORY},
        'cpu': {'total': cpus() * 1000, 'fixed': WORKER_MILLIS + running_cells * cell_millis, 'reserve': RESERVE_MILLIS, 'tenant': cell_millis},
        'disk': {'total': disk_free(), 'fixed': 0, 'reserve': RESERVE_DISK, 'tenant': VOLUME_BYTES},
        'pids': {'total': 32768, 'fixed': running_cells * CELL_PIDS, 'reserve': RESERVE_PIDS, 'tenant': CELL_PIDS},
    }
    return assess(rows, measured_at=now, now=now, isolation_verified=isolation_verified,
                  tenant_peak_verified=tenant_peak_verified, shared_host_selected=True)


def running_cell_count(store):
    """Cells the database says are running or being started (the cell slot pool)."""
    with store.connect() as con:
        return con.execute('SELECT count(*) FROM cell_slots').fetchone()[0]


def host_capacity_for(store, **kw):
    """A capacity callable for the workers: live host numbers with this host's running cells deducted."""
    def capacity():
        return host_capacity(running_cells=running_cell_count(store), **kw)
    return capacity
