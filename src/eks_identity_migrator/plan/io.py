"""Plan YAML read/write — uses ruamel for lossless round-trip + sorted keys."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from eks_identity_migrator.output.yaml_render import dump_yaml, load_yaml
from eks_identity_migrator.types.plan import Plan


def write_plan(plan: Plan, path: str | Path) -> None:
    payload = plan.model_dump(by_alias=True, mode="json")
    text = dump_yaml(payload)
    Path(path).write_text(text)


def read_plan(path: str | Path) -> Plan:
    raw = load_yaml(Path(path).read_text())
    if isinstance(raw.get("generatedAt"), str):
        # ruamel safe loader keeps strings as strings; pydantic will parse to datetime.
        pass
    elif isinstance(raw.get("generatedAt"), datetime):
        raw["generatedAt"] = raw["generatedAt"].isoformat()
    return Plan.model_validate(raw)
