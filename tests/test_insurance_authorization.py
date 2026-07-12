from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from proof_agent.contracts import InstitutionAuthorizationContext


def test_institution_authorization_defaults_public_only_and_is_exported() -> None:
    context = InstitutionAuthorizationContext()

    assert context.public_only is True
    assert context.institutions == ()
    assert hash(context) == hash(InstitutionAuthorizationContext())


def test_institution_authorization_canonicalizes_scope_and_derives_non_public() -> None:
    first = InstitutionAuthorizationContext(
        institutions=(" branch-2 ", "branch-1", "branch-2"),
        regions=("east", "north"),
    )
    second = InstitutionAuthorizationContext(
        regions=("north", "east", "north"),
        institutions=("branch-1", "branch-2"),
    )

    assert first == second
    assert first.public_only is False
    assert first.institutions == ("branch-1", "branch-2")
    assert hash(first) == hash(second)


@pytest.mark.parametrize(
    "payload",
    [
        {"public_only": True, "institutions": ["branch-1"]},
        {"public_only": False},
        {"institutions": [" "]},
        {"regions": [1]},
        {"channels": "agency"},
        {"public_only": 0, "roles": ["specialist"]},
        {"public_only": "false", "roles": ["specialist"]},
        {"access_token": "secret"},
        {"raw_credentials": ["secret"]},
    ],
)
def test_institution_authorization_rejects_invalid_python_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InstitutionAuthorizationContext.model_validate(payload)


def test_institution_authorization_json_boundary_is_strict_and_immutable() -> None:
    context = InstitutionAuthorizationContext.model_validate_json(
        json.dumps(
            {
                "roles": [" reviewer ", "reviewer", "specialist"],
                "business_lines": ["claims"],
                "public_only": False,
            }
        )
    )

    assert context.roles == ("reviewer", "specialist")
    with pytest.raises(ValidationError):
        context.public_only = True  # type: ignore[misc]

    with pytest.raises(ValidationError):
        InstitutionAuthorizationContext.model_validate_json(
            '{"roles":["reviewer"],"public_only":"false"}'
        )


def test_trace_safe_summary_contains_only_canonical_scope_and_counts() -> None:
    context = InstitutionAuthorizationContext(roles=("specialist",), regions=("east",))

    summary = context.trace_safe_summary()

    assert summary["public_only"] is False
    assert summary["roles"] == {"values": ["specialist"], "count": 1}
    assert set(summary) == {
        "public_only",
        "institutions",
        "regions",
        "channels",
        "roles",
        "business_lines",
    }
