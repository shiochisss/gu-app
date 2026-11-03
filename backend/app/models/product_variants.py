from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.mysql import CHAR

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, flag, new_id, string
from app.models.types import UTCDateTime


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("price_yen >= 1", name="ck_product_variants_1"),
        UniqueConstraint("sku", name="uq_product_variants_1"),
        UniqueConstraint("product_id", "color_name", "size", name="uq_product_variants_2"),
        choice("size", enums.SIZE, "ck_product_variants_size"),
        OPTIONS,
    )

    id = new_id()
    product_id = Column(
        UUID, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    sku = Column(string(32), nullable=False)
    color_name = Column(string(32), nullable=False)
    color_hex = Column(CHAR(7, charset="utf8mb4", collation="utf8mb4_0900_bin"), nullable=False)
    size = Column(string(8), nullable=False)
    price_yen = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    is_active = flag(True)
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
