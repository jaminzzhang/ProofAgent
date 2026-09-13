# ADR-0256: Authorize development Knowledge connections in the configuration flow

Status: accepted for the user-authorized local implementation on 2026-09-12.

[FRAME | HIGH] Development operators with Agent edit and Egress Policy edit permissions
can save bindings and authorize connections in one revision-checked command. A plain
save never grants access. Server-generated grants bind the complete canonical binding
digest and exact HTTPS origin, and live outside the editable YAML. Draft, grants and
audit commit through the existing configuration Unit of Work. Failed CAS/validation
does not grant access. Removing/changing a binding removes its matching grant.

Development execution reads the same persisted grants for the exact Agent and binding
through the configuration store. They apply only to external Knowledge transport, not
model, memory or tool networking. Retained drafts own grant lifetime; removing the last
matching grant revokes subsequent requests, including old published configurations.
No separate cache, JSON policy editing or restart is required after authorization.

Public DNS mode admits only globally routable unicast addresses. Every connection
checks the complete fresh DNS answer set and pins the socket with the original TLS
hostname; redirects and retries remain disabled. An explicit local-proxy option admits
198.18.0.0/15 and its IPv4-mapped representation only for the built-in api.agentset.ai
and api.dify.ai HTTPS origins on port 443. Other private/reserved addresses require an
independently managed server policy. DNS changes within the selected class need no
policy edit; changes outside it fail closed. This trusts the operator's local DNS/proxy
and TLS trust configuration, not arbitrary DNS answers as authorization.

Existing injected transports and explicit environment policy files retain precedence;
the UI does not override them. Production keeps the existing PostgreSQL policy and
Secret Provider and does not accept development grants. Production automatic policy
creation is not delivered by this development repair.

Connection checks require Secret Handle use permission, bind the saved revision,
resolve credentials only on the server and run one bounded synthetic read-only query
per binding via the normal provider adapter. They return only bounded status codes,
never credentials, remote response bodies or retrieved content. A successful check is
connectivity evidence, not answer quality or production publication authority.
