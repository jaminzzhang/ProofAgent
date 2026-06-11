# Insurance Business Line Scope

This package is a generic Institution Insurance Specialist example. The bundled
fixture uses short-term accident insurance as the configured business line.

Short-term accident scope is expressed through knowledge routing metadata,
read-only institution tools, and authorization context. The workflow template is
not specific to short-term insurance.

Specialists may answer public knowledge questions without institution-specific
authorization context. Scoped report, policy, claim, customer, or agent record
queries require institution, branch, role, business-line, and data-scope
authorization before a read tool is proposed.
