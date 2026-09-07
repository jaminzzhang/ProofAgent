"""Bounded JSON Schema validation with no external reference retrieval."""
from collections.abc import Mapping
import json
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError, ValidationError  # type: ignore[import-untyped]
from referencing import Registry
from referencing.exceptions import Unresolvable

from proof_agent.errors import ProofAgentError


def _plain(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    if budget is None:
        budget = [20000]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise ValueError('JSON boundary exceeded')
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('JSON object keys must be strings')
        return {key: _plain(item, depth=depth + 1, budget=budget) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth=depth + 1, budget=budget) for item in value]
    return value


def validate_tool_schema(schema: Mapping[str, Any], value: Any, *, label: str) -> None:
    try:
        plain_schema = _plain(schema)
        plain_value = _plain(value)
        if len(json.dumps(plain_schema, allow_nan=False)) > 65536 or len(json.dumps(plain_value, allow_nan=False)) > 1048576:
            raise ValueError('JSON boundary exceeded')
        dialect = plain_schema.get('$schema')
        if dialect is not None and dialect != 'https://json-schema.org/draft/2020-12/schema':
            raise ValueError('unsupported schema dialect')
        Draft202012Validator.check_schema(plain_schema)
        Draft202012Validator(plain_schema, registry=Registry()).validate(plain_value)
    except (ValueError, TypeError, SchemaError, ValidationError, RecursionError, Unresolvable):
        raise ProofAgentError('PA_TOOL_001' if label == 'input_schema' else 'PA_TOOL_SOURCE_002',
            f'Tool {label} validation failed.',
            'Use bounded JSON matching the published schema with local references only.') from None
