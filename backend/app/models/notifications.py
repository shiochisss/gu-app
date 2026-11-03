from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, Text, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, new_id, string
from app.models.types import UTCDateTime


class Notification(Base):
    __tablename__ = "notifications"

    id = new_id()
    order_id = Column(
        UUID, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    type = Column(string(32), nullable=False)
    recipient_email = Column(string(254), nullable=False)
    subject = Column(string(200), nullable=False)
    body_text = Column(Text(collation="utf8mb4_0900_bin"), nullable=False)
    status = Column(string(32), nullable=False, server_default=text("'PENDING'"))
    attempt_count = Column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at = Column(UTCDateTime(), nullable=False)
    last_error_code = Column(string(64), nullable=True)
    sent_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_notifications_1"),
        Index("ix_notifications_1", "status", "next_attempt_at"),
        Index("ix_notifications_2", "user_id", created_at.desc()),
        choice("type", enums.NOTIFICATION_TYPE, "ck_notifications_type"),
        choice("status", enums.NOTIFICATION_STATUS, "ck_notifications_status"),
        OPTIONS,
    )
