# Observation Truth Artifact Typed Union

Accepted.

Observation Truth Artifacts will be modeled as a discriminated union with separate retrieval and tool variants, rather than as generic `Mapping[str, Any]` payloads. Retrieval Observation Truth carries admitted evidence and citation/admission metadata; Tool Observation Truth carries authorized redacted tool results, schema identity, approval reference, and redaction metadata.

We choose this because retrieval truth and tool truth have different validation, citation, redaction, and final-answer synthesis requirements. A generic payload would recreate the same boundary failure as putting raw data into Observation Record `summary`.
