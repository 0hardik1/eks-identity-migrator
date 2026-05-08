"""STS client Protocol + boto3 implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from eks_identity_migrator.aws.errors import wrap_client_error
from eks_identity_migrator.aws.session import make_config

if TYPE_CHECKING:
    from boto3.session import Session


@dataclass(frozen=True)
class CallerIdentity:
    account: str
    arn: str
    user_id: str


@runtime_checkable
class StsClient(Protocol):
    def get_caller_identity(self) -> CallerIdentity: ...


class BotoStsClient:
    def __init__(self, session: Session, *, endpoint_url: str | None = None) -> None:
        self._client = session.client("sts", config=make_config(), endpoint_url=endpoint_url)

    def get_caller_identity(self) -> CallerIdentity:
        from botocore.exceptions import ClientError

        try:
            r = self._client.get_caller_identity()
        except ClientError as exc:
            raise wrap_client_error("sts:GetCallerIdentity", exc) from exc
        return CallerIdentity(
            account=str(r.get("Account", "")),
            arn=str(r.get("Arn", "")),
            user_id=str(r.get("UserId", "")),
        )
