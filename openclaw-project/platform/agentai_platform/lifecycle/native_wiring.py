"""Builds the verified native backend from host-owned configuration files.

Used only by the supervisor entry point when the operator passes a wiring file.
Without it the supervisor keeps DisabledDriver. Nothing here reads app data.
"""
import json
from pathlib import Path
import time
import urllib.request

from .fleet_driver import FleetCliDriver, FleetCustody, HeadroomAdmission, linux_mem_available
from .maintenance import HostIsolation
from .cell_config import CellProvisioner
from .litellm_admin import LiteLLMAdmin
from .netpolicy import NetPolicy
from .secrets_custody import ProviderKeys, SecretStore
from .volumes import VolumeManager, default_run

KEYS = {'fleet_custody', 'secrets_dir', 'volume_images', 'cell_state_root', 'firewall_state',
        'firewall_rules', 'cell_pool', 'bridge_gateway', 'model_proxy_port'}


def http_health(port, *, timeout=90, interval=2, opener=urllib.request.urlopen):
    """Loopback Gateway readiness: HTTP 200 within the bound, else unhealthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener(f'http://127.0.0.1:{int(port)}/', timeout=5) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(interval)
    return False


def build_native_backend(wiring_path):
    path = Path(wiring_path)
    wiring = json.loads(path.read_text())
    if type(wiring) is not dict or set(wiring) - {'litellm_env'} != KEYS:
        raise ValueError('unsupported wiring file')
    for name in KEYS - {'cell_pool', 'bridge_gateway', 'model_proxy_port'}:
        if type(wiring[name]) is not str or not Path(wiring[name]).is_absolute():
            raise ValueError('wiring paths must be absolute')
    custody = FleetCustody(json.loads(Path(wiring['fleet_custody']).read_text()))
    policy = NetPolicy(wiring['cell_pool'], wiring['bridge_gateway'], wiring['model_proxy_port'])
    run = default_run
    cells_docker = custody.env.get('DOCKER_HOST')

    def isolation_run(argv):
        # Every docker call made for isolation targets the CELL engine explicitly, never whatever the service environment holds.
        return default_run(argv, {'DOCKER_HOST': cells_docker} if argv and argv[0] == 'docker' and cells_docker else None)
    secrets = SecretStore(wiring['secrets_dir'])
    provisioner = None
    if wiring.get('litellm_env'):
        # Optional: with it, every created cell gets its own capped model key and the Gateway model route.
        if type(wiring['litellm_env']) is not str or not Path(wiring['litellm_env']).is_absolute():
            raise ValueError('wiring paths must be absolute')
        provisioner = CellProvisioner(ProviderKeys(LiteLLMAdmin(wiring['litellm_env']).http, secrets), secrets, wiring['cell_state_root'])
    driver = FleetCliDriver(
        custody,
        secrets=secrets,
        volumes=VolumeManager(wiring['volume_images'], wiring['cell_state_root'], run=run),
        isolation=HostIsolation(wiring['firewall_state'], wiring['firewall_rules'], policy, isolation_run),
        health=http_health, provisioner=provisioner)
    return driver, HeadroomAdmission(linux_mem_available, custody.reserve)
