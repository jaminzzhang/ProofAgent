# Permission Mapping Retains a Deployment Recovery Group

Accepted.

[FRAME | HIGH] Because OIDC is the exclusive initial-production authentication source, the deployment must define one protected Recovery OIDC Group mapping that grants at least `permission_mapping.view`, `permission_mapping.edit`, and `audit.view`. Proof Agent combines this mapping with Dashboard-managed External Operator Permission Mapping entries, but the Dashboard and its APIs cannot rename, weaken, replace, or delete the protected entry. Changing the Recovery OIDC Group requires an explicit deployment configuration change and service restart, and release readiness requires a successful login and permission-recovery exercise using a member of that external group.

[FRAME | HIGH] Ordinary OIDC group or role mappings remain directly configurable by an operator with `permission_mapping.edit`; no approval workflow is added. Each proposed replacement is completely validated and activated atomically as a new version, with the previous version retained for audited rollback. This protected external recovery path is chosen over a local break-glass account so production remains OIDC-exclusive, and over an entirely Dashboard-managed mapping so an authorized but erroneous edit cannot lock every operator out of recovery.
