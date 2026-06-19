from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_PERFORMANCE = {
    (
        "INST-001",
        "BR-SH",
        "TEAM-A",
        "AGT-001",
        "life",
        "2026-05",
        "premium_income",
        "agent",
    ): {
        "value": 860000,
        "unit": "CNY",
        "calculation_basis": "issued premium from managed-agent policies",
    },
    (
        "INST-001",
        "BR-SH",
        "TEAM-A",
        "AGT-001",
        "life",
        "2026-05",
        "first_year_commission",
        "agent",
    ): {
        "value": 118000,
        "unit": "CNY",
        "calculation_basis": "first-year commission booked in the reporting period",
    },
}

_ACTIVITY = {
    (
        "INST-001",
        "BR-SH",
        "TEAM-A",
        "AGT-001",
        "life",
        "2026-05",
        "visit_count",
        "agent",
    ): {
        "value": 42,
        "unit": "visits",
        "calculation_basis": "logged customer visits during reporting period",
    },
    (
        "INST-001",
        "BR-SH",
        "TEAM-A",
        "AGT-001",
        "life",
        "2026-05",
        "target_achievement_rate",
        "agent",
    ): {
        "value": 0.91,
        "unit": "ratio",
        "calculation_basis": "period performance divided by assigned target",
    },
}

_AGENTS = {
    ("INST-001", "BR-SH", "TEAM-A", "AGT-001", "life"): {
        "agent_handle": "AGT-001",
        "grade": "senior_agent",
        "managed_scope": "current_specialist_scope",
    },
}

_POLICIES = {
    ("INST-001", "BR-SH", "life", "POL-001"): {
        "status": "active",
        "product": "life_protection_basic",
    },
}

_CLAIMS = {
    ("INST-001", "BR-SH", "life", "CLM-001"): {
        "status": "pending_documents",
        "received_date": "2026-05-12",
    },
}

_CUSTOMERS = {
    ("INST-001", "BR-SH", "life", "CUST-001"): {
        "customer_handle": "CUST-001",
        "segment": "individual",
    },
}


def agent_performance_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    key = _managed_agent_metric_key(parameters)
    record = _PERFORMANCE.get(key, {"status": "not_found"})
    return {
        **_managed_scope_result(parameters),
        "report_period": str(parameters["report_period"]),
        "metric": str(parameters["metric"]),
        "aggregation_level": str(parameters["aggregation_level"]),
        "read_only": True,
        "source": "managed_agent_performance_fixture",
        **record,
    }


def agent_activity_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    key = _managed_agent_metric_key(parameters)
    record = _ACTIVITY.get(key, {"status": "not_found"})
    return {
        **_managed_scope_result(parameters),
        "report_period": str(parameters["report_period"]),
        "metric": str(parameters["metric"]),
        "aggregation_level": str(parameters["aggregation_level"]),
        "read_only": True,
        "source": "managed_agent_activity_fixture",
        **record,
    }


def agent_profile_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    key = _managed_scope_key(parameters)
    record = _AGENTS.get(key, {"status": "not_found"})
    return {
        **_managed_scope_result(parameters),
        "read_only": True,
        "source": "managed_agent_profile_fixture",
        **record,
    }


def policy_record_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    policy_id = str(parameters["policy_id"])
    record = _POLICIES.get(_business_scope_key(parameters) + (policy_id,), {"status": "not_found"})
    return {
        **_business_scope_result(parameters),
        "policy_id": policy_id,
        "read_only": True,
        "source": "policy_record_fixture",
        **record,
    }


def claim_record_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    claim_id = str(parameters["claim_id"])
    record = _CLAIMS.get(_business_scope_key(parameters) + (claim_id,), {"status": "not_found"})
    return {
        **_business_scope_result(parameters),
        "claim_id": claim_id,
        "read_only": True,
        "source": "claim_record_fixture",
        **record,
    }


def customer_profile_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    customer_id = str(parameters["customer_id"])
    record = _CUSTOMERS.get(
        _business_scope_key(parameters) + (customer_id,),
        {"status": "not_found"},
    )
    return {
        **_business_scope_result(parameters),
        "customer_id": customer_id,
        "read_only": True,
        "source": "customer_profile_fixture",
        **record,
    }


def _managed_agent_metric_key(parameters: Mapping[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    return _managed_scope_key(parameters) + (
        str(parameters["report_period"]),
        str(parameters["metric"]),
        str(parameters["aggregation_level"]),
    )


def _managed_scope_key(parameters: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(parameters["institution_id"]),
        str(parameters["branch_id"]),
        str(parameters["team_id"]),
        str(parameters["agent_id"]),
        str(parameters["business_line"]),
    )


def _business_scope_key(parameters: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(parameters["institution_id"]),
        str(parameters["branch_id"]),
        str(parameters["business_line"]),
    )


def _managed_scope_result(parameters: Mapping[str, Any]) -> dict[str, str]:
    institution_id, branch_id, team_id, agent_id, business_line = _managed_scope_key(parameters)
    return {
        "institution_id": institution_id,
        "branch_id": branch_id,
        "team_id": team_id,
        "agent_id": agent_id,
        "business_line": business_line,
    }


def _business_scope_result(parameters: Mapping[str, Any]) -> dict[str, str]:
    institution_id, branch_id, business_line = _business_scope_key(parameters)
    return {
        "institution_id": institution_id,
        "branch_id": branch_id,
        "business_line": business_line,
    }
