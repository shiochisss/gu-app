from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import ApiModel

Positive = Annotated[int, Field(strict=True, ge=1)]
Version = Annotated[int, Field(strict=True, ge=0)]
Reason = Annotated[str, Field(max_length=200)]


class PosItem(ApiModel):
    product_variant_id: UUID
    quantity: Annotated[int, Field(strict=True, ge=1, le=99)]


class PosEstimateInput(ApiModel):
    items: Annotated[list[PosItem], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_items(self):
        ids = [item.product_variant_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate SKU")
        return self


class PosSaleInput(PosEstimateInput):
    client_total_amount_yen: Annotated[int, Field(strict=True, ge=0)]
    payment_method: Literal["CASH", "CARD", "OTHER"]


class VoidInput(ApiModel):
    reason: Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
    version: Version


class ReceiptInput(ApiModel):
    quantity: Annotated[int, Field(strict=True, ge=1, le=9999)]
    reason: Reason | None = None
    version: Version


class StocktakeInput(ApiModel):
    type: Literal["STOCKTAKE"]
    counted_quantity: Annotated[int, Field(strict=True, ge=0, le=99999)]
    reason: Reason | None = None
    version: Version


class DamageInput(ApiModel):
    type: Literal["DAMAGE"]
    quantity: Positive
    reason: Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
    version: Version


AdjustmentInput = Annotated[StocktakeInput | DamageInput, Field(discriminator="type")]


class StaffProduct(ApiModel):
    product_variant_id: str
    sku: str
    product_name: str
    color_name: str
    size: str
    price_yen: int
    inventory_id: str
    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int


class InventoryInfo(StaffProduct):
    shortage_risk_quantity: int
    version: int
    updated_at: str


class InventoryList(ApiModel):
    items: list[InventoryInfo]
    page: int
    page_size: int
    total_count: int


class StaffProductList(ApiModel):
    items: list[StaffProduct]
    page: int
    page_size: int
    total_count: int


class PosLine(ApiModel):
    product_variant_id: str
    sku: str
    product_name: str
    color_name: str
    size: str
    unit_price_yen: int
    quantity: int
    line_amount_yen: int


class EstimateLine(PosLine):
    available_quantity: int
    reserved_quantity: int
    ok: bool
    reason_code: str | None


class PosEstimate(ApiModel):
    lines: list[EstimateLine]
    total_quantity: int
    total_amount_yen: int
    all_ok: bool


class SaleInfo(ApiModel):
    sale_id: str
    sale_number: str
    status: str
    total_quantity: int
    total_amount_yen: int
    payment_method: str
    sold_at: str
    lines: list[PosLine]


class SaleDetail(SaleInfo):
    voided_at: str | None
    void_reason: str | None
    staff_email: str
    version: int
    can_void: bool


class SaleSummary(ApiModel):
    completed_count: int
    completed_amount_yen: int
    voided_count: int


class SaleList(ApiModel):
    items: list[SaleDetail]
    page: int
    page_size: int
    total_count: int
    summary: SaleSummary


class TransactionInfo(ApiModel):
    transaction_id: str
    type: str
    type_label: str
    quantity_delta: int
    on_hand_after: int
    counted_quantity: int | None
    reference_label: str | None
    reason: str | None
    actor_email: str | None
    occurred_at: str


class TransactionList(ApiModel):
    inventory: InventoryInfo
    items: list[TransactionInfo]
    page: int
    page_size: int
    total_count: int


class AdjustmentResult(ApiModel):
    inventory: InventoryInfo
    transaction_id: str
    shortage_risk_quantity: int
    shortage_risk_order_count: int
