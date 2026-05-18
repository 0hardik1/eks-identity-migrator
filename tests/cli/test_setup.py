"""Tests for cli/setup.py:make_clients() — the shared client factory.

`make_clients()` builds the four AWS clients (session/iam/eks/sts) and the
K8s client used by audit, plan, and migrate. Centralising the construction
removes ~30 lines of duplication and keeps the AWS/K8s boundary rule clean.

We stub every boto/k8s constructor so the tests don't need real AWS config.
"""

from __future__ import annotations

from typing import Any

import pytest

from eks_identity_migrator.cli.setup import Clients, make_clients


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub make_session + Boto*Client + load_kube_config + KubernetesClient.

    Returns a dict capturing every call's kwargs so each test can assert
    on how `make_clients()` wired things up.
    """
    captured: dict[str, Any] = {"load_kwargs": None}

    def fake_make_session(**kwargs: Any) -> Any:
        captured["session_kwargs"] = kwargs
        return object()

    def fake_load(**kwargs: Any) -> None:
        captured["load_kwargs"] = kwargs

    monkeypatch.setattr("eks_identity_migrator.cli.setup.make_session", fake_make_session)
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoIamClient", lambda s: f"iam:{s!r}")
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoEksClient", lambda s: f"eks:{s!r}")
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoStsClient", lambda s: f"sts:{s!r}")
    monkeypatch.setattr("eks_identity_migrator.cli.setup.load_kube_config", fake_load)
    monkeypatch.setattr("eks_identity_migrator.cli.setup.KubernetesClient", lambda: "k8s-instance")
    return captured


def test_returns_clients_namedtuple_with_all_four_clients(patched: dict[str, Any]) -> None:
    clients = make_clients(region=None, profile=None)
    assert isinstance(clients, Clients)
    # Each field is set; we patched the constructors to return stub strings.
    # cast() not needed — runtime type check via `is not None` suffices for the test contract.
    assert str(clients.iam).startswith("iam:")
    assert str(clients.eks).startswith("eks:")
    assert str(clients.sts).startswith("sts:")
    assert str(clients.k8s) == "k8s-instance"


def test_forwards_region_and_profile_to_session(patched: dict[str, Any]) -> None:
    make_clients(region="eu-west-1", profile="dev")
    assert patched["session_kwargs"] == {"region": "eu-west-1", "profile": "dev"}


def test_default_region_and_profile_pass_none(patched: dict[str, Any]) -> None:
    make_clients(region=None, profile=None)
    assert patched["session_kwargs"] == {"region": None, "profile": None}


def test_forwards_kubeconfig_and_context_to_load(patched: dict[str, Any]) -> None:
    make_clients(region=None, profile=None, kubeconfig="/tmp/k", context="ctx-x")
    assert patched["load_kwargs"] == {"kubeconfig": "/tmp/k", "context": "ctx-x"}


def test_no_kubeconfig_args_passes_none(patched: dict[str, Any]) -> None:
    make_clients(region=None, profile=None)
    assert patched["load_kwargs"] == {"kubeconfig": None, "context": None}


def test_kubeconfig_load_happens_before_kubernetes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order matters — load_kube_config must run before KubernetesClient()."""
    order: list[str] = []

    monkeypatch.setattr("eks_identity_migrator.cli.setup.make_session", lambda **kw: object())
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoIamClient", lambda s: object())
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoEksClient", lambda s: object())
    monkeypatch.setattr("eks_identity_migrator.cli.setup.BotoStsClient", lambda s: object())

    def _load(**kw: Any) -> None:
        order.append("load")

    def _client() -> object:
        order.append("client")
        return object()

    monkeypatch.setattr("eks_identity_migrator.cli.setup.load_kube_config", _load)
    monkeypatch.setattr("eks_identity_migrator.cli.setup.KubernetesClient", _client)

    make_clients(region=None, profile=None)
    assert order == ["load", "client"]
