from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class CreatedAtMixin:
    """Adds `created_at`, set once at insert time. Mix into any model that
    needs a creation timestamp but never mutates it afterward.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """Adds `updated_at` on top of `CreatedAtMixin`, bumped automatically on
    every row update. Mix into any model whose rows are edited after
    creation (as opposed to write-once/append-only rows like tokens).
    """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
