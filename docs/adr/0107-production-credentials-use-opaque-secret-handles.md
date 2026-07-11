# Production Credentials Use Opaque Secret Handles

Accepted.

[FRAME | HIGH] Production model, Knowledge Source, MCP, and tool configuration refers to credential material only through opaque Production Secret Handles resolved by the backend; Dashboard, Agent configuration, connection assets, and request payloads cannot submit raw secret values or arbitrary environment-variable names. A deployment-owned external Production Secret Provider is the sole authority for secret values and their creation, rotation, revocation, and deletion lifecycle; Proof Agent provides no Secret CRUD, while Dashboard may select existing handles and show bounded resolvability or validation status. Environment-variable credential references remain available only in explicit local-development mode, and a handle is non-secret configuration metadata that does not grant clients access to the resolved credential value.
