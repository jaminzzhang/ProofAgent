from proof_agent.delivery.api import ChatRunRequest, ConversationRunRequest


def test_chat_run_requests_accept_untrusted_web_supplement_preference() -> None:
    direct = ChatRunRequest(
        agent_id="agent_1",
        question="What changed today?",
        allow_untrusted_web_supplement=True,
    )
    conversation = ConversationRunRequest(
        question="What changed today?",
        allow_untrusted_web_supplement=True,
    )

    assert direct.allow_untrusted_web_supplement is True
    assert conversation.allow_untrusted_web_supplement is True
