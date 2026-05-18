"""Tests for cli._resolve.resolve_cluster() — the CLI-layer auto-detect helper.

`audit`, `plan`, and `migrate` take an optional `--cluster`. When omitted we
infer it from the current kubectl context. This helper centralises that
resolution so the three commands behave identically.
"""

from __future__ import annotations

import pytest
import typer

from eks_identity_migrator.cli._resolve import resolve_cluster
from eks_identity_migrator.cli.exit_codes import ExitCode
from eks_identity_migrator.k8s.config import ContextHint


def _hint(
    name: str = "ctx", cluster: str = "auto-cluster", region: str | None = "us-west-2"
) -> ContextHint:
    return ContextHint(cluster_name=cluster, region=region, context_name=name)


def test_explicit_cluster_returned_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # If user passed --cluster, we should never touch kubeconfig.
    called = {"hit": False}

    def _hint_fn(**kwargs: object) -> ContextHint:
        called["hit"] = True
        return _hint()

    monkeypatch.setattr("eks_identity_migrator.cli._resolve.get_current_context_hint", _hint_fn)
    cluster, region = resolve_cluster("explicit", "eu-west-1")
    assert cluster == "explicit"
    assert region == "eu-west-1"
    assert called["hit"] is False
    captured = capsys.readouterr()
    # No banner when explicit.
    assert "auto-detected" not in captured.err


def test_auto_detect_when_cluster_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "eks_identity_migrator.cli._resolve.get_current_context_hint",
        lambda **kw: _hint(cluster="auto-cluster", region="us-west-2", name="my-ctx"),
    )
    cluster, region = resolve_cluster(None, None)
    assert cluster == "auto-cluster"
    assert region == "us-west-2"
    err = capsys.readouterr().err
    # Banner mentions the cluster + context for transparency.
    assert "auto-cluster" in err
    assert "my-ctx" in err


def test_explicit_region_overrides_hint_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "eks_identity_migrator.cli._resolve.get_current_context_hint",
        lambda **kw: _hint(region="us-west-2"),
    )
    _cluster, region = resolve_cluster(None, "eu-central-1")
    assert region == "eu-central-1"


def test_hint_region_none_keeps_region_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eks_identity_migrator.cli._resolve.get_current_context_hint",
        lambda **kw: _hint(region=None),
    )
    _cluster, region = resolve_cluster(None, None)
    assert region is None


def test_no_kubeconfig_raises_typer_exit_with_invalid_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from eks_identity_migrator.k8s.config import KubeContextResolutionError

    def _hint_fn(**kwargs: object) -> ContextHint:
        raise KubeContextResolutionError("no kubeconfig")

    monkeypatch.setattr("eks_identity_migrator.cli._resolve.get_current_context_hint", _hint_fn)
    with pytest.raises(typer.Exit) as exc_info:
        resolve_cluster(None, None)
    assert exc_info.value.exit_code == int(ExitCode.INVALID_INPUT)
    err = capsys.readouterr().err
    # Error message points the user at the two ways to fix it.
    assert "--cluster" in err
