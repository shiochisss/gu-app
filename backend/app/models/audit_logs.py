from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Index

from app.db import Base
from app.models.common import OPTIONS, UUID, new_id, string
from app.models.types import UTCDateTime


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('ORDER', 'INVENTORY', 'POS_SALE', "
            "'STORE', 'BUSINESS_HOURS', 'PAYMENT')",
            name="ck_audit_logs_1",
        ),
        CheckConstraint("actor_type IN ('CUSTOMER', 'STAFF', 'SYSTEM')", name="ck_audit_logs_2"),
        Index("ix_audit_logs_1", "target_type", "target_id", "occurred_at"),
        OPTIONS,
    )

    id = new_id()
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    target_type = Column(string(32), nullable=False)
    target_id = Column(UUID, nullable=False)
    action = Column(string(64), nullable=False)
    actor_user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    actor_type = Column(string(16), nullable=False)
    before_value = Column(JSON(none_as_null=True), nullable=True)
    after_value = Column(JSON(none_as_null=True), nullable=True)
    reason = Column(string(200), nullable=True)
    occurred_at = Column(UTCDateTime(), nullable=False)
