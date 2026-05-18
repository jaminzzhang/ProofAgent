from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError


ContractT = TypeVar("ContractT", bound=BaseModel)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ModelOutputNormalizationError(ValueError):
    def __init__(
        self,
        *,
        role: str,
        error_code: str,
        message: str,
        raw_content_length: int,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.error_code = error_code
        self.raw_content_length = raw_content_length


def parse_model_contract(
    content: str,
    contract_type: type[ContractT],
    role: str,
) -> ContractT:
    raw = _extract_single_json_object(content, role=role)
    try:
        return contract_type.model_validate(raw)
    except ValidationError as exc:
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_contract_validation_failed",
            message=f"Model output did not match {contract_type.__name__}.",
            raw_content_length=len(content),
        ) from exc


def _extract_single_json_object(content: str, *, role: str) -> dict[str, object]:
    stripped = content.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(value, dict):
            return value
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_json_not_object",
            message="Model output JSON must be a single object.",
            raw_content_length=len(content),
        )

    fenced = _FENCED_JSON_RE.findall(content)
    if len(fenced) > 1:
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_json_parse_failed",
            message="Model output did not contain a valid JSON object.",
            raw_content_length=len(content),
        )
    if len(fenced) == 1:
        try:
            value = json.loads(fenced[0])
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                return value
            raise ModelOutputNormalizationError(
                role=role,
                error_code="model_output_json_not_object",
                message="Model output JSON must be a single object.",
                raw_content_length=len(content),
            )
    raise ModelOutputNormalizationError(
        role=role,
        error_code="model_output_json_parse_failed",
        message="Model output did not contain a valid JSON object.",
        raw_content_length=len(content),
    )
