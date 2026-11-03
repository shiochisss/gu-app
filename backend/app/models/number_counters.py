from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
)
from sqlalchemy.dialects.mysql import VARCHAR

from app.db import Base
from app.models.common import OPTIONS


class NumberCounter(Base):
    __tablename__ = "number_counters"
    __table_args__ = (
        CheckConstraint("next_value >= 1", name="ck_number_counters_1"),
        OPTIONS,
    )

    name = Column(
        VARCHAR(32, charset="ascii", collation="ascii_bin"), nullable=False, primary_key=True
    )
    next_value = Column(BigInteger, nullable=False)
