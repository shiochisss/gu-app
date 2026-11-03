import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import Store
from app.schemas.catalog import ProductDetail, ProductList, StoreList
from app.services.business_calendar import preview_store
from app.services.catalog import list_products, product_detail

router = APIRouter(prefix="/api/v1/stores", tags=["店舗・商品"])
DB = Annotated[Session, Depends(get_db)]


@router.get("", response_model=StoreList)
def stores(db: DB, request: Request):
    return {
        "items": [
            preview_store(db, store, request.app.state.clock.now())
            for store in db.execute(select(Store).order_by(Store.code)).scalars()
        ]
    }


@router.get("/{store_id}/products", response_model=ProductList)
def products(
    store_id: UUID,
    db: DB,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    category: Literal["TOPS", "BOTTOMS", "OUTER", "DRESS", "INNER", "ACCESSORY"] | None = None,
    color: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    size: Literal["XS", "S", "M", "L", "XL", "FREE"] | None = None,
    sort: Literal["new", "price_asc", "price_desc"] = "new",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
):
    if q is not None and any(unicodedata.category(char) == "Cc" for char in q):
        raise ApiError(400, "VALIDATION_ERROR")
    return list_products(
        db,
        str(store_id),
        q=q,
        category=category,
        color=color,
        size=size,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/{store_id}/products/{product_id}", response_model=ProductDetail)
def product(store_id: UUID, product_id: UUID, db: DB):
    return product_detail(db, str(store_id), str(product_id))
