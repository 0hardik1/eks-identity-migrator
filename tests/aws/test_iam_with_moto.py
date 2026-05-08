"""Smoke-test the boto IamClient against moto."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from eks_identity_migrator.aws.errors import AwsOperationError
from eks_identity_migrator.aws.iam import BotoIamClient, role_name_from_arn


@pytest.fixture
def session() -> boto3.session.Session:
    return boto3.session.Session(
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def test_role_name_from_arn_simple() -> None:
    assert role_name_from_arn("arn:aws:iam::123:role/Frontend") == "Frontend"


def test_role_name_from_arn_with_path() -> None:
    assert role_name_from_arn("arn:aws:iam::123:role/path/Sub") == "path/Sub"


def test_role_name_from_arn_invalid() -> None:
    with pytest.raises(ValueError):
        role_name_from_arn("arn:aws:iam::123:user/Bob")


@mock_aws
def test_get_role_returns_trust_policy(session: boto3.session.Session) -> None:
    iam = session.client("iam")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    resp = iam.create_role(RoleName="Test", AssumeRolePolicyDocument=json.dumps(trust))
    arn = resp["Role"]["Arn"]
    client = BotoIamClient(session)
    role = client.get_role(arn)
    assert role is not None
    assert role.name == "Test"
    assert role.trust_policy["Statement"][0]["Principal"]["Service"] == "ec2.amazonaws.com"


@mock_aws
def test_get_role_returns_none_for_missing(session: boto3.session.Session) -> None:
    client = BotoIamClient(session)
    arn = "arn:aws:iam::123456789012:role/DoesNotExist"
    assert client.get_role(arn) is None


@mock_aws
def test_update_assume_role_policy_round_trip(session: boto3.session.Session) -> None:
    iam = session.client("iam")
    initial = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    iam.create_role(RoleName="Test", AssumeRolePolicyDocument=json.dumps(initial))
    client = BotoIamClient(session)

    new_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "pods.eks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    client.update_assume_role_policy("Test", new_policy)

    fetched = client.get_role("arn:aws:iam::123456789012:role/Test")
    assert fetched is not None
    assert fetched.trust_policy["Statement"][0]["Principal"]["Service"] == "pods.eks.amazonaws.com"


@mock_aws
def test_aws_operation_error_carries_action(session: boto3.session.Session) -> None:
    client = BotoIamClient(session)
    with pytest.raises(AwsOperationError) as excinfo:
        client.update_assume_role_policy("DoesNotExist", {"Version": "2012-10-17", "Statement": []})
    assert "iam:UpdateAssumeRolePolicy" in str(excinfo.value)
