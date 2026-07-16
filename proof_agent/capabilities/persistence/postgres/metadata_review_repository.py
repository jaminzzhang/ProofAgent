from __future__ import annotations

import base64
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
import json
from typing import Literal

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.knowledge.hybrid.workbook import (
    InsuranceMetadataReview,
    InsuranceMetadataReviewPage,
    InsuranceMetadataReviewSummary,
    WorkbookReviewConflictError,
    WorkbookValidationError,
    resolve_insurance_metadata_review,
    validate_insurance_metadata_review_identity,
)
from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import hybrid_metadata_reviews
from proof_agent.contracts.persistence import PersistenceInvariantError


_STATES = frozenset(
    {"review_required", "ready_for_review", "approved", "corrected", "rejected"}
)


class PostgresInsuranceMetadataReviewRepository:
    """Transactional PostgreSQL authority for exact insurance metadata decisions."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connection_source = connection_source
        self._clock = clock

    def list(self, source_id: str) -> tuple[InsuranceMetadataReview, ...]:
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(
                select(hybrid_metadata_reviews.c.review_json)
                .where(hybrid_metadata_reviews.c.source_id == source_id)
                .order_by(hybrid_metadata_reviews.c.review_id)
            ).scalars()
        return tuple(_review(payload) for payload in rows)

    def list_page(
        self,
        source_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        state: str | None = None,
        import_id: str | None = None,
    ) -> InsuranceMetadataReviewPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkbookValidationError("metadata review page limit must be between 1 and 100")
        if state is not None and state not in _STATES:
            raise WorkbookValidationError("metadata review state filter is invalid")
        after = _decode_cursor(cursor) if cursor is not None else None
        conditions = [hybrid_metadata_reviews.c.source_id == source_id]
        if state is not None:
            conditions.append(hybrid_metadata_reviews.c.state == state)
        if import_id is not None:
            if not import_id.strip() or len(import_id) > 512:
                raise WorkbookValidationError("metadata import filter is invalid")
            conditions.append(
                hybrid_metadata_reviews.c.review_json["import_id"].astext == import_id
            )
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
                select(
                    hybrid_metadata_reviews.c.state,
                    func.count().label("count"),
                )
                .where(hybrid_metadata_reviews.c.source_id == source_id)
                .group_by(hybrid_metadata_reviews.c.state)
            ).all()
        has_more = len(payloads) > limit
        items = tuple(_review(payload) for payload in payloads[:limit])
        return InsuranceMetadataReviewPage(
            items=items,
            next_cursor=(
                _encode_cursor(items[-1].review_id) if has_more and items else None
            ),
            total=total,
            summary=_summary(
                {str(row[0]): int(row[1]) for row in summary_rows}
            ),
        )

    def get(self, source_id: str, review_id: str) -> InsuranceMetadataReview | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                select(hybrid_metadata_reviews.c.review_json).where(
                    hybrid_metadata_reviews.c.source_id == source_id,
                    hybrid_metadata_reviews.c.review_id == review_id,
                )
            ).scalar_one_or_none()
        return None if payload is None else _review(payload)

    def put(self, review: InsuranceMetadataReview) -> InsuranceMetadataReview:
        return self.put_many((review,))[0]

    def put_many(
        self,
        reviews: Iterable[InsuranceMetadataReview],
    ) -> tuple[InsuranceMetadataReview, ...]:
        batch = tuple(reviews)
        if not batch:
            raise WorkbookValidationError("metadata review batch must not be empty")
        identities = {(review.source_id, review.review_id) for review in batch}
        if len(identities) != len(batch):
            raise WorkbookValidationError("metadata review batch contains duplicate identities")
        for review in batch:
            validate_insurance_metadata_review_identity(review)
        now = self._now()
        with write_connection(self._connection_source) as connection:
            for review in batch:
                existing = connection.execute(
                    select(hybrid_metadata_reviews.c.review_json)
                    .where(
                        hybrid_metadata_reviews.c.source_id == review.source_id,
                        hybrid_metadata_reviews.c.review_id == review.review_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if existing is not None:
                    if _review(existing) != review:
                        raise WorkbookReviewConflictError(
                            "metadata review identity already exists"
                        )
                    continue
                inserted = connection.execute(
                    postgres_insert(hybrid_metadata_reviews)
                    .values(**_values(review, created_at=now, updated_at=now))
                    .on_conflict_do_nothing()
                    .returning(hybrid_metadata_reviews.c.review_id)
                ).scalar_one_or_none()
                if inserted is None:
                    raise WorkbookReviewConflictError(
                        "metadata review identity already exists"
                    )
        return batch

    def resolve(
        self,
        *,
        source_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        action: Literal["approve", "correct", "reject"],
        actor: str,
        reason: str,
        corrections: Mapping[str, str | int | None] | None = None,
    ) -> InsuranceMetadataReview:
        now = self._now()
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                select(hybrid_metadata_reviews)
                .where(
                    hybrid_metadata_reviews.c.source_id == source_id,
                    hybrid_metadata_reviews.c.review_id == review_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(review_id)
            current = _review(row["review_json"])
            updated, _decision = resolve_insurance_metadata_review(
                current,
                expected_review_version=expected_review_version,
                expected_review_identity=expected_review_identity,
                action=action,
                actor=actor,
                reason=reason,
                corrections=corrections,
            )
            changed = connection.execute(
                update(hybrid_metadata_reviews)
                .where(
                    hybrid_metadata_reviews.c.source_id == source_id,
                    hybrid_metadata_reviews.c.review_id == review_id,
                    hybrid_metadata_reviews.c.review_version == expected_review_version,
                    hybrid_metadata_reviews.c.review_identity == expected_review_identity,
                )
                .values(**_values(updated, created_at=row["created_at"], updated_at=now))
            )
            if changed.rowcount != 1:
                raise WorkbookReviewConflictError(
                    "metadata review changed; reload exact identity"
                )
        return updated

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise PersistenceInvariantError("metadata review clock must be timezone-aware")
        return now


def _values(
    review: InsuranceMetadataReview,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    try:
        from uuid import UUID

        document_id = UUID(review.document_id)
        revision_id = UUID(review.revision_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise PersistenceInvariantError(
            "production metadata reviews require UUID document revisions"
        ) from exc
    return {
        "source_id": review.source_id,
        "review_id": review.review_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "review_version": review.review_version,
        "review_identity": review.review_identity,
        "state": review.state,
        "publication_blocked": review.publication_blocked,
        "review_json": model_json(review),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _review(payload: object) -> InsuranceMetadataReview:
    return InsuranceMetadataReview.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _summary(counts: Mapping[str, int]) -> InsuranceMetadataReviewSummary:
    values = {state: int(counts.get(state, 0)) for state in _STATES}
    total = sum(values.values())
    unresolved = total - values["approved"]
    return InsuranceMetadataReviewSummary(
        total=total,
        unresolved=unresolved,
        review_required=values["review_required"],
        ready_for_review=values["ready_for_review"],
        approved=values["approved"],
        corrected=values["corrected"],
        rejected=values["rejected"],
        all_approved=total > 0 and unresolved == 0,
    )


def _encode_cursor(review_id: str) -> str:
    return base64.urlsafe_b64encode(f"review.v1:{review_id}".encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> str:
    if not value or len(value) > 512:
        raise WorkbookValidationError("metadata review cursor is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise WorkbookValidationError("metadata review cursor is invalid") from exc
    prefix = "review.v1:"
    review_id = decoded.removeprefix(prefix)
    if not decoded.startswith(prefix) or not review_id or len(review_id) > 512:
        raise WorkbookValidationError("metadata review cursor is invalid")
    return review_id


__all__ = ["PostgresInsuranceMetadataReviewRepository"]
