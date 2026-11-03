from sqlalchemy import Column, ForeignKey

from app.db import Base
from app.models.common import OPTIONS, UUID


class StaffProfile(Base):
    __tablename__ = "staff_profiles"
    __table_args__ = (OPTIONS,)

    user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=True
    )
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
