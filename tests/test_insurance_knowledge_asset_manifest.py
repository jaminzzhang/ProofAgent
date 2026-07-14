from __future__ import annotations

import pytest

from proof_agent.contracts import ExactArtifactRef
from proof_agent.evaluation.knowledge_assets import (
    InsuranceKnowledgeAssetCohort,
    InsuranceKnowledgeAssetManifest,
)


def _artifact(name: str, character: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://private-evaluation/{name}.jsonl",
        version_id=f"{name}-v1",
        sha256=character * 64,
        size_bytes=4096,
        media_type="application/x-ndjson",
    )


def _cohort(name: str, count: int, mix: tuple[int, int, int], character: str):
    return InsuranceKnowledgeAssetCohort(
        cohort_id=name,
        artifact=_artifact(name, character),
        case_count=count,
        clause_lookup_count=mix[0],
        conditional_guidance_count=mix[1],
        comparison_count=mix[2],
        human_confirmed=True,
        access_controlled=name == "sealed",
        tuner_visible=name != "sealed",
    )


def test_asset_manifest_requires_real_500_case_split_and_parser_benchmark() -> None:
    manifest = InsuranceKnowledgeAssetManifest(
        schema_version="insurance-knowledge-assets.v1",
        suite_id="insurance-gold-2026-07",
        suite_version="2026-07-14",
        tuning=_cohort("tuning", 300, (90, 150, 60), "a"),
        sealed_acceptance=_cohort("sealed", 200, (60, 100, 40), "b"),
        parser_benchmark=_cohort("parser", 150, (45, 75, 30), "c"),
        parser_sealed_case_count=30,
    )

    assert manifest.tuning.case_count + manifest.sealed_acceptance.case_count == 500


def test_asset_manifest_rejects_exposed_or_wrongly_mixed_acceptance_cohort() -> None:
    with pytest.raises(ValueError, match="30/50/20"):
        InsuranceKnowledgeAssetManifest(
            schema_version="insurance-knowledge-assets.v1",
            suite_id="insurance-gold-2026-07",
            suite_version="2026-07-14",
            tuning=_cohort("tuning", 300, (90, 150, 60), "a"),
            sealed_acceptance=_cohort("sealed", 200, (70, 90, 40), "b"),
            parser_benchmark=_cohort("parser", 150, (45, 75, 30), "c"),
            parser_sealed_case_count=30,
        )
