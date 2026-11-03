from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer

from app.db import Base
from app.models import enums
from app.models.common import OPTIONS, UUID, choice, new_id, string
from app.models.types import UTCDateTime


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id = new_id()
    inventory_id = Column(
        UUID, ForeignKey("inventories.id", ondelete="RESTRICT"), nullable=False, primary_key=False
    )
    type = Column(string(32), nullable=False)
    quantity_delta = Column(Integer, nullable=False)
    on_hand_after = Column(Integer, nullable=False)
    counted_quantity = Column(Integer, nullable=True)
    reference_type = Column(string(32), nullable=True)
    reference_id = Column(UUID, nullable=True)
    reason = Column(string(200), nullable=True)
    actor_user_id = Column(
        UUID, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, primary_key=False
    )
    occurred_at = Column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "quantity_delta <> 0 OR type = 'STOCKTAKE'", name="ck_inventory_transactions_1"
        ),
        CheckConstraint("on_hand_after >= 0", name="ck_inventory_transactions_2"),
        CheckConstraint("counted_quantity >= 0", name="ck_inventory_transactions_3"),
        Index("ix_inventory_transactions_1", "inventory_id", occurred_at.desc()),
        choice("type", enums.INVENTORY_TX_TYPE, "ck_inventory_transactions_type"),
        OPTIONS,
    )
