"""Tests for k8s.config.get_current_context_hint().

The hint lets `audit`/`plan`/`migrate` default `--cluster` from the user's
current kubectl context. The parser must handle the common EKS context-name
shapes without ever crashing — if a context name is unfamiliar, we fall back
to using it verbatim as the cluster name and let the EKS describe call fail
later with a clearer message.
"""

from __future__ import annotations

import pytest

from eks_identity_migrator.k8s.config import (
    ContextHint,
    KubeContextResolutionError,
    get_current_context_hint,
    parse_context_name,
)


class TestParseContextName:
    """parse_context_name() is the pure function — no kubeconfig I/O."""

    def test_eks_arn_form_extracts_cluster_and_region(self) -> None:
        ctx = "arn:aws:eks:us-west-2:123456789012:cluster/prod-east"
        hint = parse_context_name(ctx)
        assert hint == ContextHint(cluster_name="prod-east", region="us-west-2", context_name=ctx)

    def test_eks_arn_china_partition(self) -> None:
        ctx = "arn:aws-cn:eks:cn-north-1:123456789012:cluster/beijing"
        hint = parse_context_name(ctx)
        assert hint.cluster_name == "beijing"
        assert hint.region == "cn-north-1"

    def test_eksctl_form_extracts_cluster_and_region(self) -> None:
        ctx = "iam-user@my-cluster.us-west-2.eksctl.io"
        hint = parse_context_name(ctx)
        assert hint == ContextHint(cluster_name="my-cluster", region="us-west-2", context_name=ctx)

    def test_eksctl_form_with_dots_in_cluster_name(self) -> None:
        # cluster names can contain dashes; eksctl uses the last two dotted segments as host
        ctx = "admin@prod-east-1.us-east-1.eksctl.io"
        hint = parse_context_name(ctx)
        assert hint.cluster_name == "prod-east-1"
        assert hint.region == "us-east-1"

    def test_plain_name_is_used_verbatim_no_region(self) -> None:
        hint = parse_context_name("my-cluster")
        assert hint == ContextHint(
            cluster_name="my-cluster", region=None, context_name="my-cluster"
        )

    def test_kind_context_falls_back_to_verbatim(self) -> None:
        # kind clusters: `kind-foo`. Use as-is; EKS describe will fail later with a clear error.
        hint = parse_context_name("kind-foo")
        assert hint.cluster_name == "kind-foo"
        assert hint.region is None


class TestGetCurrentContextHint:
    """get_current_context_hint() integrates list_kube_config_contexts()."""

    def test_uses_active_context_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_list_contexts(
            config_file: str | None = None,
        ) -> tuple[list[dict[str, str]], dict[str, str]]:
            return (
                [{"name": "arn:aws:eks:us-west-2:123:cluster/foo"}],
                {"name": "arn:aws:eks:us-west-2:123:cluster/foo"},
            )

        monkeypatch.setattr("kubernetes.config.list_kube_config_contexts", fake_list_contexts)
        hint = get_current_context_hint()
        assert hint.cluster_name == "foo"
        assert hint.region == "us-west-2"

    def test_no_kubeconfig_raises_resolution_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kubernetes.config.config_exception import ConfigException

        def fake_list_contexts(
            config_file: str | None = None,
        ) -> tuple[list[dict[str, str]], dict[str, str]]:
            raise ConfigException("no config file found")

        monkeypatch.setattr("kubernetes.config.list_kube_config_contexts", fake_list_contexts)
        with pytest.raises(KubeContextResolutionError) as exc_info:
            get_current_context_hint()
        # Error message should be educational — point the user at the fix.
        assert "kubeconfig" in str(exc_info.value).lower()

    def test_no_active_context_raises_resolution_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_list_contexts(
            config_file: str | None = None,
        ) -> tuple[list[dict[str, str]], dict[str, str] | None]:
            return ([], None)

        monkeypatch.setattr("kubernetes.config.list_kube_config_contexts", fake_list_contexts)
        with pytest.raises(KubeContextResolutionError):
            get_current_context_hint()

    def test_active_context_missing_name_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_list_contexts(
            config_file: str | None = None,
        ) -> tuple[list[dict[str, str]], dict[str, str]]:
            return ([{"name": "x"}], {})  # active context dict with no name

        monkeypatch.setattr("kubernetes.config.list_kube_config_contexts", fake_list_contexts)
        with pytest.raises(KubeContextResolutionError):
            get_current_context_hint()

    def test_kubeconfig_path_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        def fake_list_contexts(
            config_file: str | None = None,
        ) -> tuple[list[dict[str, str]], dict[str, str]]:
            captured["config_file"] = config_file
            return ([{"name": "x"}], {"name": "x"})

        monkeypatch.setattr("kubernetes.config.list_kube_config_contexts", fake_list_contexts)
        get_current_context_hint(kubeconfig="/tmp/custom-kubeconfig")
        assert captured["config_file"] == "/tmp/custom-kubeconfig"
