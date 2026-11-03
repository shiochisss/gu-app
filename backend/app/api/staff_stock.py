from datetime import date as Date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Inventory, InventoryTransaction, Product, ProductVariant, StaffProfile, User
from app.schemas.staff import (
    AdjustmentInput,
    AdjustmentResult,
    InventoryList,
    PosEstimate,
    PosEstimateInput,
    PosSaleInput,
    ReceiptInput,
    SaleDetail,
    SaleInfo,
    SaleList,
    StaffProductList,
    TransactionList,
    VoidInput,
)
from app.security.auth import current_user
from app.services import stock_pos as service
from app.services.idempotency import execute

router = APIRouter(prefix="/api/v1/staff", tags=["staff stock and POS"])
DB = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Key = Annotated[str | None, Header(alias="Idempotency-Key")]


def staff(user: Annotated[User, Depends(current_user)], db: DB):
    if user.role != "STAFF":
        raise ApiError(403, "FORBIDDEN")
    return user, db.get(StaffProfile, user.id).store_id


Staff = Annotated[tuple, Depends(staff)]


async def raw_body(request: Request):
    # Hash the actual JSON, including additional fields, rather than model defaults.
    request.state.idempotency_body = await request.json()


@router.get("/products", response_model=StaffProductList)
def products(
    db: DB,
    identity: Staff,
    sku: str | None = Query(None, max_length=32),
    q: str | None = Query(None, max_length=100),
    page: Page = 1,
    pageSize: PageSize = 20,
):
    if not (sku or "").strip() and not (q or "").strip():
        raise ApiError(400, "VALIDATION_ERROR")
    stmt = service.catalog_query(identity[1], active=True)
    if sku:
        stmt = stmt.where(ProductVariant.sku == sku.strip().upper())
    if q:
        stmt = stmt.where(Product.name.contains(q.strip(), autoescape=True))
    return service.paged(
        db, stmt.order_by(ProductVariant.sku), page, pageSize, service.inventory_info
    )


@router.post("/pos/sales/estimate", response_model=PosEstimate)
def estimate(data: PosEstimateInput, db: DB, identity: Staff):
    return service.estimate(service.pos_rows(db, identity[1], data.items), data.items)


@router.post(
    "/pos/sales", response_model=SaleInfo, status_code=201, dependencies=[Depends(raw_body)]
)
def sell(data: PosSaleInput, request: Request, db: DB, identity: Staff, key: Key = None):
    return execute(
        db,
        request,
        identity[0],
        key,
        lambda: service.sell(db, *identity, data, request.app.state.clock.now()),
    )


@router.get("/pos/sales", response_model=SaleList)
def sales(
    request: Request,
    db: DB,
    identity: Staff,
    date: Date | None = None,
    page: Page = 1,
    pageSize: PageSize = 20,
):
    now = request.app.state.clock.now()
    stmt = service.sales_for_date(identity[1], date or now.astimezone(service.JST).date())
    result = service.paged(
        db,
        stmt.order_by(service.PosSale.sold_at.desc(), service.PosSale.id),
        page,
        pageSize,
        lambda row: service.sale_info(db, row[0], now, True),
    )
    all_sales = db.scalars(stmt).all()
    completed = [sale for sale in all_sales if sale.status == "COMPLETED"]
    result["summary"] = dict(
        completedCount=len(completed),
        completedAmountYen=sum(x.total_amount_yen for x in completed),
        voidedCount=sum(x.status == "VOIDED" for x in all_sales),
    )
    return result


@router.post(
    "/pos/sales/{sale_id}/void", response_model=SaleDetail, dependencies=[Depends(raw_body)]
)
def void(
    sale_id: UUID, data: VoidInput, request: Request, db: DB, identity: Staff, key: Key = None
):
    return execute(
        db,
        request,
        identity[0],
        key,
        lambda: service.void(db, *identity, str(sale_id), data, request.app.state.clock.now()),
    )


@router.get("/inventories", response_model=InventoryList)
def inventories(
    db: DB,
    identity: Staff,
    q: str | None = Query(None, max_length=100),
    sku: str | None = Query(None, max_length=32),
    filter: Literal["ALL", "OUT_OF_STOCK", "SHORTAGE_RISK"] = "ALL",
    page: Page = 1,
    pageSize: PageSize = 20,
):
    stmt = service.catalog_query(identity[1])
    if q:
        stmt = stmt.where(Product.name.contains(q.strip(), autoescape=True))
    if sku:
        stmt = stmt.where(ProductVariant.sku.startswith(sku.strip().upper(), autoescape=True))
    if filter == "OUT_OF_STOCK":
        stmt = stmt.where(Inventory.on_hand_quantity <= Inventory.reserved_quantity)
    elif filter == "SHORTAGE_RISK":
        stmt = stmt.where(Inventory.on_hand_quantity < Inventory.reserved_quantity)
    return service.paged(
        db, stmt.order_by(ProductVariant.sku), page, pageSize, service.inventory_info
    )


@router.get("/inventories/{inventory_id}/transactions", response_model=TransactionList)
def transactions(
    inventory_id: UUID, db: DB, identity: Staff, page: Page = 1, pageSize: PageSize = 20
):
    row = service.inventory_row(db, identity[1], str(inventory_id))
    stmt = select(InventoryTransaction).where(
        InventoryTransaction.inventory_id == str(inventory_id)
    )
    result = service.paged(
        db,
        stmt.order_by(InventoryTransaction.occurred_at.desc(), InventoryTransaction.id.desc()),
        page,
        pageSize,
        lambda row: service.transaction_info(db, row[0]),
    )
    result["inventory"] = service.inventory_info(row)
    return result


@router.post(
    "/inventories/{inventory_id}/receipts",
    response_model=AdjustmentResult,
    dependencies=[Depends(raw_body)],
)
def receipt(
    inventory_id: UUID,
    data: ReceiptInput,
    request: Request,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return execute(
        db,
        request,
        identity[0],
        key,
        lambda: service.adjust(
            db, *identity, str(inventory_id), data, request.app.state.clock.now()
        ),
    )


@router.post(
    "/inventories/{inventory_id}/adjustments",
    response_model=AdjustmentResult,
    dependencies=[Depends(raw_body)],
)
def adjustment(
    inventory_id: UUID,
    data: AdjustmentInput,
    request: Request,
    db: DB,
    identity: Staff,
    key: Key = None,
):
    return execute(
        db,
        request,
        identity[0],
        key,
        lambda: service.adjust(
            db, *identity, str(inventory_id), data, request.app.state.clock.now()
        ),
    )
