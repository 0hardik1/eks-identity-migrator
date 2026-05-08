"""AWS client layer — Protocols + boto3 implementations.

This is the *only* module (besides `k8s/`) allowed to `import boto3`.
Everywhere else takes Protocols by injection.
"""

from eks_identity_migrator.aws.eks import (
    POD_IDENTITY_ADDON_NAME,
    BotoEksClient,
    ClusterInfo,
    EksClient,
    PodIdentityAssociation,
)
from eks_identity_migrator.aws.errors import AwsOperationError, wrap_client_error
from eks_identity_migrator.aws.iam import (
    BotoIamClient,
    IamClient,
    IamRole,
    role_name_from_arn,
)
from eks_identity_migrator.aws.session import make_config, make_session
from eks_identity_migrator.aws.sts import BotoStsClient, CallerIdentity, StsClient

__all__ = [
    "POD_IDENTITY_ADDON_NAME",
    "AwsOperationError",
    "BotoEksClient",
    "BotoIamClient",
    "BotoStsClient",
    "CallerIdentity",
    "ClusterInfo",
    "EksClient",
    "IamClient",
    "IamRole",
    "PodIdentityAssociation",
    "StsClient",
    "make_config",
    "make_session",
    "role_name_from_arn",
    "wrap_client_error",
]
