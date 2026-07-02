from __future__ import annotations

from fastapi import HTTPException

from proof_agent.errors import ProofAgentError


_PROOF_AGENT_HTTP_STATUS_BY_CODE = {
    "PA_MODEL_002": 502,
    "PA_MODEL_004": 504,
    "PA_INGESTION_004": 503,
    "PA_INGESTION_005": 409,
}


def proof_agent_http_exception(exc: ProofAgentError) -> HTTPException:
    status_code = _PROOF_AGENT_HTTP_STATUS_BY_CODE.get(exc.code, 400)
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
    )
