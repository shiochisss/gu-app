from sqlalchemy import CheckConstraint, Column, UniqueConstraint

from app.db import Base
from app.models.common import OPTIONS, new_id, string
from app.models.types import UTCDateTime


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint("result IN ('APPLIED', 'IGNORED', 'ERROR')", name="ck_payment_events_1"),
        UniqueConstraint("provider_event_id", name="uq_payment_events_1"),
        OPTIONS,
    )

    id = new_id()
    provider_event_id = Column(string(64), nullable=False)
    type = Column(string(64), nullable=False)
    payment_intent_id = Column(string(64), nullable=True)
    received_at = Column(UTCDateTime(), nullable=False)
    processed_at = Column(UTCDateTime(), nullable=True)
    processing_until = Column(UTCDateTime(), nullable=True)
    result = Column(string(32), nullable=True)
