from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint, text

from app.db import Base
from app.models.common import OPTIONS, UUID, new_id, string


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("ordered_quantity BETWEEN 1 AND 10", name="ck_order_items_1"),
        CheckConstraint("shortage_quantity >= 0", name="ck_order_items_2"),
        CheckConstraint("shortage_quantity <= ordered_quantity", name="ck_order_items_3"),
        CheckConstraint("prepared_quantity >= 0", name="ck_order_items_4"),
        CheckConstraint("unit_price_yen >= 0", name="ck_order_items_5"),
        UniqueConstraint("order_id", "line_no", name="uq_order_items_1"),
        UniqueConstraint("order_id", "product_variant_id", name="uq_order_items_2"),
        OPTIONS,
    )

    id = new_id()
    order_id = Column(
        UUID, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, primary_key=False
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
    unit_price_yen = Column(Integer, nullable=False)
    ordered_quantity = Column(Integer, nullable=False)
    shortage_quantity = Column(Integer, nullable=False, server_default=text("0"))
    prepared_quantity = Column(Integer, nullable=True)
