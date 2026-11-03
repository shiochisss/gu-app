from sqlalchemy import Column, ForeignKey, Index

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, new_id, string
from app.models.types import UTCDateTime


class OrderDelay(Base):
    __tablename__ = "order_delays"

    id = new_id()
    order_id = Column(
        UUID, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    source = Column(string(32), nullable=False)
    reason_code = Column(string(32), nullable=False)
    reason_text = Column(string(200), nullable=False)
    new_ready_at = Column(UTCDateTime(), nullable=True)
    registered_by = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    registered_at = Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        Index("ix_order_delays_1", "order_id", registered_at.desc()),
        choice("source", enums.DELAY_SOURCE, "ck_order_delays_source"),
        choice("reason_code", enums.DELAY_REASON_CODE, "ck_order_delays_reason_code"),
        OPTIONS,
    )
