import json
import shutil
from pathlib import Path

import pytest

from proof_agent.errors import ProofAgentError
from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_model_trace_events_do_not_store_raw_prompts_or_outputs(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _read_events(result.trace_path)
    model_request = next(event for event in events if event["event_type"] == "model_request")
    model_response = next(event for event in events if event["event_type"] == "model_response")

    assert set(model_request["payload"]) == {
        "cost_class",
        "estimated_tokens",
        "message_count",
        "model",
        "prompt_length",
        "provider",
        "stream",
        "system_prompt_length",
    }
    assert "content" not in model_response["payload"]
    assert "messages" not in model_request["payload"]
    assert model_response["payload"]["content_length"] > 0


def test_model_error_is_traced_when_provider_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_dir = tmp_path / "enterprise_qa"
    shutil.copytree(Path("examples/enterprise_qa"), example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path
        .read_text(encoding="utf-8")
        .replace("provider: deterministic", "provider: openai_compatible")
        .replace("name: demo", "name: gpt-test"),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProofAgentError):
        run_with_langgraph(
            manifest_path,
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path,
        )

    events = _read_events(tmp_path / "trace.jsonl")
    model_error = next(event for event in events if event["event_type"] == "model_error")
    assert model_error["status"] == "error"
    assert model_error["payload"]["provider"] == "openai_compatible"
    assert model_error["payload"]["error_code"] == "PA_MODEL_003"


def _read_events(trace_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
