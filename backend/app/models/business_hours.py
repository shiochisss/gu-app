from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Time, UniqueConstraint

from app.db import Base
from app.models.common import OPTIONS, UUID, flag, new_id, version
from app.models.types import UTCDateTime


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint(
            "(closed AND opens_at IS NULL AND closes_at IS NULL) OR "
            "(NOT closed AND opens_at IS NOT NULL "
            "AND closes_at IS NOT NULL AND opens_at < closes_at)",
            name="ck_business_hours_1",
        ),
        UniqueConstraint("store_id", "business_date", name="uq_business_hours_1"),
        OPTIONS,
    )

    id = new_id()
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    business_date = Column(Date, nullable=False)
    closed = flag(False)
    opens_at = Column(Time, nullable=True)
    closes_at = Column(Time, nullable=True)
    updated_by = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
