from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint

from app.db import Base
from app.models.common import HASH, OPTIONS, UUID, new_id
from app.models.types import UTCDateTime


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_1"),
        Index("ix_refresh_tokens_1", "user_id"),
        OPTIONS,
    )

    id = new_id()
    user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    token_hash = Column(HASH, nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
    revoked_at = Column(UTCDateTime(), nullable=True)
    replaced_by_id = Column(
        UUID, ForeignKey("refresh_tokens.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    created_at = Column(UTCDateTime(), nullable=False)
