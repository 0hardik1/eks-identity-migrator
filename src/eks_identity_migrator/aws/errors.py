"""Wrap botocore exceptions with action context (spec §15)."""

from __future__ import annotations

from typing import Any


class AwsOperationError(Exception):
    """Wraps a botocore ClientError or other AWS-side failure with action + context."""

    def __init__(
        self,
        action: str,
        message: str,
        *,
        sa: str | None = None,
        role_arn: str | None = None,
        original: Exception | None = None,
        code: str | None = None,
    ) -> None:
        self.action = action
        self.sa = sa
        self.role_arn = role_arn
        self.original = original
        self.code = code
        prefix = f"AWS {action}"
        if sa:
            prefix += f" for SA {sa}"
        if role_arn:
            prefix += f" (role {role_arn})"
        super().__init__(f"{prefix}: {message}")


def wrap_client_error(
    action: str,
    exc: Exception,
    *,
    sa: str | None = None,
    role_arn: str | None = None,
) -> AwsOperationError:
    """Best-effort conversion of a botocore ClientError into an AwsOperationError."""
    code: str | None = None
    message = str(exc)
    response: dict[str, Any] | None = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error", {})
        if isinstance(err, dict):
            code = err.get("Code")
            message = err.get("Message", message)
    return AwsOperationError(
        action=action,
        message=message,
        sa=sa,
        role_arn=role_arn,
        original=exc,
        code=code,
    )
