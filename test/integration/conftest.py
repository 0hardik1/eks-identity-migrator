"""Integration test harness — kind + LocalStack IAM + fake EKS at the boundary.

Per spec §10, LocalStack EKS Pod Identity coverage is incomplete on the
community edition. We split: real LocalStack IAM (so the trust-policy
serialisation contract is exercised against the real IAM API), fake EKS at
our Protocol boundary.

These tests are gated behind `pytest.mark.integration` and require:
- Docker daemon
- `kind` v0.24+
- `kubectl` v1.31+
- network to pull `localstack/localstack:3.8`

They self-skip with a clear message when any prerequisite is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from typing import Any

import pytest


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker_alive() -> bool:
    if not _has("docker"):
        return False
    proc = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=10, check=False
    )
    return proc.returncode == 0


REQUIRED_BINARIES = ("kind", "kubectl", "docker")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    missing = [b for b in REQUIRED_BINARIES if not _has(b)]
    if missing or not _docker_alive():
        skip_reason = (
            f"integration tests need docker + {REQUIRED_BINARIES}; "
            f"missing: {missing or 'docker daemon not running'}"
        )
        skip_marker = pytest.mark.skip(reason=skip_reason)
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def kind_cluster() -> Iterator[str]:
    """Create a kind cluster for the test session, return its kubeconfig path."""
    name = "eks-id-migrator-it"
    subprocess.run(["kind", "create", "cluster", "--name", name], check=True)
    try:
        proc = subprocess.run(
            ["kind", "get", "kubeconfig", "--name", name],
            check=True,
            capture_output=True,
            text=True,
        )
        kubeconfig = "/tmp/kind-eks-id-migrator-it-kubeconfig"
        with open(kubeconfig, "w") as f:
            f.write(proc.stdout)
        yield kubeconfig
    finally:
        subprocess.run(["kind", "delete", "cluster", "--name", name], check=False)


@pytest.fixture(scope="session")
def localstack_iam() -> Iterator[str]:
    """Start LocalStack with IAM + STS, return its endpoint URL."""
    name = "eks-id-migrator-localstack"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "4566:4566",
            "-e",
            "SERVICES=iam,sts",
            "localstack/localstack:3.8",
        ],
        check=True,
        capture_output=True,
    )
    endpoint = "http://localhost:4566"
    # Wait up to 60s for readiness.
    deadline = time.time() + 60
    while time.time() < deadline:
        proc = subprocess.run(
            ["curl", "-fsS", f"{endpoint}/_localstack/health"],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and b'"iam": "available"' in proc.stdout:
            break
        time.sleep(2)
    else:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        pytest.fail("localstack failed to come up within 60s")

    try:
        yield endpoint
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


@pytest.fixture
def boto_session_localstack(localstack_iam: str) -> Any:
    """boto3 Session configured to talk to LocalStack."""
    import boto3

    return boto3.session.Session(
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
