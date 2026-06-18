import json
import shutil
from pathlib import Path

import pytest
import yaml

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import EnvironmentModelCredentialReference, ModelCallRole
from proof_agent.errors import ProofAgentError
from proof_agent.runtime.langgraph_runner import run_with_langgraph
from proof_agent.contracts import TraceEventType


def test_trace_event_types_include_react_review_events() -> None:
    values = {event.value for event in TraceEventType}
    assert "workflow_stage_context_applied" in values
    assert "intent_resolution" in values
    assert "retrieval_query_set" in values
    assert "reasoning_summary" in values
    assert "action_proposal" in values
    assert "review_requested" in values
    assert "review_decision" in values
    assert "review_error" in values
    assert "review_overridden" in values
    assert "clarification_requested" in values


def test_model_call_roles_include_intent_resolution() -> None:
    assert ModelCallRole.INTENT_RESOLUTION.value == "intent_resolution"


def test_model_trace_events_do_not_store_raw_prompts_or_outputs(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
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
        "response_format",
        "role",
        "stream",
        "system_prompt_length",
    }
    assert "content" not in model_response["payload"]
    assert "messages" not in model_request["payload"]
    assert model_response["payload"]["content_length"] > 0


def test_final_answer_model_trace_includes_role_and_response_format(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _read_events(result.trace_path)
    model_request = next(event for event in events if event["event_type"] == "model_request")

    assert model_request["payload"]["role"] == "final_answer"
    assert model_request["payload"]["response_format"] == "text"


def test_shared_model_connection_resolution_trace_is_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_MODEL_KEY", "raw-secret-value")
    example_dir = tmp_path / "enterprise_qa"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa"), example_dir)
    manifest_path = example_dir / "agent.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["model"] = {
        "model_source": "shared",
        "connection_id": "model_demo_shared",
        "params": {"temperature": 0},
    }
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_model_connection(
        connection_id="model_demo_shared",
        display_name="Demo Shared",
        provider="deterministic",
        model_identifier="demo",
        base_url="https://models.example.test/v1",
        credential_ref=EnvironmentModelCredentialReference(name="DEMO_MODEL_KEY"),
        actor="operator",
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
        configuration_store=store,
    )

    events = _read_events(result.trace_path)
    resolution = next(
        event for event in events if event["event_type"] == "model_connection_resolution"
    )
    assert resolution["payload"]["connection_id"] == "model_demo_shared"
    assert resolution["payload"]["provider"] == "deterministic"
    assert resolution["payload"]["base_url_host"] == "models.example.test"
    assert resolution["payload"]["credential_ref"] == {
        "type": "env",
        "name": "DEMO_MODEL_KEY",
    }
    assert "raw-secret-value" not in result.trace_path.read_text(encoding="utf-8")


def test_model_error_is_traced_when_provider_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_dir = tmp_path / "enterprise_qa"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa"), example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8")
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
