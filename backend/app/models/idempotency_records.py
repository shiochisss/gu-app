from sqlalchemy import JSON, Column, ForeignKey, Integer

from app.db import Base
from app.models.common import HASH, OPTIONS, UUID, string
from app.models.types import UTCDateTime


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (OPTIONS,)

    user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, primary_key=True
    )
    endpoint = Column(string(200), nullable=False, primary_key=True)
    idempotency_key = Column(UUID, nullable=False, primary_key=True)
    request_hash = Column(HASH, nullable=False)
    response_status = Column(Integer, nullable=True)
    locked_until = Column(UTCDateTime(), nullable=False)
    response_body = Column(JSON(none_as_null=True), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False)
