"""Install the designated local Metadata Profile without production authority claims."""

from __future__ import annotations

import os
from typing import Any, Protocol

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    proofagent_insurance_reference_profile,
)
from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
    S3ExactArtifactStore,
)
from proof_agent.capabilities.persistence.postgres.bundle import (
    PostgresPersistenceBundle,
)


SOURCE_ID = "ks_insurance"
ACTOR = "local-production-bootstrap"


class _ReferenceMetadataBundle(Protocol):
    @property
    def knowledge(self) -> Any: ...

    @property
    def metadata_reviews(self) -> Any: ...

    @property
    def hybrid_ingestion(self) -> Any: ...


def bootstrap_reference_metadata(bundle: _ReferenceMetadataBundle) -> bool:
    """Publish the checked-in Profile and bind it only to the local fixture if present."""

    profile = proofagent_insurance_reference_profile()
    bundle.metadata_reviews.publish_profile(
        profile,
        display_name="Proof Agent insurance reference",
        actor=ACTOR,
    )
    if bundle.knowledge.get_source_record(SOURCE_ID) is None:
        return False
    bundle.metadata_reviews.bind_source_profile(
        source_id=SOURCE_ID,
        profile_revision_id=profile.profile_revision_id,
        actor=ACTOR,
        production=False,
    )
    return True


def materialize_reference_candidate_reviews(
    bundle: _ReferenceMetadataBundle,
    artifact_store: object,
) -> int:
    """Restore missing V2 Review Sets without approving operator decisions."""

    bundle.hybrid_ingestion.configure_artifact_store(artifact_store)
    bundle.hybrid_ingestion.configure_reference_profile_source_ids((SOURCE_ID,))
    review_sets = (
        bundle.hybrid_ingestion.materialize_missing_candidate_review_sets(SOURCE_ID)
    )
    return len(review_sets)


def main() -> None:
    dsn = _required("PROOF_AGENT_POSTGRES_DSN")
    bundle = PostgresPersistenceBundle.create(dsn)
    artifact_store: S3ExactArtifactStore | None = None
    migrated = 0
    try:
        bound = bootstrap_reference_metadata(bundle)
        if bound:
            artifact_store = _artifact_store_from_environment()
            migrated = materialize_reference_candidate_reviews(bundle, artifact_store)
    finally:
        if artifact_store is not None:
            artifact_store.close()
        bundle.close()
    state = "bound to ks_insurance" if bound else "published; ks_insurance not present"
    print(
        f"local reference Metadata Profile is {state}; "
        f"materialized {migrated} missing candidate Review Set(s)",
        flush=True,
    )


def _artifact_store_from_environment() -> S3ExactArtifactStore:
    return S3ExactArtifactStore.from_environment(
        bucket=_required("HYBRID_S3_BUCKET"),
        key_prefix=os.environ.get("HYBRID_S3_KEY_PREFIX", ""),
        endpoint_url=os.environ.get("HYBRID_S3_ENDPOINT") or None,
        region_name=os.environ.get("HYBRID_S3_REGION") or None,
        allow_insecure_endpoint=(
            os.environ.get("HYBRID_S3_ALLOW_INSECURE_ENDPOINT", "").strip()
            == "1"
        ),
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
