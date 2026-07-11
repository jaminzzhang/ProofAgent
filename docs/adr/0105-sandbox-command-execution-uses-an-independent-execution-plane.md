# Sandbox Command Execution Uses an Independent Execution Plane

Accepted.

[FRAME | HIGH] Future sandboxed script and command execution will run only through a dedicated Sandbox Execution Service outside the Proof Agent API and worker process and container boundaries. API and worker components may submit governed sandbox jobs and consume bounded results, but they must not execute the requested program locally or inherit the sandbox workload's trust boundary. This remains a post-release capability and does not weaken ADR-0104's initial-production prohibition.
