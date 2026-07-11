# Production Egress Is Default-Deny and Dashboard-Managed

Accepted.

[FRAME | HIGH] Every production server-side model, Knowledge Source, MCP, tool, and other governed outbound request is denied unless its exact HTTPS origin is present in the active Production Egress Policy; destination resolution, redirects, and retries must remain inside that policy. Dashboard provides an Egress Policy Workspace, but the backend owns validation and enforcement, and Agent configuration, connection assets, request payloads, or frontend state cannot widen the active policy. The initial release has no Egress approval workflow: a permitted operator may update the active policy directly only through complete backend validation, atomic replacement, and configuration audit; invalid candidates leave the active policy unchanged. Approved internal HTTPS services may be listed explicitly without creating a blanket private-network exception.
