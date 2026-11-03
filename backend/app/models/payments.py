from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, UniqueConstraint, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, flag, new_id, string, version
from app.models.types import UTCDateTime


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("operation_attempt >= 1", name="ck_payments_1"),
        CheckConstraint("authorized_amount_yen >= 0", name="ck_payments_2"),
        CheckConstraint("captured_amount_yen >= 0", name="ck_payments_3"),
        CheckConstraint("released_amount_yen >= 0", name="ck_payments_4"),
        CheckConstraint("refunded_amount_yen >= 0", name="ck_payments_5"),
        UniqueConstraint("order_id", name="uq_payments_1"),
        UniqueConstraint("provider_payment_intent_id", name="uq_payments_2"),
        Index("ix_payments_1", "status", "operation_started_at"),
        choice("status", enums.PAYMENT_STATUS, "ck_payments_status"),
        choice("last_operation", enums.PAYMENT_OPERATION, "ck_payments_last_operation"),
        OPTIONS,
    )

    id = new_id()
    order_id = Column(
        UUID, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    provider = Column(string(16), nullable=False, server_default=text("'STRIPE'"))
    provider_payment_intent_id = Column(string(64), nullable=True)
    status = Column(string(32), nullable=False, server_default=text("'NOT_STARTED'"))
    last_operation = Column(string(32), nullable=True)
    operation_attempt = Column(Integer, nullable=False, server_default=text("1"))
    authorized_confirmed = flag(False)
    failure_code = Column(string(64), nullable=True)
    authorized_amount_yen = Column(Integer, nullable=False)
    captured_amount_yen = Column(Integer, nullable=False, server_default=text("0"))
    released_amount_yen = Column(Integer, nullable=False, server_default=text("0"))
    refunded_amount_yen = Column(Integer, nullable=False, server_default=text("0"))
    provider_refund_id = Column(string(64), nullable=True)
    operation_started_at = Column(UTCDateTime(), nullable=True)
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
