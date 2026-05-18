"""Verify which credential source each running pod is using.

A pod still on IRSA has ``AWS_WEB_IDENTITY_TOKEN_FILE`` in its environment;
a pod on Pod Identity has ``AWS_CONTAINER_CREDENTIALS_FULL_URI``. Both
present means the SDK will pick Pod Identity first — but the legacy IRSA
env stays until the pod is restarted. This package classifies each pod and
optionally probes ``sts:GetCallerIdentity`` from inside the pod to confirm.

Use this as the gate before running ``apply --phase cleanup`` — once verify
is clean for every SA, it's safe to strip the IRSA annotation and (with
``--remove-oidc-trust``) the OIDC statements from the role.
"""

from __future__ import annotations

from eks_identity_migrator.cli.exit_codes import ExitCode


def run(
    *,
    plan: str,
    probe: bool,
    region: str | None,
    profile: str | None,
) -> ExitCode:
    from eks_identity_migrator.verify.entry import run as _run

    return _run(plan=plan, probe=probe, region=region, profile=profile)
