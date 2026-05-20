from proof_agent.capabilities.tools.insurance_read import (
    claim_status_lookup,
    policy_status_lookup,
)


def test_policy_status_lookup_reads_fixture() -> None:
    result = policy_status_lookup({"customer_id": "CUST-001", "policy_id": "POL-001"})

    assert result["policy_id"] == "POL-001"
    assert result["status"] == "active"
    assert result["read_only"] is True


def test_claim_status_lookup_reads_fixture() -> None:
    result = claim_status_lookup({"customer_id": "CUST-001", "claim_id": "CLM-001"})

    assert result["claim_id"] == "CLM-001"
    assert result["status"] in {"received", "in_review"}
    assert result["read_only"] is True
