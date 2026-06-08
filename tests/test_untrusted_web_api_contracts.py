from proof_agent.delivery.api import ChatRunRequest, ConversationRunRequest
from proof_agent.delivery.customer_api import CustomerRunRequest


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


def test_customer_run_request_accepts_untrusted_web_supplement_preference() -> None:
    request = CustomerRunRequest(
        question="What changed today?",
        allow_untrusted_web_supplement=True,
    )

    assert request.allow_untrusted_web_supplement is True
