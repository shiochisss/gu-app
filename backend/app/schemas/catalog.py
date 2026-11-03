from datetime import date, datetime

from app.schemas.common import ApiModel


class StoreHours(ApiModel):
    date: date
    closed: bool
    opens_at: str | None = None
    closes_at: str | None = None


class StoreSummary(ApiModel):
    store_id: str
    code: str
    name: str
    address: str
    today: StoreHours
    accepting_orders: bool
    order_cutoff_at: datetime | None
    can_order_now: bool
    earliest_ready_at: datetime | None


class StoreList(ApiModel):
    items: list[StoreSummary]


class ProductColor(ApiModel):
    name: str
    hex: str


class ProductSummary(ApiModel):
    product_id: str
    name: str
    category: str
    category_label: str
    price_yen: int
    image_color: str
    colors: list[ProductColor]
    available_sizes: list[str]


class ProductList(ApiModel):
    items: list[ProductSummary]
    page: int
    page_size: int
    total_count: int


class ProductVariantInfo(ApiModel):
    product_variant_id: str
    sku: str
    color_name: str
    color_hex: str
    size: str
    price_yen: int
    in_stock: bool
    max_selectable_quantity: int


class ProductDetail(ApiModel):
    product_id: str
    name: str
    category: str
    category_label: str
    description: str
    image_color: str
    variants: list[ProductVariantInfo]
