from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path

FEATURES = frozenset({"customer_execution", "provisioning", "telegram", "uploads", "billing_live", "optimization", "purchases"})
@dataclass(frozen=True)
class Config:
    bind: str
    app_port: int
    control_port: int
    state_dir: Path
    max_connections: int
    socket_timeout_seconds: int
    max_body_bytes: int
    features: dict[str, bool]

    @classmethod
    def load(cls, path: Path) -> Config:
        raw = json.loads(path.read_text())
        expected = {"schema_version", "bind", "app_port", "control_port", "state_dir", "max_connections", "socket_timeout_seconds", "max_body_bytes", "features"}
        if set(raw) != expected or raw["schema_version"] != 1:
            raise ValueError("unsupported config schema")
        if raw["bind"] != "127.0.0.1":
            raise ValueError("foundation requires loopback binding")
        for key, low, high in [("app_port",1024,65535),("control_port",1024,65535),("max_connections",1,16),("socket_timeout_seconds",1,10),("max_body_bytes",1,16384)]:
            if type(raw[key]) is not int or not low <= raw[key] <= high:
                raise ValueError("invalid numeric config")
        if raw["app_port"] == raw["control_port"]: raise ValueError("service ports must differ")
        if not isinstance(raw["state_dir"],str) or not raw["state_dir"]: raise ValueError("invalid state directory")
        features = raw["features"]
        if not isinstance(features,dict) or set(features) != FEATURES or any(type(v) is not bool for v in features.values()):
            raise ValueError("invalid feature gates")
        if any(features.values()):
            raise ValueError("foundation cannot activate customer capabilities")
        state = Path(raw["state_dir"])
        if not state.is_absolute(): state = path.parent / state
        return cls(raw["bind"],raw["app_port"],raw["control_port"],state.absolute(),raw["max_connections"],raw["socket_timeout_seconds"],raw["max_body_bytes"],features.copy())
