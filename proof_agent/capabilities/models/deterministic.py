from __future__ import annotations

import json
import re

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.demo.deterministic_provider import DeterministicProvider


class DeterministicModelProvider:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._provider = DeterministicProvider()

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> DeterministicModelProvider:
        if model_config.name is None:
            raise ProofAgentError(
                "PA_MODEL_001",
                "deterministic model config requires a model name.",
                "Resolve shared/custom model configuration before constructing the provider.",
            )
        return cls(model_config.name)

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return self._model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return None

    def generate(self, request: ModelRequest) -> ModelResponse:
        question = str(request.metadata.get("question") or _last_user_message(request))
        answer = self._provider.answer(question)
        if (
            request.function_schema is not None
            and request.function_schema.name == "submit_final_answer"
        ):
            if _missing_deterministic_answer(answer):
                answer = _answer_from_request_evidence(request)
            answer = json.dumps(
                {
                    "message": answer,
                    "citations": _allowed_citation_refs_from_request(request),
                },
                ensure_ascii=True,
            )
        return ModelResponse(
            content=answer,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def _missing_deterministic_answer(answer: str) -> bool:
    return answer.startswith("No deterministic answer is configured")


def _last_user_message(request: ModelRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content if request.messages else ""


def _answer_from_request_evidence(request: ModelRequest) -> str:
    evidence_text = _evidence_text_from_request(request)
    sentence = _first_evidence_sentence(evidence_text)
    if not sentence:
        return "No deterministic answer is configured for this question."
    return _paraphrase_evidence_sentence(sentence)


def _evidence_text_from_request(request: ModelRequest) -> str:
    user_message = _last_user_message(request)
    marker = "Evidence:\n"
    start = user_message.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = user_message.find("\n\nAllowed citation refs:", start)
    if end == -1:
        end = len(user_message)
    return user_message[start:end].strip()


def _first_evidence_sentence(evidence_text: str) -> str:
    lines = [
        line.strip()
        for line in evidence_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    normalized = " ".join(lines).strip()
    if not normalized:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", normalized)
    if match is None:
        return normalized
    return match.group(1).strip()


def _paraphrase_evidence_sentence(sentence: str) -> str:
    reimbursement = re.match(
        r"^(?P<subject>.+?)\s+are reimbursed up to\s+(?P<limit>.+?)\s+when\s+(?P<condition>.+?)\.$",
        sentence,
        flags=re.IGNORECASE,
    )
    if reimbursement is not None:
        subject = _singular_reimbursement_subject(reimbursement.group("subject"))
        return (
            f"{subject} reimbursement is capped at {reimbursement.group('limit')} "
            f"when {reimbursement.group('condition')}."
        )
    return f"Based on the accepted evidence, {sentence[0].lower()}{sentence[1:]}"


def _singular_reimbursement_subject(subject: str) -> str:
    stripped = subject.strip()
    if stripped.lower().endswith(" meals"):
        return stripped[:-1]
    return stripped


def _allowed_citation_refs_from_request(request: ModelRequest) -> list[str]:
    refs: list[str] = []
    capture = False
    for line in _last_user_message(request).splitlines():
        if line.strip() == "Allowed citation refs:":
            capture = True
            continue
        if not capture:
            continue
        if not line.startswith("- "):
            break
        ref = line[2:].strip()
        if ref:
            refs.append(ref)
    return refs[:1]
