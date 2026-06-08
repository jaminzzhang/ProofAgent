from proof_agent.capabilities.tools.source_descriptors import get_tool_source_descriptor
from proof_agent.contracts import ToolSource, ToolSourceDescriptor, ToolSourceLifecycleState


def test_brave_search_tool_source_descriptor_exposes_untrusted_web_search() -> None:
    descriptor = get_tool_source_descriptor("brave_search")

    assert isinstance(descriptor, ToolSourceDescriptor)
    assert descriptor.provider == "brave_search"
    assert descriptor.exposed_tool_contracts == ("untrusted_web_search",)
    assert descriptor.credential_env_vars == ("BRAVE_SEARCH_API_KEY",)
    assert descriptor.supports_validation is True


def test_tool_source_contract_represents_live_search_vendor_connection() -> None:
    source = ToolSource(
        source_id="ts_brave",
        name="Brave Search Production",
        source_type="search_vendor",
        provider="brave_search",
        lifecycle_state=ToolSourceLifecycleState.ACTIVE,
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_API_KEY",
        params={"timeout_seconds": 8, "default_max_results": 3},
        config_revision=2,
        created_at="2026-06-08T00:00:00Z",
        updated_at="2026-06-08T00:00:00Z",
    )

    assert source.lifecycle_state is ToolSourceLifecycleState.ACTIVE
    assert source.provider == "brave_search"
    assert source.credential_env_ref == "BRAVE_SEARCH_API_KEY"
    assert source.config_revision == 2
