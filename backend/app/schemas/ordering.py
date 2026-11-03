from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import ApiModel
from app.schemas.staff import PosLine


class OrderLineInput(ApiModel):
    product_variant_id: UUID
    quantity: Annotated[int, Field(strict=True, ge=1)]


class EstimateInput(ApiModel):
    store_id: UUID
    items: Annotated[list[OrderLineInput], Field(min_length=1)]
    shortage_policy: Literal["CANCEL_ALL", "PURCHASE_AVAILABLE"]

    @model_validator(mode="after")
    def unique(self):
        ids = [x.product_variant_id for x in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate SKU")
        return self


class OrderInput(EstimateInput):
    estimate_id: UUID
    client_total_amount_yen: Annotated[int, Field(strict=True, ge=0)]
    client_estimated_ready_at: AwareDatetime
    confirmation_token_id: Annotated[str, Field(pattern=r"^ctoken_[A-Za-z0-9_]+$", max_length=255)]
    agreed_to_pickup_terms: Annotated[bool, Field(strict=True)]


class EstimateResponse(ApiModel):
    accepted: bool
    rejection_code: str | None = None
    rejection_details: dict | None = None
    estimate_id: str | None = None
    store_id: str
    store_name: str
    items: list[PosLine]
    total_quantity: int
    total_amount_yen: int
    shortage_policy: str
    estimated_ready_at: datetime | None = None
    estimate_expires_at: datetime | None = None
    pickup_deadline_rule_text: str
    overdue_policy_text: str


class NextAction(ApiModel):
    type: Literal["STRIPE_HANDLE_NEXT_ACTION"]
    client_secret: str


class OrderCreated(ApiModel):
    order_id: str
    order_number: str
    status: str
    payment_status: str
    original_ready_at: datetime
    next_action: NextAction | None = None


class PaymentConfirmation(ApiModel):
    order_id: str
    status: str
    payment_status: str
    failure_message: str | None = None


class OrderSummary(ApiModel):
    order_id: str
    order_number: str
    store_name: str
    status: str
    status_label: str
    payment_status: str
    total_quantity: int
    ordered_amount_yen: int
    captured_amount_yen: int | None
    original_ready_at: datetime
    current_ready_at: datetime | None
    is_delayed: bool
    created_at: datetime


class OrderList(ApiModel):
    items: list[OrderSummary]
    page: int
    page_size: int
    total_count: int


class OrderStore(ApiModel):
    store_id: str
    name: str
    address: str


class OrderItemInfo(ApiModel):
    order_item_id: str
    product_name: str
    sku: str
    color_name: str
    size: str
    unit_price_yen: int
    ordered_quantity: int
    shortage_quantity: int
    prepared_quantity: int | None


class DelayInfo(ApiModel):
    source: str
    reason_text: str
    new_ready_at: datetime | None
    registered_at: datetime


class PickupInfo(ApiModel):
    qr_value: str
    manual_code: str


class OrderDetail(ApiModel):
    order_id: str
    order_number: str
    status: str
    status_label: str
    payment_status: str
    payment_status_label: str
    store: OrderStore
    items: list[OrderItemInfo]
    total_quantity: int
    ordered_amount_yen: int
    captured_amount_yen: int | None
    shortage_policy: str
    created_at: datetime
    accepted_at: datetime | None
    original_ready_at: datetime
    updated_ready_at: datetime | None
    ready_at: datetime | None
    pickup_deadline_at: datetime | None
    picked_up_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason_label: str | None
    is_delayed: bool
    delay_occurred: bool
    delays: list[DelayInfo]
    pickup: PickupInfo | None
    can_cancel: bool
    can_reissue_pickup_code: bool
    version: int


class MailInfo(ApiModel):
    notification_id: str
    type: str
    recipient_email: str
    subject: str
    body_text: str
    status: str
    attempt_count: int
    sent_at: datetime | None
    created_at: datetime
    order_id: str
    order_number: str


class MailList(ApiModel):
    items: list[MailInfo]
