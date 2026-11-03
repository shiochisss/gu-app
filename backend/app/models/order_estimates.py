from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Index, Integer, text

from app.db import Base
from app.models import enums
from app.models.common import HASH, OPTIONS, UUID, choice, new_id, string
from app.models.types import UTCDateTime


class OrderEstimate(Base):
    __tablename__ = "order_estimates"
    __table_args__ = (
        CheckConstraint("total_quantity BETWEEN 1 AND 10", name="ck_order_estimates_1"),
        CheckConstraint("total_amount_yen >= 0", name="ck_order_estimates_2"),
        Index("ix_order_estimates_1", "store_id", "status", "expires_at"),
        choice("status", enums.ESTIMATE_STATUS, "ck_order_estimates_status"),
        choice("shortage_policy", enums.SHORTAGE_POLICY, "ck_order_estimates_shortage_policy"),
        OPTIONS,
    )

    id = new_id()
    user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    request_hash = Column(HASH, nullable=False)
    items = Column(JSON, nullable=False)
    shortage_policy = Column(string(32), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    total_amount_yen = Column(Integer, nullable=False)
    work_minutes = Column(Integer, nullable=False)
    estimated_ready_at = Column(UTCDateTime(), nullable=False)
    status = Column(string(32), nullable=False, server_default=text("'HELD'"))
    created_at = Column(UTCDateTime(), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
