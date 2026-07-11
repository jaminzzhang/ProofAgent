# Initial Release Recovery Objectives

Accepted.

[FRAME | HIGH] The initial internal single-tenant private pilot has a Recovery Point Objective of no more than 15 minutes and a Recovery Time Objective of no more than 4 hours for the combined Production Transactional State Store and Production Artifact Store. Release readiness requires tested PostgreSQL point-in-time recovery, object-version recovery, cross-store reference and digest verification, and a timed restoration rehearsal that meets both objectives. Unverified backup existence does not satisfy either objective.
