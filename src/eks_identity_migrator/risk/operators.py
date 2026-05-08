"""Well-known operator ServiceAccount registry (gotcha 9).

Each entry is (sa_name_pattern, hint). `*` is treated as a glob suffix.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

OPERATOR_SAS: tuple[tuple[str, str], ...] = (
    (
        "aws-load-balancer-controller",
        "Check the AWS Load Balancer Controller docs for Pod Identity support.",
    ),
    ("cluster-autoscaler", "Cluster Autoscaler can use Pod Identity in recent versions."),
    ("karpenter", "Karpenter v0.32+ supports Pod Identity natively."),
    ("external-dns", "external-dns supports Pod Identity in recent releases."),
    (
        "ebs-csi-controller-sa",
        "AWS EBS CSI driver supports Pod Identity in recent releases.",
    ),
    ("efs-csi-*", "AWS EFS CSI driver SAs — verify Pod Identity support per version."),
    ("external-secrets", "external-secrets controller supports Pod Identity in recent versions."),
)


def operator_hint(sa_name: str) -> str | None:
    """Return a hint string if the SA matches a known operator, else None."""
    for pattern, hint in OPERATOR_SAS:
        if fnmatchcase(sa_name, pattern):
            return hint
    return None


def is_operator_sa(sa_name: str) -> bool:
    return operator_hint(sa_name) is not None
