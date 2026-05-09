from proof_agent.memory.session import SessionMemory


def test_session_memory_rejects_sensitive_write() -> None:
    memory = SessionMemory(deny_fields={"access_token", "customer_phone"})
    result = memory.write({"summary": "ok", "access_token": "secret"})
    assert result.status == "failed"
    assert memory.read() == {}


def test_session_memory_allows_safe_summary() -> None:
    memory = SessionMemory(deny_fields={"access_token"})
    result = memory.write({"summary": "customer asked about travel meals"})
    assert result.status == "passed"
    assert memory.read()["summary"] == "customer asked about travel meals"
