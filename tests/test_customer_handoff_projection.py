from proof_agent.observability.storage.handoff_projection import extract_handoffs


def test_extract_handoff_projection_from_trace_events() -> None:
    events = [
        {
            "event_type": "customer_handoff_created",
            "timestamp": "2026-05-20T00:00:00Z",
            "run_id": "run_123",
            "payload": {
                "reason": "insufficient_evidence",
                "question_summary": "Can you guarantee payment?",
                "customer_ref": "CUST-001",
            },
        }
    ]

    handoffs = extract_handoffs(events)

    assert len(handoffs) == 1
    assert handoffs[0].run_id == "run_123"
    assert handoffs[0].reason.value == "insufficient_evidence"


def test_extract_handoffs_ignores_non_handoff_events() -> None:
    handoffs = extract_handoffs(
        [
            {
                "event_type": "final_output",
                "timestamp": "2026-05-20T00:00:00Z",
                "run_id": "run_123",
                "payload": {"answer": "done"},
            }
        ]
    )

    assert handoffs == ()
