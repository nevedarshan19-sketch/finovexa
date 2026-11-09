"""Request-scoped business tenancy.

Every row that belongs to a business carries a ``business_id``. Owner and
employee requests resolve one active business before any handler runs; the
ORM hooks below then make the business boundary the default for every SELECT,
UPDATE and DELETE on a scoped model, regardless of how the query is written.

Sessions are also guarded on ``Session.get`` because the identity map can
return an already-loaded row without touching the database.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator

from sqlalchemy import ForeignKey, Integer, event, inspect as sa_inspect
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

_current_business: ContextVar[int | None] = ContextVar(
    "finovexa_current_business", default=None
)
_bypass: ContextVar[bool] = ContextVar("finovexa_tenancy_bypass", default=False)


class BusinessIsolationError(Exception):
    """A request tried to read or write a row owned by another business."""


class BusinessScoped:
    """Mixin for every table that stores business data."""

    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_profiles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


def current_business_id() -> int | None:
    return _current_business.get()


def tenancy_bypassed() -> bool:
    return _bypass.get()


def set_current_business(business_id: int | None) -> None:
    _current_business.set(business_id)


@contextlib.contextmanager
def business_scope(business_id: int | None) -> Iterator[None]:
    token = _current_business.set(business_id)
    try:
        yield
    finally:
        _current_business.reset(token)


@contextlib.contextmanager
def tenancy_bypass() -> Iterator[None]:
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)


def guard_business_row(row: object) -> None:
    """Reject a row that belongs to a different business than the request."""
    business_id = _current_business.get()
    if row is None or business_id is None or _bypass.get():
        return
    if isinstance(row, BusinessScoped) and row.business_id != business_id:
        raise BusinessIsolationError("This record belongs to another business.")


class TenantSession(Session):
    def get(self, entity, ident, **kwargs):  # type: ignore[override]
        row = super().get(entity, ident, **kwargs)
        guard_business_row(row)
        return row


@event.listens_for(Session, "do_orm_execute")
def _scope_statement(state) -> None:
    business_id = _current_business.get()
    if business_id is None or _bypass.get():
        return
    if state.execution_options.get("tenancy_bypass"):
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            BusinessScoped,
            lambda cls: cls.business_id == business_id,
            include_aliases=True,
        )
    )


def _owner_for(*, user_id: int | None, owner_id: int | None, session: Session) -> int | None:
    from .models import User

    if owner_id:
        return owner_id
    if user_id:
        user = session.get(User, user_id)
        if user is not None:
            return user.owner_id if user.role == "employee" else user.id
    return None


def _infer_from_parent(session: Session, row: object) -> int | None:
    mapper = sa_inspect(type(row), raiseerr=False)
    if mapper is None:
        return None
    for rel in mapper.relationships:
        if rel.uselist or rel.direction.name != "MANYTOONE":
            continue
        parent_cls = rel.mapper.class_
        if not issubclass(parent_cls, BusinessScoped):
            continue
        for column in rel.local_columns:
            ident = getattr(row, column.key, None)
            if ident is None:
                continue
            parent = session.get(parent_cls, ident)
            if parent is not None and parent.business_id:
                return parent.business_id
    return None


def _infer_business_id(session: Session, row: object) -> int | None:
    """Attach system-created rows (seeding, webhooks) to the owner's first business."""
    from .models import BusinessProfile

    owner_id = _owner_for(
        user_id=getattr(row, "user_id", None),
        owner_id=getattr(row, "owner_id", None),
        session=session,
    )
    if owner_id is None:
        return _infer_from_parent(session, row)
    business = (
        session.query(BusinessProfile)
        .filter(BusinessProfile.owner_id == owner_id)
        .order_by(BusinessProfile.id)
        .first()
    )
    return business.id if business is not None else None


@event.listens_for(Session, "before_flush")
def _stamp_business_id(session, flush_context, instances) -> None:
    if _bypass.get():
        return
    business_id = _current_business.get()
    for row in list(session.new) + list(session.dirty) + list(session.deleted):
        if not isinstance(row, BusinessScoped):
            continue
        if business_id is not None and row.business_id is None:
            row.business_id = business_id
        elif business_id is None and row.business_id is None:
            row.business_id = _infer_business_id(session, row)
        elif business_id is not None and row.business_id != business_id:
            raise BusinessIsolationError(
                "A record from another business cannot be written in this context."
            )
