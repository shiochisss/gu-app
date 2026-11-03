from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint

from app.db import Base
from app.models.common import OPTIONS, UUID, new_id, string


class PosSaleItem(Base):
    __tablename__ = "pos_sale_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 99", name="ck_pos_sale_items_1"),
        CheckConstraint("unit_price_yen >= 0", name="ck_pos_sale_items_2"),
        UniqueConstraint("pos_sale_id", "product_variant_id", name="uq_pos_sale_items_1"),
        OPTIONS,
    )

    id = new_id()
    pos_sale_id = Column(
        UUID, ForeignKey("pos_sales.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    line_no = Column(Integer, nullable=False)
    product_variant_id = Column(
        UUID,
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=False,
        primary_key=False,
    )
    product_name = Column(string(100), nullable=False)
    sku = Column(string(32), nullable=False)
    color_name = Column(string(32), nullable=False)
    size = Column(string(8), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_yen = Column(Integer, nullable=False)
