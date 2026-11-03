from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, UniqueConstraint, text

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, new_id, string
from app.models.types import UTCDateTime


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="ck_inventory_reservations_1"),
        CheckConstraint("consumed_quantity >= 0", name="ck_inventory_reservations_2"),
        CheckConstraint("shortage_quantity >= 0", name="ck_inventory_reservations_3"),
        UniqueConstraint("order_item_id", name="uq_inventory_reservations_1"),
        choice("status", enums.RESERVATION_STATUS, "ck_inventory_reservations_status"),
        OPTIONS,
    )

    id = new_id()
    order_item_id = Column(
        UUID, ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    inventory_id = Column(
        UUID, ForeignKey("inventories.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    quantity = Column(Integer, nullable=False)
    status = Column(string(32), nullable=False, server_default=text("'HELD'"))
    consumed_quantity = Column(Integer, nullable=False, server_default=text("0"))
    shortage_quantity = Column(Integer, nullable=False, server_default=text("0"))
    expires_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False)
    updated_at = Column(UTCDateTime(), nullable=False)
