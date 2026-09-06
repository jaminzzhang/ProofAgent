"""Typed source records: data only, never evidence-admission authority."""

import json
import re
from datetime import date, datetime
from typing import Any
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from proof_agent.contracts._base import StrictFrozenModel


Name = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^\S(?:.*\S)?$")]
Text = Annotated[StrictStr, Field(max_length=4096)]


class StructuredEvidenceField(StrictFrozenModel):
    field: Name
    value_type: Literal["string", "integer", "decimal", "boolean", "date", "datetime", "null"]
    value: Text | StrictInt | StrictBool | None
    unit: Name | None = None

    @model_validator(mode="after")
    def exact_type(self) -> Self:
        value = self.value
        kind = self.value_type
        valid = False
        if kind == "string":
            valid = type(value) is str
        elif kind == "integer":
            valid = type(value) is int and len(str(abs(value))) <= 128
        elif kind == "decimal":
            valid = (
                type(value) is str
                and len(value) <= 128
                and re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value) is not None
            )
        elif kind == "boolean":
            valid = type(value) is bool
        elif kind == "null":
            valid = value is None
        elif kind == "date" and isinstance(value, str):
            valid = date.fromisoformat(value).isoformat() == value
        elif kind == "datetime" and isinstance(value, str):
            valid = "T" in value and datetime.fromisoformat(value).utcoffset() is not None
        if not valid:
            raise ValueError("Structured field does not match its declared bounded type")
        return self


class StructuredEvidenceRecord(StrictFrozenModel):
    schema_version: Literal["proofagent-structured-evidence.v1"] = (
        "proofagent-structured-evidence.v1"
    )
    record_id: Name
    fields: tuple[StructuredEvidenceField, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        if len({item.field for item in self.fields}) != len(self.fields):
            raise ValueError("Structured record fields must be unique")
        return self


def parse_structured_evidence(content: str) -> StructuredEvidenceRecord:
    if len(content) > 100_000:
        raise ValueError("Structured record content limit exceeded")
    data = json.loads(content, object_pairs_hook=_unique_object)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != "proofagent-structured-evidence.v1"
    ):
        raise ValueError("Structured record must declare its supported schema version")
    return StructuredEvidenceRecord.model_validate(data)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Structured record has duplicate keys")
        result[key] = value
    return result
