from sqlalchemy import CheckConstraint, Column, Integer

from app.db import Base
from app.models.common import OPTIONS, new_id, string
from app.models.types import UTCDateTime


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("result IN ('SUCCESS', 'SKIPPED_LOCKED', 'ERROR')", name="ck_job_runs_1"),
        CheckConstraint("processed_count >= 0", name="ck_job_runs_2"),
        OPTIONS,
    )

    id = new_id()
    job_code = Column(string(8), nullable=False)
    started_at = Column(UTCDateTime(), nullable=False)
    finished_at = Column(UTCDateTime(), nullable=True)
    result = Column(string(16), nullable=True)
    processed_count = Column(Integer, nullable=True)
    error_message = Column(string(500), nullable=True)
