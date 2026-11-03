from sqlalchemy import Column, Index, text
from sqlalchemy.dialects.mysql import CHAR

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, choice, flag, new_id, string
from app.models.types import UTCDateTime


class Product(Base):
    __tablename__ = "products"

    id = new_id()
    name = Column(string(100), nullable=False)
    category = Column(string(32), nullable=False)
    description = Column(string(1000), nullable=False, server_default=text("''"))
    image_color = Column(CHAR(7, charset="utf8mb4", collation="utf8mb4_0900_bin"), nullable=False)
    is_active = flag(True)
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        Index("ix_products_1", "category"),
        Index("ix_products_2", created_at.desc()),
        choice("category", enums.CATEGORY, "ck_products_category"),
        OPTIONS,
    )
