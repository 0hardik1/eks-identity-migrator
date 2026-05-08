"""Table-driven trust-policy classifier (spec §7.2).

Each rule is a pure predicate over (ParsedPolicy, MappingContext). The
classifier runs every rule, collects findings, and computes a terminal
classification: max(red > yellow > gray > green).

Strategy-dependent escalation (e.g., multi-cluster role reuse becomes red
for replace) is handled by the plan generator, not here — keeping the
classifier strategy-agnostic makes audit output deterministic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from eks_identity_migrator.policy.parser import ParsedPolicy
from eks_identity_migrator.policy.translator import POD_IDENTITY_SERVICE
from eks_identity_migrator.risk.codes import FindingCode
from eks_identity_migrator.risk.context import MappingContext
from eks_identity_migrator.risk.operators import operator_hint
from eks_identity_migrator.types.inventory import (
    FindingModel,
    RiskClassification,
    Severity,
)

# Pod Identity session-name limit (IAM session names are limited to 64 chars).
POD_IDENTITY_SESSION_NAME_MAX = 64

Predicate = Callable[[ParsedPolicy, MappingContext], bool]


@dataclass(frozen=True)
class Rule:
    code: FindingCode
    severity: Severity
    color: RiskClassification | None  # None = informational, no color contribution
    message: str
    hint: str | None
    predicate: Predicate


# ---- predicate helpers ----------------------------------------------------


def _has_other_oidc_issuer(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    issuers = parsed.federated_oidc_issuers()
    if not issuers:
        return False
    target = ctx.normalized_issuer
    return any(issuer != target for issuer in issuers)


def _no_oidc_issuer_matches_cluster(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    issuers = parsed.federated_oidc_issuers()
    if not issuers:
        return False
    target = ctx.normalized_issuer
    return all(issuer != target for issuer in issuers)


def _has_cross_account_principal(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    """Federated principal in a different account than the cluster, OR Principal.AWS present."""
    if parsed.has_principal_aws():
        return True
    cluster_account = ctx.cluster_account
    for fed in parsed.federated_principals:
        # arn:aws:iam::<account>:oidc-provider/<issuer>
        parts = fed.split(":")
        if len(parts) >= 5 and parts[4] and parts[4] != cluster_account:
            return True
    return bool(ctx.role_account and ctx.role_account != cluster_account)


def _has_wildcard_sub(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    issuer = ctx.normalized_issuer
    sub_key = f"{issuer}:sub"
    for stmt in parsed.statements:
        sl = stmt.condition_value("StringLike", sub_key)
        if sl is None:
            continue
        for v in sl:
            if "*" in v or "?" in v:
                return True
    return False


def _has_multi_sub_forall(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    issuer = ctx.normalized_issuer
    sub_key = f"{issuer}:sub"
    for stmt in parsed.statements:
        v = stmt.condition_value("ForAllValues:StringEquals", sub_key)
        if v and len(v) > 1:
            return True
    return False


def _has_custom_aud_claim(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    issuer = ctx.normalized_issuer
    aud_key = f"{issuer}:aud"
    for stmt in parsed.statements:
        for op in ("StringEquals", "StringEqualsIgnoreCase"):
            vals = stmt.condition_value(op, aud_key)
            if vals is None:
                continue
            for v in vals:
                if v != "sts.amazonaws.com":
                    return True
    return False


def _is_operator_sa(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    return operator_hint(ctx.sa_name) is not None


def _has_mixed_ec2_principal(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    has_federated = any(s.principal_federated for s in parsed.statements)
    return has_federated and parsed.has_service_principal("ec2.amazonaws.com")


def _has_tagsession_already(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    return "sts:TagSession" in parsed.all_actions


def _is_default_sa_annotated(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    return ctx.sa_name == "default"


def _is_multi_statement_oidc(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    """Two or more statements each grant OIDC IRSA (additional cluster, additional SA, etc.)."""
    irsa_stmt_count = 0
    for s in parsed.statements:
        if s.principal_federated and "sts:AssumeRoleWithWebIdentity" in s.actions:
            irsa_stmt_count += 1
    return irsa_stmt_count >= 2


def _session_name_would_truncate(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    # Pod Identity assumed-role session name format used by AWS includes the
    # cluster, namespace, and SA — exact length varies, but a conservative
    # heuristic is that the joined string already exceeds the IAM session-name
    # limit of 64 characters.
    candidate = f"{ctx.cluster_name}-{ctx.sa_namespace}-{ctx.sa_name}"
    return len(candidate) > POD_IDENTITY_SESSION_NAME_MAX


_DEFAULT_IRSA_TOKEN_PATH = "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"  # noqa: S105


def _has_custom_token_file_path(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    """Detect explicit non-default `AWS_WEB_IDENTITY_TOKEN_FILE` in pod env (gotcha 12)."""
    for env in ctx.pod_envs:
        if (
            env.name == "AWS_WEB_IDENTITY_TOKEN_FILE"
            and env.value
            and env.value != _DEFAULT_IRSA_TOKEN_PATH
        ):
            return True
    return False


def _has_pod_identity_already(parsed: ParsedPolicy, ctx: MappingContext) -> bool:
    return parsed.has_service_principal(POD_IDENTITY_SERVICE)


# ---- rule table -----------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        code=FindingCode.CROSS_ACCOUNT_TRUST,
        severity="error",
        color=RiskClassification.RED,
        message="Trust policy references a principal in a different account.",
        hint=(
            "Pod Identity Associations are same-account only. Create an "
            "intermediate role in the cluster's account that assumes the target role; "
            "migrate the intermediate role."
        ),
        predicate=_has_cross_account_principal,
    ),
    Rule(
        code=FindingCode.CUSTOM_AUD_CLAIM,
        severity="error",
        color=RiskClassification.RED,
        message="Trust policy uses a non-default OIDC `aud` claim.",
        hint=(
            "Pod Identity does not support custom audience claims. Re-architect the "
            "auth flow if this audience is required."
        ),
        predicate=_has_custom_aud_claim,
    ),
    Rule(
        code=FindingCode.FOREIGN_OIDC_ISSUER,
        severity="error",
        color=RiskClassification.RED,
        message="Trust policy's OIDC issuer does not match this cluster's issuer.",
        hint="The role isn't trusted by this cluster's OIDC provider; nothing to migrate here.",
        predicate=_no_oidc_issuer_matches_cluster,
    ),
    Rule(
        code=FindingCode.ROLE_USED_BY_MULTIPLE_CLUSTERS,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Role's trust policy includes statements for other OIDC issuers.",
        hint=(
            "Append-strategy migration is safe; replace would remove other clusters' "
            "trust. Coordinate fleet rollout before using --strategy replace."
        ),
        predicate=_has_other_oidc_issuer,
    ),
    Rule(
        code=FindingCode.MIXED_PRINCIPAL_EC2,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Role is trusted by both EC2 instances and IRSA.",
        hint=(
            "Append keeps the EC2 trust intact; replace will be applied carefully "
            "(only OIDC statements are stripped)."
        ),
        predicate=_has_mixed_ec2_principal,
    ),
    Rule(
        code=FindingCode.WILDCARD_SUB,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Trust policy `sub` condition uses a wildcard via StringLike.",
        hint=(
            "Pod Identity Associations are per-(cluster, ns, sa). The migration emits one "
            "association per SA *currently* using this role; new SAs added to the namespace "
            "will not auto-inherit access."
        ),
        predicate=_has_wildcard_sub,
    ),
    Rule(
        code=FindingCode.MULTI_SUB_FORALL,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Trust policy lists multiple SAs in a ForAllValues:StringEquals condition.",
        hint="Migration emits one Pod Identity Association per SA listed.",
        predicate=_has_multi_sub_forall,
    ),
    Rule(
        code=FindingCode.MULTI_STATEMENT_OIDC,
        severity="info",
        color=RiskClassification.YELLOW,
        message="Trust policy contains multiple OIDC IRSA statements.",
        hint="Each non-target statement is preserved by --strategy append.",
        predicate=_is_multi_statement_oidc,
    ),
    Rule(
        code=FindingCode.OPERATOR_MANAGED,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="ServiceAccount matches a well-known cluster operator.",
        hint=(
            "Operators (ALB controller, Karpenter, CSI drivers, etc.) often have their own "
            "Pod Identity migration story. Check the operator's docs before cleanup."
        ),
        predicate=_is_operator_sa,
    ),
    Rule(
        code=FindingCode.DEFAULT_SA_ANNOTATED,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="The namespace's `default` ServiceAccount carries the IRSA annotation.",
        hint=(
            "Every pod with empty serviceAccountName picks this up. Confirm scope before migrating."
        ),
        predicate=_is_default_sa_annotated,
    ),
    Rule(
        code=FindingCode.SESSION_NAME_TOO_LONG,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Generated Pod Identity session name would exceed IAM's 64-character limit.",
        hint="Rename the SA or the namespace to shorten the session name.",
        predicate=_session_name_would_truncate,
    ),
    Rule(
        code=FindingCode.CUSTOM_TOKEN_FILE_PATH,
        severity="warn",
        color=RiskClassification.YELLOW,
        message="Pod sets AWS_WEB_IDENTITY_TOKEN_FILE explicitly to a non-default path.",
        hint=(
            "App may read the OIDC token directly. Verify after migration; "
            "this is not covered by Pod Identity."
        ),
        predicate=_has_custom_token_file_path,
    ),
    Rule(
        code=FindingCode.STS_TAGSESSION_PRESENT,
        severity="info",
        color=None,
        message="Trust policy already lists sts:TagSession.",
        hint=None,
        predicate=_has_tagsession_already,
    ),
)


def _terminal_color(findings: Iterable[FindingModel]) -> RiskClassification:
    """Apply the precedence: red > yellow > gray > green."""
    seen = {f.code for f in findings if f.code != FindingCode.STS_TAGSESSION_PRESENT.value}
    code_to_color = {r.code.value: r.color for r in RULES if r.color is not None}
    has_red = any(code_to_color.get(c) == RiskClassification.RED for c in seen)
    if has_red:
        return RiskClassification.RED
    has_yellow = any(code_to_color.get(c) == RiskClassification.YELLOW for c in seen)
    if has_yellow:
        return RiskClassification.YELLOW
    has_gray = any(code_to_color.get(c) == RiskClassification.GRAY for c in seen)
    if has_gray:
        return RiskClassification.GRAY
    return RiskClassification.GREEN


def classify(
    parsed: ParsedPolicy | None,
    ctx: MappingContext,
    *,
    extra_findings: Iterable[FindingModel] = (),
) -> tuple[RiskClassification, list[FindingModel]]:
    """Classify a mapping. `parsed=None` indicates a parse failure → gray."""
    findings: list[FindingModel] = list(extra_findings)

    if parsed is None:
        findings.append(
            FindingModel(
                code=FindingCode.POLICY_PARSE_ERROR.value,
                severity="error",
                message="Trust policy could not be parsed.",
                hint="Inspect the role's trust policy JSON in the IAM console.",
            )
        )
        return RiskClassification.GRAY, findings

    if ctx.permission_boundary:
        findings.append(
            FindingModel(
                code=FindingCode.PERMISSION_BOUNDARY.value,
                severity="info",
                message=f"Role has permission boundary: {ctx.permission_boundary}",
                hint="Permission boundaries are unaffected by trust-policy changes.",
            )
        )

    if ctx.used_by_pods_count == 0:
        findings.append(
            FindingModel(
                code=FindingCode.STALE_ANNOTATION.value,
                severity="warn",
                message="ServiceAccount carries the IRSA annotation but no pod uses it.",
                hint="Remove the annotation if the SA is unused.",
            )
        )
        return RiskClassification.GRAY, findings

    for rule in RULES:
        try:
            matched = rule.predicate(parsed, ctx)
        except Exception as exc:  # defensive: a buggy rule shouldn't kill audit
            findings.append(
                FindingModel(
                    code=rule.code.value,
                    severity="warn",
                    message=(
                        f"Rule {rule.code.value} raised an exception during classification: {exc}"
                    ),
                )
            )
            continue
        if matched:
            findings.append(
                FindingModel(
                    code=rule.code.value,
                    severity=rule.severity,
                    message=rule.message,
                    hint=rule.hint,
                )
            )

    return _terminal_color(findings), findings
