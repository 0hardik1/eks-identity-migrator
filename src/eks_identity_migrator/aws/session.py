"""boto3 Session construction — central retry config (gotcha 16)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from boto3.session import Session


def make_session(*, region: str | None = None, profile: str | None = None) -> Session:
    """Construct a boto3 Session with the project's standard config."""
    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    if profile:
        kwargs["profile_name"] = profile
    return boto3.session.Session(**kwargs)


def make_config() -> Config:
    """Standard botocore Config: adaptive retry, max_attempts >= 5 (spec gotcha 16)."""
    return Config(
        retries={"max_attempts": 5, "mode": "adaptive"},
        user_agent_extra="eks-identity-migrator/0.1",
    )
