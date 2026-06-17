from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel, ValidationError


ContractT = TypeVar("ContractT", bound=BaseModel)

MAX_MODEL_OUTPUT_CHARS = 20_000
MAX_JSON_DEPTH = 20
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ModelOutputNormalizationError(ValueError):
    def __init__(
        self,
        *,
        role: str,
        error_code: str,
        message: str,
        raw_content_length: int,
        contract_name: str | None = None,
        violation_codes: Iterable[str] = (),
        field_paths: Iterable[str] = (),
        violation_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.error_code = error_code
        self.raw_content_length = raw_content_length
        self.contract_name = contract_name
        self.violation_codes = tuple(_bounded_safe_text(item) for item in violation_codes)[:20]
        self.field_paths = tuple(_bounded_safe_text(item) for item in field_paths)[:20]
        self.violation_count = max(0, int(violation_count))


def parse_model_contract(
    content: str,
    contract_type: type[ContractT],
    role: str,
) -> ContractT:
    if len(content) > MAX_MODEL_OUTPUT_CHARS:
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_too_large",
            message="Model output was too large to normalize.",
            raw_content_length=len(content),
        )
    raw = _extract_single_json_object(content, role=role)
    _assert_json_depth(raw, role=role, raw_content_length=len(content))
    try:
        return contract_type.model_validate(raw)
    except ValidationError as exc:
        field_paths, violation_codes = _validation_error_diagnostics(exc)
        raise ModelOutputNormalizationError(
            role=role,
            error_code="model_output_contract_validation_failed",
            message=f"Model output did not match {contract_type.__name__}.",
            raw_content_length=len(content),
            contract_name=contract_type.__name__,
            violation_codes=violation_codes,
            field_paths=field_paths,
            violation_count=len(exc.errors()),
        ) from exc


def _extract_single_json_object(content: str, *, role: str) -> dict[str, object]:
    stripped = content.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        pass
    except RecursionError as exc:
        raise _too_deep_error(role=role, raw_content_length=len(content)) from exc
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
        except RecursionError as exc:
            raise _too_deep_error(role=role, raw_content_length=len(content)) from exc
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


def _assert_json_depth(
    value: object,
    *,
    role: str,
    raw_content_length: int,
) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise _too_deep_error(role=role, raw_content_length=raw_content_length)
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _too_deep_error(
    *,
    role: str,
    raw_content_length: int,
) -> ModelOutputNormalizationError:
    return ModelOutputNormalizationError(
        role=role,
        error_code="model_output_too_deep",
        message="Model output JSON nesting exceeded the safe depth limit.",
        raw_content_length=raw_content_length,
    )


def _validation_error_diagnostics(exc: ValidationError) -> tuple[tuple[str, ...], tuple[str, ...]]:
    field_paths: list[str] = []
    violation_codes: list[str] = []
    for error in exc.errors():
        path = _field_path(error.get("loc", ()))
        if path:
            field_paths.append(path)
        code = _safe_violation_code(str(error.get("type") or "contract_validation_failed"))
        violation_codes.append(code)
    return tuple(dict.fromkeys(field_paths))[:20], tuple(dict.fromkeys(violation_codes))[:20]


def _field_path(loc: object) -> str:
    if not isinstance(loc, tuple | list):
        return ""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[]"
            else:
                parts.append("[]")
        else:
            parts.append(_safe_violation_code(str(item)))
    return ".".join(part for part in parts if part)[:160]


def _safe_violation_code(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return (cleaned or "contract_validation_failed")[:120]


def _bounded_safe_text(value: object) -> str:
    return _safe_violation_code(str(value))
