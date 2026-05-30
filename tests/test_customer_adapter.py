from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import CustomerConversationRecord
from proof_agent.delivery.customer_adapters import CustomerAdapterRequest, load_customer_run_adapter


def test_customer_run_adapter_loads_from_agent_package_file(tmp_path: Path) -> None:
    adapter_path = tmp_path / "customer_adapter.py"
    adapter_path.write_text(
        """
from proof_agent.contracts import CustomerSafeResponse
from proof_agent.delivery.customer_adapters import CustomerAdapterResult


def handle_customer_run(request):
    return CustomerAdapterResult(
        safe_response=CustomerSafeResponse(message=f"adapter handled: {request.question}"),
        clear_disambiguation_options=True,
    )
""",
        encoding="utf-8",
    )
    manifest_path = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
    manifest = load_agent_manifest(manifest_path)
    conversation = CustomerConversationRecord(
        conversation_id="cust_conv_test",
        agent_id="demo",
        created_at="2026-05-22T00:00:00Z",
        updated_at="2026-05-22T00:00:00Z",
    )

    adapter = load_customer_run_adapter(adapter_path)
    result = adapter(
        CustomerAdapterRequest(
            manifest=manifest,
            manifest_path=manifest_path,
            question="hello",
            conversation=conversation,
        )
    )

    assert result is not None
    assert result.safe_response.message == "adapter handled: hello"
    assert result.clear_disambiguation_options is True
