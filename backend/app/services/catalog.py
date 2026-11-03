from sqlalchemy import select

from app.errors import ApiError
from app.models import Inventory, Product, ProductVariant, Store
from app.models.enums import SIZE

CATEGORY_LABELS = {
    "TOPS": "トップス",
    "BOTTOMS": "ボトムス",
    "OUTER": "アウター",
    "DRESS": "ワンピース",
    "INNER": "インナー",
    "ACCESSORY": "小物",
}


def require_store(db, store_id):
    store = db.get(Store, store_id)
    if store is None:
        raise ApiError(404, "STORE_NOT_FOUND")
    return store


def list_products(
    db, store_id, *, q=None, category=None, color=None, size=None, sort="new", page=1, page_size=20
):
    require_store(db, store_id)
    statement = select(
        Product, ProductVariant, Inventory.on_hand_quantity, Inventory.reserved_quantity
    ).join(ProductVariant, ProductVariant.product_id == Product.id)
    statement = statement.join(Inventory, Inventory.product_variant_id == ProductVariant.id).where(
        Inventory.store_id == store_id,
        Product.is_active.is_(True),
        ProductVariant.is_active.is_(True),
        Inventory.on_hand_quantity > Inventory.reserved_quantity,
    )
    if q is not None:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            Product.name.collate("utf8mb4_0900_ai_ci").like(f"%{escaped}%", escape="\\")
        )
    if category:
        statement = statement.where(Product.category == category)
    if color:
        statement = statement.where(ProductVariant.color_name == color)
    if size:
        statement = statement.where(ProductVariant.size == size)
    grouped = {}
    for product, variant, _, _ in db.execute(statement):
        if product.id not in grouped:
            grouped[product.id] = {"product": product, "variants": []}
        grouped[product.id]["variants"].append(variant)
    summaries = []
    for value in grouped.values():
        product, variants = value["product"], value["variants"]
        variants.sort(key=lambda item: (item.sort_order, item.sku))
        colors = list(
            {v.color_name: {"name": v.color_name, "hex": v.color_hex} for v in variants}.values()
        )
        summaries.append(
            {
                "product_id": product.id,
                "name": product.name,
                "category": product.category,
                "category_label": CATEGORY_LABELS[product.category],
                "price_yen": min(v.price_yen for v in variants),
                "image_color": product.image_color,
                "colors": colors,
                "available_sizes": [s for s in SIZE if any(v.size == s for v in variants)],
                "created": product.created_at.timestamp(),
            }
        )

    def order_key(value):
        rest = (-value["created"], value["product_id"])
        if sort == "new":
            return rest
        return ((value["price_yen"] if sort == "price_asc" else -value["price_yen"]), *rest)

    summaries.sort(key=order_key)
    return {
        "items": summaries[(page - 1) * page_size : page * page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(summaries),
    }


def product_detail(db, store_id, product_id):
    require_store(db, store_id)
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise ApiError(404, "PRODUCT_NOT_FOUND")
    rows = db.execute(
        select(ProductVariant, Inventory.on_hand_quantity, Inventory.reserved_quantity)
        .join(Inventory, Inventory.product_variant_id == ProductVariant.id)
        .where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
            Inventory.store_id == store_id,
        )
        .order_by(ProductVariant.sort_order, ProductVariant.sku)
    ).all()
    if not rows:
        raise ApiError(404, "PRODUCT_NOT_FOUND")
    variants = []
    for variant, on_hand, reserved in rows:
        available = max(0, on_hand - reserved)
        variants.append(
            {
                "product_variant_id": variant.id,
                "sku": variant.sku,
                "color_name": variant.color_name,
                "color_hex": variant.color_hex,
                "size": variant.size,
                "price_yen": variant.price_yen,
                "in_stock": available > 0,
                "max_selectable_quantity": min(available, 10),
            }
        )
    return {
        "product_id": product.id,
        "name": product.name,
        "category": product.category,
        "category_label": CATEGORY_LABELS[product.category],
        "description": product.description,
        "image_color": product.image_color,
        "variants": variants,
    }
