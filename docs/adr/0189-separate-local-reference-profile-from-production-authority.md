---
status: accepted
---

# Separate local reference Profile from production authority

[FRAME | HIGH] Designated local environments check in and publish `proofagent-insurance-reference.v1` as an explicitly `reference_only` Insurance Metadata Profile and may bind it to the local `ks_insurance` fixture during the direct Metadata Review V2 migration. Its values must be explicitly declared reference codes and must not be inferred from uploaded PDFs or parser proposals. Production neither creates nor binds this Profile automatically: every production insurance Source must select an authorized, published, non-reference Profile Revision before migration may run. Replacing a reference binding later follows the normal Profile upgrade preview and renewed-approval workflow.
