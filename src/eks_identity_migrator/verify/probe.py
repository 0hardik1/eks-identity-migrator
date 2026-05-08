"""Verification probe — inspect pod env (and optionally exec aws sts) per SA."""

from __future__ import annotations

import json

from eks_identity_migrator.k8s.client import K8sClient
from eks_identity_migrator.types.plan import Plan
from eks_identity_migrator.verify.result import VerifyEntry, VerifyResult, VerifyStatus

POD_IDENTITY_ENV_KEYS = {
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
}
IRSA_ENV_KEYS = {"AWS_WEB_IDENTITY_TOKEN_FILE"}


def _classify_envs(env_names: set[str]) -> VerifyStatus:
    has_pi = bool(env_names & POD_IDENTITY_ENV_KEYS)
    has_irsa = bool(env_names & IRSA_ENV_KEYS)
    if has_pi and has_irsa:
        return VerifyStatus.DUAL
    if has_pi:
        return VerifyStatus.POD_IDENTITY
    if has_irsa:
        return VerifyStatus.IRSA
    # Neither — could mean SDK uses node IMDS or no AWS access at all.
    return VerifyStatus.FAILED


def verify(
    plan: Plan,
    *,
    k8s: K8sClient,
    probe: bool = False,
) -> VerifyResult:
    """Inspect each non-skipped step and classify the credential source in use."""
    result = VerifyResult()
    for step in plan.steps:
        if step.skip:
            continue
        sa = step.sa
        pods = [p for p in k8s.list_pods(namespace=sa.namespace) if p.service_account == sa.name]
        running = [p for p in pods if p.phase == "Running"]
        if not running:
            result.add(
                VerifyEntry(sa=sa, status=VerifyStatus.DEFERRED, note="no running pod for SA")
            )
            continue
        target_pod = running[0]
        env_names: set[str] = set()
        for envs in target_pod.container_envs.values():
            for name, _value, _value_from in envs:
                env_names.add(name)
        status = _classify_envs(env_names)

        probe_arn: str | None = None
        if probe:
            try:
                out = k8s.exec_in_pod(
                    sa.namespace,
                    target_pod.name,
                    ["aws", "sts", "get-caller-identity", "--output", "json"],
                )
                data = json.loads(out)
                probe_arn = data.get("Arn")
            except Exception:
                probe_arn = None

        result.add(
            VerifyEntry(
                sa=sa,
                status=status,
                pod=target_pod.name,
                note=", ".join(sorted(env_names)) or None,
                probe_arn=probe_arn,
            )
        )
    return result


def render_verify_summary(result: VerifyResult) -> str:
    """One-line per SA, plus a tally summary."""
    lines: list[str] = []
    counts: dict[VerifyStatus, int] = dict.fromkeys(VerifyStatus, 0)
    for e in result.entries:
        counts[e.status] += 1
        lines.append(
            f"{e.sa}: {e.status.value}"
            + (f" (pod={e.pod})" if e.pod else "")
            + (f" arn={e.probe_arn}" if e.probe_arn else "")
        )
    tally = ", ".join(f"{counts[s]} {s.value}" for s in VerifyStatus if counts[s])
    return "\n".join([*lines, f"-- {tally}"])
