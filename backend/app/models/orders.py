from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, UniqueConstraint, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, flag, new_id, string, version
from app.models.types import UTCDateTime


class Order(Base):
    __tablename__ = "orders"

    id = new_id()
    order_number = Column(string(16), nullable=False)
    purchaser_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    estimate_id = Column(
        UUID,
        ForeignKey("order_estimates.id", ondelete="RESTRICT"),
        nullable=False,
        primary_key=False,
    )
    status = Column(string(32), nullable=False, server_default=text("'PENDING_PAYMENT'"))
    shortage_policy = Column(string(32), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    ordered_amount_yen = Column(Integer, nullable=False)
    captured_amount_yen = Column(Integer, nullable=True)
    work_minutes = Column(Integer, nullable=False)
    pickup_terms_agreed_at = Column(UTCDateTime(), nullable=False)
    hold_expires_at = Column(UTCDateTime(), nullable=False)
    accepted_at = Column(UTCDateTime(), nullable=True)
    original_ready_at = Column(UTCDateTime(), nullable=False)
    updated_ready_at = Column(UTCDateTime(), nullable=True)
    preparation_started_at = Column(UTCDateTime(), nullable=True)
    ready_at = Column(UTCDateTime(), nullable=True)
    pickup_deadline_at = Column(UTCDateTime(), nullable=True)
    picked_up_at = Column(UTCDateTime(), nullable=True)
    handed_over_by = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    cancelled_at = Column(UTCDateTime(), nullable=True)
    cancel_reason_code = Column(string(32), nullable=True)
    expired_at = Column(UTCDateTime(), nullable=True)
    returned_to_stock_at = Column(UTCDateTime(), nullable=True)
    is_delayed = flag(False)
    delay_occurred = flag(False)
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("total_quantity BETWEEN 1 AND 10", name="ck_orders_1"),
        CheckConstraint("ordered_amount_yen >= 0", name="ck_orders_2"),
        CheckConstraint("captured_amount_yen >= 0", name="ck_orders_3"),
        UniqueConstraint("order_number", name="uq_orders_1"),
        UniqueConstraint("estimate_id", name="uq_orders_2"),
        Index("ix_orders_1", "purchaser_id", created_at.desc()),
        Index("ix_orders_2", "store_id", "status", "accepted_at"),
        Index("ix_orders_3", "status", "hold_expires_at"),
        Index("ix_orders_4", "status", "pickup_deadline_at"),
        choice("status", enums.ORDER_STATUS, "ck_orders_status"),
        choice("shortage_policy", enums.SHORTAGE_POLICY, "ck_orders_shortage_policy"),
        choice("cancel_reason_code", enums.CANCEL_REASON_CODE, "ck_orders_cancel_reason_code"),
        OPTIONS,
    )
