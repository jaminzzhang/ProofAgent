# Defer Runtime Case Memory From the Initial Private Pilot

Accepted. Supersedes the initial-release runtime-memory requirement in ADR 0123 and the PostgreSQL Case Memory clause in ADR 0124; their remaining product boundaries stay in force.

[FRAME | HIGH] The initial private pilot does not enable runtime Case Memory reads or writes. The sole production Agent manifest keeps `capabilities.memory.enabled: false`, and production candidate validation rejects any manifest that enables non-authoritative runtime memory. PostgreSQL Case Memory contracts, schema and repositories remain dormant infrastructure rather than a shipped operator capability.

[FRAME | HIGH] Operator Chat conversation turns remain PostgreSQL-authoritative and may be admitted through Controlled Run Context. Conversation context and any future memory remain non-evidence: neither can establish business truth, satisfy an evidence slot or support a citation.

[COMPUTED | HIGH] Enabling Case Memory safely requires a later candidate-bound slice that fixes the case/conversation identity mapping, deterministic write-admission rules, allowed fact schema, deletion and expiry operations, audit projection, sensitive-data treatment, recall limits and real-model evaluation. Keeping the partially specified path disabled is safer than introducing production data retention and model-context behavior without those controls.
