from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_POLICY_STATUS = {
    ("CUST-001", "POL-001"): {"status": "active", "plan": "standard_health"},
    ("CUST-002", "POL-002"): {"status": "active", "plan": "premium_health"},
}

_CLAIM_STATUS = {
    ("CUST-001", "CLM-001"): {"status": "in_review", "received_date": "2026-05-01"},
    ("CUST-001", "CLM-003"): {"status": "received", "received_date": "2026-05-04"},
    ("CUST-002", "CLM-002"): {"status": "received", "received_date": "2026-05-03"},
}


def policy_status_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    """Return deterministic policy status for the authenticated mock customer."""

    customer_id = str(parameters["customer_id"])
    policy_id = str(parameters["policy_id"])
    record = _POLICY_STATUS.get((customer_id, policy_id), {"status": "not_found"})
    return {
        "customer_id": customer_id,
        "policy_id": policy_id,
        "read_only": True,
        "source": "insurance_read_fixture",
        **record,
    }


def claim_status_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    """Return deterministic claim status for the authenticated mock customer."""

    customer_id = str(parameters["customer_id"])
    claim_id = str(parameters["claim_id"])
    record = _CLAIM_STATUS.get((customer_id, claim_id), {"status": "not_found"})
    return {
        "customer_id": customer_id,
        "claim_id": claim_id,
        "read_only": True,
        "source": "insurance_read_fixture",
        **record,
    }
