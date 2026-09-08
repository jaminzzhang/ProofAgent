"""Canonical provider-specific evidence identities, without remote URL inference."""

from urllib.parse import quote


def external_evidence_source(*, provider: str, binding_id: str, source_id: str,
                             document_id: str | None, chunk_id: str,
                             tenant_id: str | None = None) -> str:
    if provider == "dify" and document_id and tenant_id is None:
        return f"external://{binding_id}/datasets/{source_id}/documents/{document_id}"
    if provider == "agentset" and document_id is None:
        tenant = f"/tenants/{quote(tenant_id, safe='')}" if tenant_id is not None else ""
        return f"external://{binding_id}/namespaces/{quote(source_id, safe='')}{tenant}/chunks/{quote(chunk_id, safe='')}"
    raise ValueError("External evidence provider identity is invalid")
