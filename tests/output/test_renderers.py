"""Renderer tests — JSON/YAML round-trip and table snapshot."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

from rich.console import Console

from eks_identity_migrator.output import (
    dump_yaml,
    inventory_to_json,
    load_yaml,
    plan_from_yaml,
    plan_to_json,
    plan_to_yaml,
    render_inventory_table,
)
from eks_identity_migrator.types import (
    AssociationSpec,
    ClusterRef,
    FindingModel,
    Inventory,
    Mapping,
    Plan,
    PlanStep,
    PodRef,
    RiskClassification,
    SARef,
)

CLUSTER = ClusterRef(
    name="my-cluster",
    region="us-west-2",
    account="123456789012",
    oidc_issuer="https://oidc.eks.us-west-2.amazonaws.com/id/EX",
    arn="arn:aws:eks:us-west-2:123456789012:cluster/my-cluster",
)
TS = datetime(2026, 5, 8, 14, 32, tzinfo=UTC)


def make_inventory() -> Inventory:
    return Inventory(
        cluster=CLUSTER,
        generated_at=TS,
        mappings=[
            Mapping(
                sa=SARef(namespace="prod", name="app"),
                role_arn="arn:aws:iam::123456789012:role/app",
                trust_policy={"Version": "2012-10-17", "Statement": []},
                used_by_pods=[PodRef(namespace="prod", name="app-x", owner="Deployment/app")],
                risk=RiskClassification.GREEN,
            ),
            Mapping(
                sa=SARef(namespace="data", name="etl"),
                role_arn="arn:aws:iam::123456789012:role/etl",
                trust_policy={"Version": "2012-10-17", "Statement": []},
                used_by_pods=[PodRef(namespace="data", name="etl-x", owner="Job/etl")],
                risk=RiskClassification.RED,
                findings=[
                    FindingModel(
                        code="CROSS_ACCOUNT_TRUST",
                        severity="error",
                        message="cross-account",
                    )
                ],
            ),
        ],
    )


def make_plan() -> Plan:
    return Plan(
        cluster=CLUSTER,
        strategy="append",
        generated_at=TS,
        steps=[
            PlanStep(
                sa=SARef(namespace="prod", name="app"),
                role_arn="arn:aws:iam::123456789012:role/app",
                risk=RiskClassification.GREEN,
                association_create=AssociationSpec(
                    cluster_name="my-cluster",
                    namespace="prod",
                    service_account="app",
                    role_arn="arn:aws:iam::123456789012:role/app",
                ),
            )
        ],
    )


# ---- JSON


def test_inventory_to_json_round_trip() -> None:
    inv = make_inventory()
    text = inventory_to_json(inv)
    parsed = json.loads(text)
    # camelCase
    assert parsed["mappings"][0]["roleArn"].startswith("arn:")
    assert parsed["mappings"][0]["usedByPods"]
    # Round-trip
    inv2 = Inventory.model_validate(parsed)
    assert inv2 == inv


def test_inventory_json_byte_stable() -> None:
    inv = make_inventory()
    a = inventory_to_json(inv)
    b = inventory_to_json(inv)
    assert a == b


def test_plan_to_json_round_trip() -> None:
    plan = make_plan()
    text = plan_to_json(plan)
    plan2 = Plan.model_validate(json.loads(text))
    assert plan2 == plan


# ---- YAML


def test_plan_yaml_round_trip_byte_stable() -> None:
    plan = make_plan()
    a = plan_to_yaml(plan)
    plan2 = plan_from_yaml(a)
    b = plan_to_yaml(plan2)
    assert plan == plan2
    assert a == b  # acceptance §12.2


def test_dump_yaml_sorts_keys() -> None:
    payload = {"z": 1, "a": 2, "m": 3}
    text = dump_yaml(payload)
    assert text.index("a:") < text.index("m:") < text.index("z:")


def test_load_yaml_round_trip_pure_json() -> None:
    payload = {"a": [1, 2], "b": {"c": True, "d": "s"}}
    text = dump_yaml(payload)
    assert load_yaml(text) == payload


# ---- table snapshot


def test_render_inventory_table_includes_all_columns_and_summary() -> None:
    inv = make_inventory()
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=200, force_terminal=False)
    console.print(render_inventory_table(inv))
    out = buf.getvalue()
    for col in ("NAMESPACE", "SA", "ROLE", "RISK", "FINDINGS"):
        assert col in out
    assert "GREEN" in out
    assert "RED" in out
    assert "2 ServiceAccounts" in out
    assert "CROSS_ACCOUNT_TRUST" in out
