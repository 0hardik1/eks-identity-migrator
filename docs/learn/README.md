# Learn: EKS workload identity, deeply

This folder is the **why**. The engineering specification — what the tool does
and how it's built — lives in [`docs/SPEC.md`](../SPEC.md).

If you've ever stared at a blob of JSON like

```
"Condition": {
  "StringEquals": {
    "oidc.eks.us-west-2.amazonaws.com/id/EXAMPLE:sub":
      "system:serviceaccount:production:app-frontend"
  }
}
```

and wondered *what is actually happening when a pod calls AWS*, this is for
you. By the end of these three documents you should understand the credential
flow end-to-end for both IRSA and EKS Pod Identity, why each finding code in
[`risk/codes.py`](../../src/eks_identity_migrator/risk/codes.py) exists, and
why migrating is a three-phase operation rather than a one-shot toggle.

## Reading order

1. [`01-oidc-and-irsa.md`](01-oidc-and-irsa.md) — what OIDC is, how EKS turns
   each cluster into an OIDC issuer, how the projected ServiceAccount token
   becomes AWS credentials, and which gotchas this codebase classifies as
   `WILDCARD_SUB`, `CROSS_ACCOUNT_TRUST`, `CUSTOM_AUD_CLAIM`, and friends.

2. [`02-pod-identity.md`](02-pod-identity.md) — the Pod Identity Association
   API, the `eks-pod-identity-agent` daemonset, the new IAM trust shape with
   `pods.eks.amazonaws.com` as a service principal, and the mandatory
   `aws:SourceAccount` / `aws:SourceArn` confused-deputy conditions this
   codebase always emits.

3. [`03-irsa-vs-pod-identity.md`](03-irsa-vs-pod-identity.md) — side-by-side
   comparison, problem-by-problem walk-through of how Pod Identity removes
   IRSA's sharp edges, an honest list of what Pod Identity does **not** solve,
   and the mental model behind the tool's three-phase
   `trust → association → cleanup` migration.

## If you only have five minutes

Skip to the comparison table at the top of
[`03-irsa-vs-pod-identity.md`](03-irsa-vs-pod-identity.md). Come back for the
flow diagrams when something there doesn't make sense.

## How these docs reference the codebase

When a concept maps to something concrete in this repo, the docs cite the
file path inline. Examples:

- Finding-code names (e.g. `CROSS_ACCOUNT_TRUST`) are defined in
  [`risk/codes.py`](../../src/eks_identity_migrator/risk/codes.py); the
  predicates that emit them live in
  [`risk/rules.py`](../../src/eks_identity_migrator/risk/rules.py).
- Real trust-policy JSON examples come from the
  [`testdata/trust-policies/`](../../testdata/trust-policies) and
  [`testdata/translator/`](../../testdata/translator) fixtures — you can
  `cat` any of them to see the exact bytes the parser and translator are
  expected to handle.
- Spec section numbers (e.g. "SPEC §7.3") refer to
  [`docs/SPEC.md`](../SPEC.md).

## External references

Authoritative sources, collected here for skimmability. They're also linked
inline on first use.

### AWS

- [IAM Roles for Service Accounts (EKS user guide)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [EKS Pod Identity (EKS user guide)](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [EKS Pod Identity Agent setup](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-agent-setup.html)
- [How EKS Pod Identity works](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-how-it-works.html)
- [AWS announcement: Amazon EKS Pod Identity (Nov 2023)](https://aws.amazon.com/blogs/aws/amazon-eks-pod-identity-simplifies-iam-permissions-for-applications-on-amazon-eks-clusters/)
- [`sts:AssumeRoleWithWebIdentity` API reference](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html)
- [`sts:AssumeRole` API reference](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html)
- [`sts:TagSession` API reference](https://docs.aws.amazon.com/STS/latest/APIReference/API_TagSession.html)
- [Confused-deputy prevention with `aws:SourceAccount` / `aws:SourceArn`](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html)

### Standards

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)
- [RFC 7517 — JSON Web Key (JWK)](https://www.rfc-editor.org/rfc/rfc7517)
- [RFC 7519 — JSON Web Token (JWT)](https://www.rfc-editor.org/rfc/rfc7519)

### Kubernetes

- [Configure ServiceAccounts for Pods](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)
- [Projected volumes (`serviceAccountToken`)](https://kubernetes.io/docs/concepts/storage/projected-volumes/#serviceaccounttoken)
- [BoundServiceAccountTokenVolume](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/#bound-service-account-token-volume)

### Prior art

- [Datadog MKAT (Managed Kubernetes Auditing Toolkit)](https://github.com/DataDog/managed-kubernetes-auditing-toolkit) — audits IRSA + Pod Identity but does not migrate. Mentioned in [SPEC §1](../SPEC.md).
