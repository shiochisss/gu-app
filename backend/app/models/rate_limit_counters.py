from sqlalchemy import CheckConstraint, Column, Integer

from app.db import Base
from app.models.common import OPTIONS, string
from app.models.types import UTCDateTime


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"
    __table_args__ = (
        CheckConstraint("count >= 0", name="ck_rate_limit_counters_1"),
        OPTIONS,
    )

    key = Column(string(200), nullable=False, primary_key=True)
    window_started_at = Column(UTCDateTime(), nullable=False)
    count = Column(Integer, nullable=False)
