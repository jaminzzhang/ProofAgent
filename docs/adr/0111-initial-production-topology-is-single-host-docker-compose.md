# Initial Production Topology Is Single-Host Docker Compose

Accepted.

[FRAME | HIGH] The initial formal release supports one hardened Linux host running a production Docker Compose topology with separate Gateway, API, Run Executor, Knowledge Worker, and static Dashboard and Operator Chat process roles. API and Run Executor use the same Proof Agent image and product boundary; the Run Executor is not an independent microservice. PostgreSQL, S3-compatible Production Artifact Store, external OIDC, and Production Secret Provider remain external dependencies rather than colocated development containers. Kubernetes, multi-host high availability, public quick tunnels, source bind mounts, and the current deterministic-demo Compose file are outside the initial production topology.
