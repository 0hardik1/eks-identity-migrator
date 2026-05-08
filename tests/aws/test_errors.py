"""Wrap-error tests."""

from __future__ import annotations

from botocore.exceptions import ClientError

from eks_identity_migrator.aws.errors import AwsOperationError, wrap_client_error


def test_wrap_client_error_carries_code_and_message() -> None:
    err = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "you may not"}}, "UpdateAssumeRolePolicy"
    )
    wrapped = wrap_client_error("iam:UpdateAssumeRolePolicy", err, role_arn="arn:aws:iam::1:role/x")
    assert wrapped.code == "AccessDenied"
    assert "iam:UpdateAssumeRolePolicy" in str(wrapped)
    assert "arn:aws:iam::1:role/x" in str(wrapped)
    assert "you may not" in str(wrapped)


def test_aws_error_includes_sa_when_set() -> None:
    err = AwsOperationError("eks:CreatePodIdentityAssociation", "boom", sa="ns/foo")
    assert "ns/foo" in str(err)
