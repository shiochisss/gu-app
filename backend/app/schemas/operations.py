from datetime import time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import ApiModel
from app.schemas.ordering import OrderDetail, OrderItemInfo
from app.schemas.staff import Version


class VersionInput(ApiModel):
    version: Version


class ShortageItem(ApiModel):
    order_item_id: UUID
    shortage_quantity: Annotated[int, Field(strict=True, ge=0)]


class ShortageInput(VersionInput):
    items: Annotated[list[ShortageItem], Field(min_length=1)]

    @model_validator(mode="after")
    def unique(self):
        ids = [x.order_item_id for x in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate order item")
        return self


class DelayInput(VersionInput):
    reason_code: Literal["STAFF_SHORTAGE", "CONGESTION", "STOCK_CHECK", "OTHER"]
    reason_text: Annotated[str, Field(max_length=200)] | None = None
    updated_ready_at: AwareDatetime | None = None


class AcceptanceInput(VersionInput):
    accepting_orders: Annotated[bool, Field(strict=True)]
    reason: Annotated[str, Field(max_length=200)] | None = None


class HoursInput(ApiModel):
    use_default: Annotated[bool, Field(strict=True)]
    closed: Annotated[bool, Field(strict=True)] = False
    opens_at: time | None = None
    closes_at: time | None = None
    version: Version | None = None

    @model_validator(mode="after")
    def hours(self):
        if not self.use_default and not self.closed:
            if self.opens_at is None or self.closes_at is None:
                raise ValueError("hours required")
            if (
                self.opens_at.tzinfo
                or self.closes_at.tzinfo
                or self.opens_at >= self.closes_at
                or self.opens_at.second
                or self.opens_at.microsecond
                or self.closes_at.second
                or self.closes_at.microsecond
            ):
                raise ValueError("invalid hours")
        return self


class VerifyInput(ApiModel):
    qr_value: Annotated[str, Field(max_length=1024)] | None = None
    order_number: Annotated[str, Field(pattern=r"^P[0-9]{6,15}$")] | None = None
    manual_code: Annotated[str, Field(pattern=r"^[0-9]{6}$")] | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if self.qr_value is not None:
            if self.order_number is not None or self.manual_code is not None:
                raise ValueError("choose QR or manual")
        elif not self.order_number or not self.manual_code:
            raise ValueError("manual credentials required")
        return self


class HandoverInput(VersionInput):
    pickup_verification_id: UUID


class StaffItem(OrderItemInfo):
    shortage_risk_quantity: int
    on_hand_quantity: int


class PaymentInfo(ApiModel):
    status: str
    authorized_amount_yen: int
    captured_amount_yen: int
    failure_code: str | None


class StaffOrderDetail(OrderDetail):
    pickup: None = Field(default=None, exclude=True)
    can_cancel: bool = Field(default=False, exclude=True)
    can_reissue_pickup_code: bool = Field(default=False, exclude=True)
    items: list[StaffItem]
    payment: PaymentInfo
    allowed_actions: list[str]


class StaffOrderSummary(ApiModel):
    order_id: str
    order_number: str
    status: str
    status_label: str
    accepted_at: str | None
    original_ready_at: str
    current_ready_at: str | None
    is_delayed: bool
    delay_pending: bool
    total_quantity: int
    shortage_risk: bool
    pickup_deadline_at: str | None


class StaffOrderList(ApiModel):
    items: list[StaffOrderSummary]
    tab_counts: dict[str, int]
    page: int
    page_size: int
    total_count: int


class VerifiedItem(ApiModel):
    product_name: str
    color_name: str
    size: str
    prepared_quantity: int


class Verification(ApiModel):
    can_hand_over: bool
    reason_code: str | None = None
    reason_message: str | None = None
    pickup_verification_id: str | None = None
    order_id: str | None = None
    order_number: str | None = None
    status: str | None = None
    items: list[VerifiedItem] | None = None
    captured_amount_yen: int | None = None
    pickup_deadline_at: str | None = None
    version: int | None = None


class HandoverResult(ApiModel):
    order_id: str
    order_number: str
    status: str
    picked_up_at: str


class HoursDay(ApiModel):
    date: str
    closed: bool
    opens_at: str | None
    closes_at: str | None
    source: str
    override_version: int | None


class DefaultHours(ApiModel):
    opens_at: str
    closes_at: str
    regular_closed_weekdays: list[int]


class StaffStore(ApiModel):
    store_id: str
    name: str
    accepting_orders: bool
    acceptance_reason: str | None
    acceptance_changed_at: str | None
    version: int
    default_hours: DefaultHours
    days: list[HoursDay]
    warnings: list[str] = Field(default_factory=list)


class JobsInput(ApiModel):
    jobs: list[Literal["J-01", "J-02", "J-03", "J-04", "J-05", "J-06", "J-07"]] = Field(
        default_factory=lambda: ["J-01", "J-02", "J-03", "J-04", "J-05"]
    )


class JobResult(ApiModel):
    job: str
    result: str
    processed_count: int


class JobsResult(ApiModel):
    results: list[JobResult]
