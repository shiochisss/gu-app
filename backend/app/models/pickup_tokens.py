from sqlalchemy import CheckConstraint, Column, Computed, ForeignKey, UniqueConstraint

from app.db import Base
from app.models.common import OPTIONS, UUID, new_id, string
from app.models.types import UTCDateTime


class PickupToken(Base):
    __tablename__ = "pickup_tokens"
    __table_args__ = (
        CheckConstraint(
            "revoked_reason IN ('REISSUED', 'CANCELLED', 'RETURNED')", name="ck_pickup_tokens_1"
        ),
        UniqueConstraint("active_order_id", name="uq_pickup_tokens_1"),
        OPTIONS,
    )

    token_id = new_id()
    order_id = Column(
        UUID, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    issued_at = Column(UTCDateTime(), nullable=False)
    revoked_at = Column(UTCDateTime(), nullable=True)
    revoked_reason = Column(string(16), nullable=True)
    used_at = Column(UTCDateTime(), nullable=True)
    active_order_id = Column(
        UUID, Computed("CASE WHEN revoked_at IS NULL THEN order_id ELSE NULL END", persisted=True)
    )
