"""IAM client Protocol + boto3 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from eks_identity_migrator.aws.errors import wrap_client_error
from eks_identity_migrator.aws.session import make_config

if TYPE_CHECKING:
    from boto3.session import Session


@dataclass(frozen=True)
class IamRole:
    arn: str
    name: str
    trust_policy: dict[str, Any]
    permission_boundary: str | None = None


@runtime_checkable
class IamClient(Protocol):
    def get_role(self, role_arn: str) -> IamRole | None:
        """Return the role, or None if it does not exist."""

    def update_assume_role_policy(
        self, role_name: str, policy_document: dict[str, Any]
    ) -> None: ...


def role_name_from_arn(arn: str) -> str:
    """`arn:aws:iam::<acct>:role/<name>` → `<name>` (handles paths like `role/path/Name`)."""
    if ":role/" not in arn:
        raise ValueError(f"not an IAM role ARN: {arn}")
    return arn.split(":role/", 1)[1]


class BotoIamClient:
    """boto3-backed IamClient. Wraps ClientErrors with action context."""

    def __init__(self, session: Session, *, endpoint_url: str | None = None) -> None:
        self._client = session.client("iam", config=make_config(), endpoint_url=endpoint_url)

    def get_role(self, role_arn: str) -> IamRole | None:
        from botocore.exceptions import ClientError

        try:
            name = role_name_from_arn(role_arn)
            resp = self._client.get_role(RoleName=name)
        except ClientError as exc:
            err = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
            if err.get("Code") in {"NoSuchEntity", "NoSuchEntityException"}:
                return None
            raise wrap_client_error("iam:GetRole", exc, role_arn=role_arn) from exc
        except Exception as exc:
            raise wrap_client_error("iam:GetRole", exc, role_arn=role_arn) from exc

        role = resp["Role"]
        # botocore URL-decodes the trust policy document automatically.
        trust_raw: Any = role.get("AssumeRolePolicyDocument", {})
        trust: dict[str, Any] = trust_raw if isinstance(trust_raw, dict) else {}
        boundary_obj = role.get("PermissionsBoundary") or {}
        boundary = (
            boundary_obj.get("PermissionsBoundaryArn") if isinstance(boundary_obj, dict) else None
        )
        return IamRole(
            arn=role.get("Arn", role_arn),
            name=role.get("RoleName", name),
            trust_policy=trust,
            permission_boundary=boundary,
        )

    def update_assume_role_policy(self, role_name: str, policy_document: dict[str, Any]) -> None:
        import json

        from botocore.exceptions import ClientError

        try:
            self._client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=json.dumps(policy_document, sort_keys=True),
            )
        except ClientError as exc:
            raise wrap_client_error("iam:UpdateAssumeRolePolicy", exc, role_arn=role_name) from exc
        except Exception as exc:
            raise wrap_client_error("iam:UpdateAssumeRolePolicy", exc, role_arn=role_name) from exc
