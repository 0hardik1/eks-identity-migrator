"""Deterministic YAML output via ruamel — supports lossless round-trip.

Always serialise pydantic models through `model_dump(by_alias=True, mode='json')`
*first*, so we hand a pure JSON-compatible dict to ruamel (avoids `True`/`False`
casing surprises and datetime sub-class issues).
"""

from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML

from eks_identity_migrator.types.plan import Plan


def _new_yaml() -> YAML:
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_unicode = True
    yaml.sort_base_mapping_type_on_output = True
    return yaml


def dump_yaml(payload: Any) -> str:
    """Dump a pure-JSON-shaped Python object to a YAML string."""
    yaml = _new_yaml()
    buf = io.StringIO()
    yaml.dump(payload, buf)
    return buf.getvalue()


def load_yaml(text: str) -> Any:
    yaml = _new_yaml()
    return yaml.load(io.StringIO(text))


def plan_to_yaml(plan: Plan) -> str:
    payload = plan.model_dump(by_alias=True, mode="json")
    return dump_yaml(payload)


def plan_from_yaml(text: str) -> Plan:
    raw = load_yaml(text)
    return Plan.model_validate(raw)
