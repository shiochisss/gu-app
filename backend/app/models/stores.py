import json

from sqlalchemy import JSON, CheckConstraint, Column, Time, UniqueConstraint, text

from app.db import Base
from app.models.common import OPTIONS, flag, new_id, string, version
from app.models.types import UTCDateTime


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint("default_opens_at < default_closes_at", name="ck_stores_1"),
        CheckConstraint(
            "JSON_SCHEMA_VALID('"
            + json.dumps(
                {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 7},
                    "uniqueItems": True,
                }
            )
            + "', regular_closed_weekdays)",
            name="ck_stores_2",
        ),
        UniqueConstraint("code", name="uq_stores_1"),
        OPTIONS,
    )

    id = new_id()
    code = Column(string(16), nullable=False)
    name = Column(string(100), nullable=False)
    address = Column(string(200), nullable=False)
    timezone = Column(string(64), nullable=False, server_default=text("'Asia/Tokyo'"))
    default_opens_at = Column(Time, nullable=False)
    default_closes_at = Column(Time, nullable=False)
    regular_closed_weekdays = Column(JSON, nullable=False, server_default=text("(JSON_ARRAY())"))
    accepting_orders = flag(True)
    acceptance_reason = Column(string(200), nullable=True)
    acceptance_changed_at = Column(UTCDateTime(), nullable=True)
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
