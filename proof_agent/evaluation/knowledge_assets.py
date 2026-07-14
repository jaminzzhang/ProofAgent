"""Exact external-asset manifest for insurance Knowledge release evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import ExactArtifactRef
from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


class _AssetModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InsuranceKnowledgeAssetCohort(_AssetModel):
    cohort_id: str = Field(min_length=1)
    artifact: ExactArtifactRef
    case_count: int = Field(gt=0)
    clause_lookup_count: int = Field(ge=0)
    conditional_guidance_count: int = Field(ge=0)
    comparison_count: int = Field(ge=0)
    human_confirmed: Literal[True]
    access_controlled: bool
    tuner_visible: bool

    @model_validator(mode="after")
    def require_complete_mix(self) -> Self:
        if (
            self.clause_lookup_count + self.conditional_guidance_count + self.comparison_count
            != self.case_count
        ):
            raise ValueError("Knowledge cohort query-type counts must equal case count")
        return self


class InsuranceKnowledgeAssetManifest(_AssetModel):
    schema_version: Literal["insurance-knowledge-assets.v1"]
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    tuning: InsuranceKnowledgeAssetCohort
    sealed_acceptance: InsuranceKnowledgeAssetCohort
    parser_benchmark: InsuranceKnowledgeAssetCohort
    parser_sealed_case_count: int = Field(gt=0)

    @model_validator(mode="after")
    def require_release_cohorts(self) -> Self:
        if self.tuning.case_count != 300 or self.sealed_acceptance.case_count != 200:
            raise ValueError("Gold Suite requires exactly 300 tuning and 200 sealed cases")
        for label, cohort, expected in (
            ("tuning", self.tuning, (90, 150, 60)),
            ("sealed acceptance", self.sealed_acceptance, (60, 100, 40)),
        ):
            actual = (
                cohort.clause_lookup_count,
                cohort.conditional_guidance_count,
                cohort.comparison_count,
            )
            if actual != expected:
                raise ValueError(f"{label} cohort must preserve the 30/50/20 query mix")
        if self.tuning.access_controlled or not self.tuning.tuner_visible:
            raise ValueError("tuning cohort must be reviewer-visible and not sealed")
        if not self.sealed_acceptance.access_controlled or self.sealed_acceptance.tuner_visible:
            raise ValueError("sealed acceptance cohort must be access-controlled and tuner-hidden")
        if not 100 <= self.parser_benchmark.case_count <= 200:
            raise ValueError("parser benchmark requires 100 to 200 samples")
        if self.parser_sealed_case_count >= self.parser_benchmark.case_count:
            raise ValueError("parser sealed slice must leave a visible tuning slice")
        artifact_digests = {
            self.tuning.artifact.sha256,
            self.sealed_acceptance.artifact.sha256,
            self.parser_benchmark.artifact.sha256,
        }
        if len(artifact_digests) != 3:
            raise ValueError("evaluation cohorts must use distinct immutable artifacts")
        return self


def load_insurance_knowledge_asset_manifest(
    path: Path | str,
) -> InsuranceKnowledgeAssetManifest:
    manifest_path = Path(path)
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationInputError(
            f"Unable to read insurance Knowledge asset manifest: {manifest_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise EvaluationInputError("insurance Knowledge asset manifest must be a mapping")
    try:
        return InsuranceKnowledgeAssetManifest.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationInputError(f"Invalid insurance Knowledge asset manifest: {exc}") from exc


__all__ = [
    "InsuranceKnowledgeAssetCohort",
    "InsuranceKnowledgeAssetManifest",
    "load_insurance_knowledge_asset_manifest",
]
