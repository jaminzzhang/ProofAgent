"""Install the designated local Metadata Profile without production authority claims."""

from __future__ import annotations

import os
from typing import Protocol

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    proofagent_insurance_reference_profile,
)
from proof_agent.capabilities.persistence.postgres.bundle import (
    PostgresPersistenceBundle,
)


SOURCE_ID = "ks_insurance"
ACTOR = "local-production-bootstrap"


class _ReferenceMetadataBundle(Protocol):
    knowledge: object
    metadata_reviews: object


def bootstrap_reference_metadata(bundle: _ReferenceMetadataBundle) -> bool:
    """Publish the checked-in Profile and bind it only to the local fixture if present."""

    profile = proofagent_insurance_reference_profile()
    bundle.metadata_reviews.publish_profile(  # type: ignore[attr-defined]
        profile,
        display_name="Proof Agent insurance reference",
        actor=ACTOR,
    )
    if bundle.knowledge.get_source_record(SOURCE_ID) is None:  # type: ignore[attr-defined]
        return False
    bundle.metadata_reviews.bind_source_profile(  # type: ignore[attr-defined]
        source_id=SOURCE_ID,
        profile_revision_id=profile.profile_revision_id,
        actor=ACTOR,
        production=False,
    )
    return True


def main() -> None:
    dsn = _required("PROOF_AGENT_POSTGRES_DSN")
    bundle = PostgresPersistenceBundle.create(dsn)
    try:
        bound = bootstrap_reference_metadata(bundle)
    finally:
        bundle.close()
    state = "bound to ks_insurance" if bound else "published; ks_insurance not present"
    print(f"local reference Metadata Profile is {state}", flush=True)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
