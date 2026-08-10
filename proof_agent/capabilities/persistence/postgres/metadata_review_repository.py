from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
from datetime import UTC, date, datetime
import hashlib
import json
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataProfileRevision,
    InsuranceMetadataReviewPageV2,
    InsuranceMetadataReviewSet,
    InsuranceMetadataReviewSummaryV2,
    InsuranceMetadataReviewV2,
    MetadataReviewCommandResult,
    MetadataReviewConflictError,
    MetadataProfileBindingRequiredError,
    MetadataReviewValidationError,
    advance_insurance_metadata_review_set,
    approve_metadata_review,
    require_production_metadata_profile,
    reject_metadata_review,
    save_metadata_review_draft,
)
from proof_agent.capabilities.knowledge.hybrid.metadata_workbook import (
    MetadataWorkbookApplyResultV2,
    MetadataWorkbookImportPreviewV2,
    apply_metadata_workbook_import_preview_v2,
)
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    hybrid_metadata_review_decisions,
    hybrid_metadata_review_sets,
    hybrid_metadata_reviews,
    insurance_metadata_profile_revisions,
    insurance_metadata_profiles,
    knowledge_source_metadata_bindings,
)
from proof_agent.contracts.persistence import PersistenceInvariantError


class PostgresInsuranceMetadataReviewRepository:
    """Transactional V2 Profile and metadata-review authority."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock

    def publish_profile(
        self,
        profile: InsuranceMetadataProfileRevision,
        *,
        display_name: str,
        actor: str,
        published_at: datetime | None = None,
    ) -> InsuranceMetadataProfileRevision:
        name = _nonblank(display_name, "display_name")
        publisher = _nonblank(actor, "actor")
        timestamp = self._timestamp(published_at)
        profile_json = model_json(profile)
        profile_digest = hashlib.sha256(
            profile.model_dump_json().encode("utf-8")
        ).hexdigest()
        with write_connection(self._connection_source) as connection:
            connection.execute(
                postgres_insert(insurance_metadata_profiles)
                .values(
                    profile_id=profile.profile_id,
                    display_name=name,
                    lifecycle_state="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                .on_conflict_do_nothing()
            )
            existing = connection.execute(
                select(insurance_metadata_profile_revisions.c.profile_json).where(
                    insurance_metadata_profile_revisions.c.profile_revision_id
                    == profile.profile_revision_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                persisted = _profile(existing)
                if persisted != profile:
                    raise MetadataReviewConflictError(
                        "metadata Profile revision identity already exists"
                    )
                return persisted
            revision_number = int(
                connection.execute(
                    select(
                        func.coalesce(
                            func.max(
                                insurance_metadata_profile_revisions.c.revision_number
                            ),
                            0,
                        )
                    ).where(
                        insurance_metadata_profile_revisions.c.profile_id
                        == profile.profile_id
                    )
                ).scalar_one()
            ) + 1
            connection.execute(
                insurance_metadata_profile_revisions.insert().values(
                    profile_revision_id=profile.profile_revision_id,
                    profile_id=profile.profile_id,
                    revision_number=revision_number,
                    profile_digest=profile_digest,
                    reference_only=profile.reference_only,
                    profile_json=profile_json,
                    published_by=publisher,
                    published_at=timestamp,
                )
            )
        return profile

    def bind_source_profile(
        self,
        *,
        source_id: str,
        profile_revision_id: str,
        actor: str,
        bound_at: datetime | None = None,
        production: bool,
    ) -> InsuranceMetadataProfileRevision:
        binder = _nonblank(actor, "actor")
        timestamp = self._timestamp(bound_at)
        with write_connection(self._connection_source) as connection:
            profile = self._profile(connection, profile_revision_id)
            if production:
                require_production_metadata_profile(profile)
            connection.execute(
                postgres_insert(knowledge_source_metadata_bindings)
                .values(
                    source_id=source_id,
                    metadata_scheme="insurance_rule.v2",
                    profile_revision_id=profile.profile_revision_id,
                    bound_by=binder,
                    bound_at=timestamp,
                )
                .on_conflict_do_update(
                    index_elements=[knowledge_source_metadata_bindings.c.source_id],
                    set_={
                        "metadata_scheme": "insurance_rule.v2",
                        "profile_revision_id": profile.profile_revision_id,
                        "bound_by": binder,
                        "bound_at": timestamp,
                    },
                )
            )
        return profile

    def get_bound_profile(
        self,
        source_id: str,
        *,
        production: bool = False,
    ) -> InsuranceMetadataProfileRevision:
        """Return the Source-controlled Profile revision for materialization."""

        with read_connection(self._connection_source) as connection:
            profile = self._bound_profile(connection, source_id)
        if production:
            require_production_metadata_profile(profile)
        return profile

    def put_review_set(
        self, review_set: InsuranceMetadataReviewSet
    ) -> InsuranceMetadataReviewSet:
        document_id, revision_id = _revision_uuids(review_set)
        now = self._timestamp(None)
        with write_connection(self._connection_source) as connection:
            profile = self._bound_profile(connection, review_set.source_id)
            if profile.profile_revision_id != review_set.profile_revision_id:
                raise MetadataReviewConflictError(
                    "metadata Review Set Profile does not match Source binding"
                )
            self._supersede_prior_document_revisions(
                connection,
                source_id=review_set.source_id,
                document_id=document_id,
                revision_id=revision_id,
                updated_at=now,
            )
            existing = connection.execute(
                select(hybrid_metadata_review_sets.c.review_set_json)
                .where(
                    hybrid_metadata_review_sets.c.source_id == review_set.source_id,
                    hybrid_metadata_review_sets.c.document_id == document_id,
                    hybrid_metadata_review_sets.c.revision_id == revision_id,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                persisted = _review_set(existing)
                if persisted != review_set:
                    raise MetadataReviewConflictError(
                        "current metadata Review Set already exists"
                    )
                return persisted
            connection.execute(
                hybrid_metadata_review_sets.insert().values(
                    **_review_set_values(
                        review_set,
                        document_id=document_id,
                        revision_id=revision_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            )
            for review in review_set.reviews:
                connection.execute(
                    hybrid_metadata_reviews.insert().values(
                        **_review_values(
                            review_set.review_set_id,
                            review,
                            document_id=document_id,
                            revision_id=revision_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                )
        return review_set

    def _supersede_prior_document_revisions(
        self,
        connection: object,
        *,
        source_id: str,
        document_id: UUID,
        revision_id: UUID,
        updated_at: datetime,
    ) -> None:
        connection.execute(  # type: ignore[attr-defined]
            update(hybrid_metadata_review_sets)
            .where(
                hybrid_metadata_review_sets.c.source_id == source_id,
                hybrid_metadata_review_sets.c.document_id == document_id,
                hybrid_metadata_review_sets.c.revision_id != revision_id,
                hybrid_metadata_review_sets.c.current.is_(True),
            )
            .values(current=False, updated_at=updated_at)
        )
        connection.execute(  # type: ignore[attr-defined]
            update(hybrid_metadata_reviews)
            .where(
                hybrid_metadata_reviews.c.source_id == source_id,
                hybrid_metadata_reviews.c.document_id == document_id,
                hybrid_metadata_reviews.c.revision_id != revision_id,
                hybrid_metadata_reviews.c.current.is_(True),
            )
            .values(current=False, updated_at=updated_at)
        )

    def get_current_review_set(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> InsuranceMetadataReviewSet | None:
        try:
            document_uuid = UUID(document_id)
            revision_uuid = UUID(revision_id)
        except ValueError as exc:
            raise MetadataReviewValidationError(
                "production metadata reviews require UUID document revisions"
            ) from exc
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                select(hybrid_metadata_review_sets.c.review_set_json).where(
                    hybrid_metadata_review_sets.c.source_id == source_id,
                    hybrid_metadata_review_sets.c.document_id == document_uuid,
                    hybrid_metadata_review_sets.c.revision_id == revision_uuid,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
            ).scalar_one_or_none()
        return None if payload is None else _review_set(payload)

    def list_page(
        self,
        source_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        state: str | None = None,
        import_id: str | None = None,
    ) -> InsuranceMetadataReviewPageV2:
        del import_id
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MetadataReviewValidationError(
                "metadata review page limit must be between 1 and 100"
            )
        states = {"needs_input", "ready_for_approval", "approved", "rejected"}
        if state is not None and state not in states:
            raise MetadataReviewValidationError("metadata review state filter is invalid")
        after = _decode_cursor(cursor) if cursor is not None else None
        conditions = [
            hybrid_metadata_reviews.c.source_id == source_id,
            hybrid_metadata_reviews.c.current.is_(True),
        ]
        if state is not None:
            conditions.append(hybrid_metadata_reviews.c.state == state)
        page_conditions = list(conditions)
        if after is not None:
            page_conditions.append(hybrid_metadata_reviews.c.review_id > after)
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(
                select(hybrid_metadata_reviews.c.review_json)
                .where(and_(*page_conditions))
                .order_by(hybrid_metadata_reviews.c.review_id)
                .limit(limit + 1)
            ).scalars().all()
            total = int(
                connection.execute(
                    select(func.count())
                    .select_from(hybrid_metadata_reviews)
                    .where(and_(*conditions))
                ).scalar_one()
            )
            summary_rows = connection.execute(
                select(hybrid_metadata_reviews.c.state, func.count())
                .where(
                    hybrid_metadata_reviews.c.source_id == source_id,
                    hybrid_metadata_reviews.c.current.is_(True),
                )
                .group_by(hybrid_metadata_reviews.c.state)
            ).all()
        has_more = len(payloads) > limit
        items = tuple(_review(payload) for payload in payloads[:limit])
        counts = {str(row[0]): int(row[1]) for row in summary_rows}
        summary_total = sum(counts.values())
        approved = counts.get("approved", 0)
        return InsuranceMetadataReviewPageV2(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1].review_id) if has_more and items else None
            ),
            total=total,
            summary=InsuranceMetadataReviewSummaryV2(
                total=summary_total,
                unresolved=summary_total - approved,
                needs_input=counts.get("needs_input", 0),
                ready_for_approval=counts.get("ready_for_approval", 0),
                approved=approved,
                rejected=counts.get("rejected", 0),
                all_approved=summary_total > 0 and approved == summary_total,
            ),
        )

    def save_draft(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        changes: Mapping[str, str | int | date | None],
    ) -> MetadataReviewCommandResult:
        return self._command(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
            action="save_draft",
            changes=changes,
        )

    def approve(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
    ) -> MetadataReviewCommandResult:
        return self._command(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
            action="approve",
            changes=None,
        )

    def reject(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
    ) -> MetadataReviewCommandResult:
        return self._command(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
            action="reject",
            changes=None,
        )

    def apply_workbook_preview(
        self,
        preview: MetadataWorkbookImportPreviewV2,
        *,
        expected_preview_identity: str,
        actor: str,
        reason: str,
    ) -> MetadataWorkbookApplyResultV2:
        """Apply a stored Preview under the Review Set row lock."""

        try:
            document_uuid = UUID(preview.document_id)
            revision_uuid = UUID(preview.revision_id)
        except ValueError as exc:
            raise MetadataReviewValidationError(
                "production metadata reviews require UUID document revisions"
            ) from exc
        now = self._timestamp(None)
        with write_connection(self._connection_source) as connection:
            set_row = connection.execute(
                select(hybrid_metadata_review_sets)
                .where(
                    hybrid_metadata_review_sets.c.source_id == preview.source_id,
                    hybrid_metadata_review_sets.c.document_id == document_uuid,
                    hybrid_metadata_review_sets.c.revision_id == revision_uuid,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
                .with_for_update()
            ).mappings().one_or_none()
            if set_row is None:
                raise KeyError(preview.preview_id)
            current_set = _review_set(set_row["review_set_json"])
            profile = self._bound_profile(connection, preview.source_id)
            result = apply_metadata_workbook_import_preview_v2(
                preview,
                current_review_set=current_set,
                profile=profile,
                expected_preview_identity=expected_preview_identity,
                actor=actor,
                reason=reason,
            )
            prior_by_id = {review.review_id: review for review in current_set.reviews}
            resulting_by_identity = {
                review.review_identity: review for review in result.review_set.reviews
            }
            for decision in result.decisions:
                review = resulting_by_identity[decision.resulting_review_identity]
                prior = prior_by_id.get(review.review_id)
                values = _review_values(
                    current_set.review_set_id,
                    review,
                    document_id=document_uuid,
                    revision_id=revision_uuid,
                    created_at=(now if prior is None else set_row["created_at"]),
                    updated_at=now,
                )
                if prior is None:
                    connection.execute(hybrid_metadata_reviews.insert().values(**values))
                else:
                    changed = connection.execute(
                        update(hybrid_metadata_reviews)
                        .where(
                            hybrid_metadata_reviews.c.source_id == preview.source_id,
                            hybrid_metadata_reviews.c.review_id == prior.review_id,
                            hybrid_metadata_reviews.c.review_version
                            == prior.review_version,
                            hybrid_metadata_reviews.c.review_identity
                            == prior.review_identity,
                            hybrid_metadata_reviews.c.current.is_(True),
                        )
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise MetadataReviewConflictError(
                            "metadata review changed; reload exact identity"
                        )
                connection.execute(
                    hybrid_metadata_review_decisions.insert().values(
                        source_id=preview.source_id,
                        decision_id=decision.decision_id,
                        review_id=review.review_id,
                        prior_review_identity=decision.prior_review_identity,
                        resulting_review_identity=decision.resulting_review_identity,
                        action=decision.action,
                        actor=decision.actor,
                        reason=decision.reason,
                        changed_fields_json=list(decision.changed_fields),
                        decision_json=model_json(decision),
                        created_at=now,
                    )
                )
            changed_set = connection.execute(
                update(hybrid_metadata_review_sets)
                .where(
                    hybrid_metadata_review_sets.c.source_id == preview.source_id,
                    hybrid_metadata_review_sets.c.review_set_id
                    == current_set.review_set_id,
                    hybrid_metadata_review_sets.c.generation == current_set.generation,
                    hybrid_metadata_review_sets.c.review_set_identity
                    == current_set.review_set_identity,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
                .values(
                    generation=result.review_set.generation,
                    review_set_identity=result.review_set.review_set_identity,
                    review_set_json=model_json(result.review_set),
                    updated_at=now,
                )
            )
            if changed_set.rowcount != 1:
                raise MetadataReviewConflictError(
                    "metadata Review Set changed; reload exact identity"
                )
        return result

    def _command(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        action: Literal["save_draft", "approve", "reject"],
        changes: Mapping[str, str | int | date | None] | None,
    ) -> MetadataReviewCommandResult:
        try:
            document_uuid = UUID(document_id)
            revision_uuid = UUID(revision_id)
        except ValueError as exc:
            raise MetadataReviewValidationError(
                "production metadata reviews require UUID document revisions"
            ) from exc
        now = self._timestamp(None)
        with write_connection(self._connection_source) as connection:
            set_row = connection.execute(
                select(hybrid_metadata_review_sets)
                .where(
                    hybrid_metadata_review_sets.c.source_id == source_id,
                    hybrid_metadata_review_sets.c.document_id == document_uuid,
                    hybrid_metadata_review_sets.c.revision_id == revision_uuid,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
                .with_for_update()
            ).mappings().one_or_none()
            if set_row is None:
                raise KeyError(review_id)
            current_set = _review_set(set_row["review_set_json"])
            current = next(
                (review for review in current_set.reviews if review.review_id == review_id),
                None,
            )
            if current is None:
                raise KeyError(review_id)
            profile = self._bound_profile(connection, source_id)
            if action == "save_draft":
                result = save_metadata_review_draft(
                    current,
                    profile=profile,
                    expected_review_version=expected_review_version,
                    expected_review_identity=expected_review_identity,
                    actor=actor,
                    reason=reason,
                    changes=changes or {},
                )
            elif action == "approve":
                result = approve_metadata_review(
                    current,
                    profile=profile,
                    expected_review_version=expected_review_version,
                    expected_review_identity=expected_review_identity,
                    actor=actor,
                    reason=reason,
                )
            else:
                result = reject_metadata_review(
                    current,
                    expected_review_version=expected_review_version,
                    expected_review_identity=expected_review_identity,
                    actor=actor,
                    reason=reason,
                )
            updated_set = advance_insurance_metadata_review_set(
                current_set, result.review
            )
            changed_review = connection.execute(
                update(hybrid_metadata_reviews)
                .where(
                    hybrid_metadata_reviews.c.source_id == source_id,
                    hybrid_metadata_reviews.c.review_id == review_id,
                    hybrid_metadata_reviews.c.review_version == expected_review_version,
                    hybrid_metadata_reviews.c.review_identity == expected_review_identity,
                    hybrid_metadata_reviews.c.current.is_(True),
                )
                .values(
                    **_review_values(
                        current_set.review_set_id,
                        result.review,
                        document_id=document_uuid,
                        revision_id=revision_uuid,
                        created_at=set_row["created_at"],
                        updated_at=now,
                    )
                )
            )
            if changed_review.rowcount != 1:
                raise MetadataReviewConflictError(
                    "metadata review changed; reload exact identity"
                )
            changed_set = connection.execute(
                update(hybrid_metadata_review_sets)
                .where(
                    hybrid_metadata_review_sets.c.source_id == source_id,
                    hybrid_metadata_review_sets.c.review_set_id
                    == current_set.review_set_id,
                    hybrid_metadata_review_sets.c.generation == current_set.generation,
                    hybrid_metadata_review_sets.c.review_set_identity
                    == current_set.review_set_identity,
                    hybrid_metadata_review_sets.c.current.is_(True),
                )
                .values(
                    generation=updated_set.generation,
                    review_set_identity=updated_set.review_set_identity,
                    review_set_json=model_json(updated_set),
                    updated_at=now,
                )
            )
            if changed_set.rowcount != 1:
                raise MetadataReviewConflictError(
                    "metadata Review Set changed; reload exact identity"
                )
            connection.execute(
                hybrid_metadata_review_decisions.insert().values(
                    source_id=source_id,
                    decision_id=result.decision.decision_id,
                    review_id=review_id,
                    prior_review_identity=result.decision.prior_review_identity,
                    resulting_review_identity=(
                        result.decision.resulting_review_identity
                    ),
                    action=result.decision.action,
                    actor=result.decision.actor,
                    reason=result.decision.reason,
                    changed_fields_json=list(result.decision.changed_fields),
                    decision_json=model_json(result.decision),
                    created_at=now,
                )
            )
        return result

    def _bound_profile(
        self, connection: object, source_id: str
    ) -> InsuranceMetadataProfileRevision:
        row = connection.execute(  # type: ignore[attr-defined]
            select(knowledge_source_metadata_bindings.c.profile_revision_id).where(
                knowledge_source_metadata_bindings.c.source_id == source_id,
                knowledge_source_metadata_bindings.c.metadata_scheme
                == "insurance_rule.v2",
            )
        ).scalar_one_or_none()
        if row is None:
            raise MetadataProfileBindingRequiredError(
                "insurance_rule.v2 Source requires a published metadata Profile binding"
            )
        return self._profile(connection, str(row))

    @staticmethod
    def _profile(
        connection: object, profile_revision_id: str
    ) -> InsuranceMetadataProfileRevision:
        payload = connection.execute(  # type: ignore[attr-defined]
            select(insurance_metadata_profile_revisions.c.profile_json).where(
                insurance_metadata_profile_revisions.c.profile_revision_id
                == profile_revision_id
            )
        ).scalar_one_or_none()
        if payload is None:
            raise MetadataReviewValidationError(
                "published metadata Profile revision was not found"
            )
        return _profile(payload)

    def _timestamp(self, value: datetime | None) -> datetime:
        timestamp = self._clock() if value is None else value
        if timestamp.utcoffset() is None:
            raise PersistenceInvariantError("metadata review clock must be timezone-aware")
        return timestamp


def _profile(payload: object) -> InsuranceMetadataProfileRevision:
    return InsuranceMetadataProfileRevision.model_validate_json(_json(payload))


def _review_set(payload: object) -> InsuranceMetadataReviewSet:
    return InsuranceMetadataReviewSet.model_validate_json(_json(payload))


def _review(payload: object) -> InsuranceMetadataReviewV2:
    return InsuranceMetadataReviewV2.model_validate_json(_json(payload))


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _revision_uuids(review_set: InsuranceMetadataReviewSet) -> tuple[UUID, UUID]:
    try:
        return UUID(review_set.document_id), UUID(review_set.revision_id)
    except ValueError as exc:
        raise MetadataReviewValidationError(
            "production metadata reviews require UUID document revisions"
        ) from exc


def _review_set_values(
    review_set: InsuranceMetadataReviewSet,
    *,
    document_id: UUID,
    revision_id: UUID,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "source_id": review_set.source_id,
        "review_set_id": review_set.review_set_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "structured_build_id": review_set.structured_build_id,
        "profile_revision_id": review_set.profile_revision_id,
        "generation": review_set.generation,
        "review_set_identity": review_set.review_set_identity,
        "current": True,
        "review_set_json": model_json(review_set),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _review_values(
    review_set_id: str,
    review: InsuranceMetadataReviewV2,
    *,
    document_id: UUID,
    revision_id: UUID,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "source_id": review.source_id,
        "review_id": review.review_id,
        "review_set_id": review_set_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "profile_revision_id": review.profile_revision_id,
        "scope": review.scope,
        "canonical_anchor": review.canonical_anchor,
        "review_version": review.review_version,
        "review_identity": review.review_identity,
        "state": review.state,
        "current": review.current,
        "approved_metadata_revision_id": review.approved_metadata_revision_id,
        "review_json": model_json(review),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _nonblank(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MetadataReviewValidationError(f"{field} must not be blank")
    return normalized


def _encode_cursor(review_id: str) -> str:
    return base64.urlsafe_b64encode(f"review.v2:{review_id}".encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> str:
    if not value or len(value) > 1_024:
        raise MetadataReviewValidationError("metadata review cursor is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise MetadataReviewValidationError("metadata review cursor is invalid") from exc
    prefix = "review.v2:"
    if not decoded.startswith(prefix) or not decoded[len(prefix) :]:
        raise MetadataReviewValidationError("metadata review cursor is invalid")
    return decoded[len(prefix) :]


__all__ = ["PostgresInsuranceMetadataReviewRepository"]
