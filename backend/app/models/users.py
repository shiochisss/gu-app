from sqlalchemy import Column, UniqueConstraint, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, choice, new_id, string
from app.models.types import UTCDateTime


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_1"),
        choice("role", enums.USER_ROLE, "ck_users_role"),
        choice("status", enums.USER_STATUS, "ck_users_status"),
        OPTIONS,
    )

    id = new_id()
    email = Column(string(254), nullable=False)
    password_hash = Column(string(255), nullable=False)
    role = Column(string(32), nullable=False)
    status = Column(string(32), nullable=False, server_default=text("'ACTIVE'"))
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
