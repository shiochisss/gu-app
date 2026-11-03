from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint, text

from app.db import Base
from app.models.common import OPTIONS, UUID, new_id, version
from app.models.types import UTCDateTime


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (
        CheckConstraint("on_hand_quantity >= 0", name="ck_inventories_1"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventories_2"),
        UniqueConstraint("store_id", "product_variant_id", name="uq_inventories_1"),
        OPTIONS,
    )

    id = new_id()
    store_id = Column(
        UUID, ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    product_variant_id = Column(
        UUID,
        ForeignKey("product_variants.id", ondelete="RESTRICT"),
        nullable=False,
        primary_key=False,
    )
    on_hand_quantity = Column(Integer, nullable=False, server_default=text("0"))
    reserved_quantity = Column(Integer, nullable=False, server_default=text("0"))
    version = version()
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
    updated_at = Column(UTCDateTime(), nullable=False)
