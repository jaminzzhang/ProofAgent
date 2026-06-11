from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_REPORTS = {
    ("INST-001", "BR-SH", "short_term_accident", "2026-05", "premium_income"): {
        "value": 1280000,
        "unit": "CNY",
        "calculation_basis": "issued premium for short-term accident policies",
    },
    ("INST-001", "BR-SH", "short_term_accident", "2026-05", "claim_count"): {
        "value": 42,
        "unit": "claims",
        "calculation_basis": "claims received in reporting period",
    },
}

_POLICIES = {
    ("INST-001", "BR-SH", "short_term_accident", "POL-ST-001"): {
        "status": "active",
        "product": "short_term_accident_basic",
    },
}

_CLAIMS = {
    ("INST-001", "BR-SH", "short_term_accident", "CLM-ST-001"): {
        "status": "pending_documents",
        "received_date": "2026-05-12",
    },
}

_CUSTOMERS = {
    ("INST-001", "BR-SH", "short_term_accident", "CUST-ST-001"): {
        "customer_handle": "CUST-ST-001",
        "segment": "individual",
    },
}

_AGENTS = {
    ("INST-001", "BR-SH", "short_term_accident", "AGT-ST-001"): {
        "agent_handle": "AGT-ST-001",
        "channel": "agency",
    },
}


def institution_report_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    key = _scope_key(parameters) + (
        str(parameters["report_period"]),
        str(parameters["metric"]),
    )
    record = _REPORTS.get(key, {"status": "not_found"})
    return {
        **_scope_result(parameters),
        "report_period": str(parameters["report_period"]),
        "metric": str(parameters["metric"]),
        "read_only": True,
        "source": "institution_report_fixture",
        **record,
    }


def institution_policy_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    policy_id = str(parameters["policy_id"])
    record = _POLICIES.get(_scope_key(parameters) + (policy_id,), {"status": "not_found"})
    return {
        **_scope_result(parameters),
        "policy_id": policy_id,
        "read_only": True,
        "source": "institution_policy_fixture",
        **record,
    }


def institution_claim_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    claim_id = str(parameters["claim_id"])
    record = _CLAIMS.get(_scope_key(parameters) + (claim_id,), {"status": "not_found"})
    return {
        **_scope_result(parameters),
        "claim_id": claim_id,
        "read_only": True,
        "source": "institution_claim_fixture",
        **record,
    }


def institution_customer_profile_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    customer_id = str(parameters["customer_id"])
    record = _CUSTOMERS.get(
        _scope_key(parameters) + (customer_id,),
        {"status": "not_found"},
    )
    return {
        **_scope_result(parameters),
        "customer_id": customer_id,
        "read_only": True,
        "source": "institution_customer_profile_fixture",
        **record,
    }


def institution_agent_profile_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    agent_id = str(parameters["agent_id"])
    record = _AGENTS.get(_scope_key(parameters) + (agent_id,), {"status": "not_found"})
    return {
        **_scope_result(parameters),
        "agent_id": agent_id,
        "read_only": True,
        "source": "institution_agent_profile_fixture",
        **record,
    }


def _scope_key(parameters: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(parameters["institution_id"]),
        str(parameters["branch_id"]),
        str(parameters["business_line"]),
    )


def _scope_result(parameters: Mapping[str, Any]) -> dict[str, str]:
    institution_id, branch_id, business_line = _scope_key(parameters)
    return {
        "institution_id": institution_id,
        "branch_id": branch_id,
        "business_line": business_line,
    }
