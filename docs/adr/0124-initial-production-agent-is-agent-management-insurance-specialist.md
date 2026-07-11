# Initial Production Agent Is Agent Management Insurance Specialist

Accepted.

[FRAME | HIGH] `agent_management_insurance_specialist` is the sole Agent identity in the initial production release and the sole target of the candidate-bound real-LLM release gate. Its production form migrates to React Enterprise QA Template V3, PostgreSQL Case Memory, S3-backed Knowledge artifacts, Production Secret Handles, and default-deny Production Egress Policy. Local Tool Handlers are removed; tool capability is enabled only for contract-validated read-only HTTP tools, and otherwise remains disabled.

[FRAME | HIGH] `institution_insurance_specialist` and `insurance_customer_service` are removed as current example packages rather than shipped as production-disabled alternatives. The customer-facing example is also outside the accepted browser-operator-only release scope. Historical Git and ADR records may describe the removed examples, but current product documentation, tests, release suites, seeded configuration, and runtime catalogs must name only the sole production Agent where an active example is required.
