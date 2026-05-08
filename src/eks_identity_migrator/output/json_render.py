"""Deterministic JSON output for Inventory and Plan.

`model_dump_json(by_alias=True)` gives camelCase keys; we re-serialise through
`json.dumps(..., sort_keys=True)` so output is byte-stable across runs.
"""

from __future__ import annotations

import json
from typing import Any

from eks_identity_migrator.types.inventory import Inventory
from eks_identity_migrator.types.plan import Plan


def _to_canonical(payload: Any, *, indent: int = 2) -> str:
    return json.dumps(payload, sort_keys=True, indent=indent, default=str)


def inventory_to_json(inv: Inventory) -> str:
    payload = inv.model_dump(by_alias=True, mode="json")
    return _to_canonical(payload)


def plan_to_json(plan: Plan) -> str:
    payload = plan.model_dump(by_alias=True, mode="json")
    return _to_canonical(payload)
