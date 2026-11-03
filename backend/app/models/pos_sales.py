from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, UniqueConstraint, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, new_id, string, version
from app.models.types import UTCDateTime


class PosSale(Base):
    __tablename__ = "pos_sales"

    id = new_id()
    sale_number = Column(string(16), nullable=False)
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    staff_user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    status = Column(string(32), nullable=False, server_default=text("'COMPLETED'"))
    payment_method = Column(string(32), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    total_amount_yen = Column(Integer, nullable=False)
    sold_at = Column(UTCDateTime(), nullable=False)
    voided_at = Column(UTCDateTime(), nullable=True)
    voided_by = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    void_reason = Column(string(200), nullable=True)
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}

    __table_args__ = (
        CheckConstraint("total_quantity >= 0", name="ck_pos_sales_1"),
        CheckConstraint("total_amount_yen >= 0", name="ck_pos_sales_2"),
        UniqueConstraint("sale_number", name="uq_pos_sales_1"),
        Index("ix_pos_sales_1", "store_id", sold_at.desc()),
        choice("status", enums.POS_SALE_STATUS, "ck_pos_sales_status"),
        choice("payment_method", enums.POS_PAYMENT_METHOD, "ck_pos_sales_payment_method"),
        OPTIONS,
    )
