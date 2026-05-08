"""Shared base model: camelCase aliasing, populate-by-name, extra=forbid.

Subclassing this gives every public type the same JSON/YAML serialization
contract: `model_dump_json(by_alias=True)` emits camelCase keys (matching the
spec §5/§9 examples), while `populate_by_name=True` lets internal code
construct instances using snake_case field names.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for all public data types in this project."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
        ser_json_timedelta="iso8601",
        validate_assignment=False,
    )
