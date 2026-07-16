from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from proof_agent.contracts.run_execution import RunRequest


FIXTURES = Path(__file__).parent / "fixtures" / "run_execution_contract" / "v1"


def _load(name: str) -> tuple[RunRequest, ...]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return tuple(RunRequest.model_validate(item) for item in payload["requests"])


def test_candidate_executor_consumes_old_api_v1_without_reinterpretation() -> None:
    requests = _load("old_api_requests.json")
    assert len(requests) == 1
    assert requests[0].contract_version == "proofagent.run-execution.v1"
    assert requests[0].question == "old API request"


def test_old_executor_contract_consumes_candidate_api_v1() -> None:
    requests = _load("candidate_api_requests.json")
    assert len(requests) == 1
    assert requests[0].conversation_id == "019ba001-1111-7000-8000-000000000012"


def test_unknown_or_missing_required_v1_fields_fail_closed() -> None:
    payload = json.loads(
        (FIXTURES / "candidate_api_requests.json").read_text(encoding="utf-8")
    )["requests"][0]
    with pytest.raises(ValidationError):
        RunRequest.model_validate({**payload, "new_required_semantics": True})
    missing = dict(payload)
    del missing["permission_epoch"]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(missing)
