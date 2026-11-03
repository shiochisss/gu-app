import io
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import insert, select, update

from app.clock import FakeClock
from app.main import create_app
from app.models import BusinessHours, Inventory, Product, ProductVariant, RefreshToken, User
from app.services.seed import seed_database, seed_id

PASSWORD = "Test-only-seed-password-42!"


@pytest.fixture
def api(clean_mysql, settings):
    clock = FakeClock(datetime(2026, 11, 2, 6, tzinfo=UTC))
    seed_database(clean_mysql, clock, PASSWORD)
    config = settings.model_copy(
        update={"database_url": SecretStr(clean_mysql.url.render_as_string(hide_password=False))}
    )
    app = create_app(config, clock)
    with TestClient(
        app, headers={"X-BFF-Secret": config.bff_shared_secret.get_secret_value()}
    ) as client:
        yield client, clock, clean_mysql, app


def sign_in(client, email="buyer1@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_register_me_logout_and_private_token_storage(api):
    client, _, engine, _ = api
    response = client.post(
        "/api/v1/auth/register",
        json={"email": " New.Buyer@Example.com ", "password": PASSWORD, "role": "STAFF"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "new.buyer@example.com"
    assert body["user"]["role"] == "CUSTOMER"
    assert body["accessTokenExpiresAt"].endswith("+09:00")
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + body["accessToken"]}
        ).json()["email"]
        == "new.buyer@example.com"
    )
    with engine.connect() as conn:
        stored = conn.execute(select(RefreshToken.token_hash)).scalars().all()
        assert body["refreshToken"] not in stored
        assert all(len(value) == 64 for value in stored)
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": "NEW.BUYER@example.com", "password": PASSWORD}
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v1/auth/logout", json={"refreshToken": body["refreshToken"]}).status_code
        == 204
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"refreshToken": body["refreshToken"]}).status_code
        == 401
    )
    # An issued access token keeps its designed 15-minute lifetime after logout.
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + body["accessToken"]}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/auth/logout", json={"refreshToken": "unknown"}).status_code == 204


def test_it_sec_04_jwt_tampering_and_clock_expiry(api):
    client, clock, _, _ = api
    token = sign_in(client).json()["accessToken"]
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + token[:-10] + "tamperedXX"}
        ).json()["code"]
        == "UNAUTHENTICATED"
    )
    clock.advance(timedelta(minutes=15))
    result = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})
    assert result.status_code == 401 and result.json()["code"] == "TOKEN_EXPIRED"


def test_disabled_account_and_staff_identity(api):
    client, _, engine, _ = api
    staff = sign_in(client, "staff.shinjuku@example.com").json()
    assert staff["user"]["storeId"] == seed_id("store", "SHINJUKU")
    assert staff["user"]["storeName"] == "テスト新宿店"
    with engine.begin() as conn:
        conn.execute(
            update(User).where(User.email == "staff.shinjuku@example.com").values(status="DISABLED")
        )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + staff["accessToken"]}
        ).status_code
        == 401
    )
    assert sign_in(client, "staff.shinjuku@example.com").json()["code"] == "INVALID_CREDENTIALS"


@pytest.mark.parametrize("seconds,reusable", [(29.999, True), (30, False), (31, False)])
def test_it_sec_08_15_refresh_rotation_boundaries(api, seconds, reusable):
    client, clock, _, _ = api
    first = sign_in(client).json()
    second = client.post("/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert second.status_code == 200
    clock.advance(timedelta(seconds=seconds))
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
        ).status_code
        == 401
    )
    result = client.post(
        "/api/v1/auth/refresh", json={"refreshToken": second.json()["refreshToken"]}
    )
    assert result.status_code == (200 if reusable else 401)


def test_it_sec_07_failure_limit_window_and_reset(api):
    client, clock, _, _ = api
    for _ in range(5):
        assert sign_in(client, password="a-wrong-test-password").status_code == 401
    assert sign_in(client).status_code == 429
    clock.advance(timedelta(minutes=15))
    result = sign_in(client)
    assert result.status_code == 429 and result.headers["Retry-After"] == "1"
    clock.advance(timedelta(microseconds=1))
    assert sign_in(client).status_code == 200
    assert sign_in(client, password="a-wrong-test-password").status_code == 401
    assert sign_in(client).status_code == 200


def test_it_sec_05_13_14_secrets_logs_and_no_cors(api):
    client, _, _, app = api
    denied = client.get("/api/v1/stores", headers={"X-BFF-Secret": "wrong"})
    assert denied.status_code == 403
    stream = io.StringIO()
    logging.getLogger("pickup").handlers[0].setStream(stream)
    body = sign_in(client).json()
    client.post("/api/v1/auth/refresh", json={"refreshToken": body["refreshToken"]})
    log = stream.getvalue()
    for value in [
        PASSWORD,
        body["accessToken"],
        body["refreshToken"],
        "buyer1@example.com",
        app.state.settings.jwt_secret.get_secret_value(),
    ]:
        assert value not in log
    response = client.options(
        "/api/v1/stores",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "body",
    [
        {"email": "invalid", "password": PASSWORD},
        {"email": "buyer@example.com", "password": "short"},
        {"email": "buyer@example.com", "password": "x" * 129},
    ],
)
def test_auth_validation_is_common_400(api, body):
    result = api[0].post("/api/v1/auth/register", json=body)
    assert result.status_code == 400 and result.json()["code"] == "VALIDATION_ERROR"
    assert result.json()["fieldErrors"]


def test_catalog_list_detail_filters_pagination_and_injection(api):
    client, _, engine, _ = api
    store = seed_id("store", "SHINJUKU")
    prefix = f"/api/v1/stores/{store}/products"
    all_products = client.get(prefix).json()
    assert all_products["totalCount"] == 6
    assert all("created" not in item for item in all_products["items"])
    assert client.get(prefix, params={"sort": "price_asc"}).json()["items"][0]["priceYen"] == 990
    assert client.get(prefix, params={"pageSize": 2, "page": 2}).json()["pageSize"] == 2
    assert client.get(prefix, params={"q": "' OR 1=1 --"}).json()["totalCount"] == 0
    assert (
        client.get(prefix, params={"category": "TOPS", "size": "M", "color": "ホワイト"}).json()[
            "totalCount"
        ]
        == 1
    )
    assert client.get(prefix, params={"size": "FREE"}).json()["totalCount"] == 0
    product = seed_id("product", "1")
    detail = client.get(prefix + "/" + product).json()
    assert len(detail["variants"]) == 4
    variant = seed_id("variant", "P001-0-M")
    with engine.begin() as conn:
        conn.execute(
            update(Inventory)
            .where(Inventory.store_id == store, Inventory.product_variant_id == variant)
            .values(on_hand_quantity=99)
        )
    fresh = client.get(prefix + "/" + product).json()
    assert (
        next(value for value in fresh["variants"] if value["productVariantId"] == variant)[
            "maxSelectableQuantity"
        ]
        == 10
    )


def test_it_cat_01_store_specific_availability_and_literal_wildcards(api):
    client, _, engine, _ = api
    product_id = seed_id("product", "1")
    with engine.begin() as conn:
        conn.execute(
            update(Product).where(Product.id == product_id).values(name="Literal%_\\ item")
        )
        variant_ids = select(ProductVariant.id).where(ProductVariant.product_id == product_id)
        conn.execute(
            update(Inventory)
            .where(
                Inventory.store_id == seed_id("store", "SHINJUKU"),
                Inventory.product_variant_id.in_(variant_ids),
            )
            .values(on_hand_quantity=0)
        )
    a = f"/api/v1/stores/{seed_id('store', 'SHINJUKU')}/products"
    b = f"/api/v1/stores/{seed_id('store', 'SHIBUYA')}/products"
    assert client.get(a, params={"q": "%_\\"}).json()["totalCount"] == 0
    assert client.get(b, params={"q": "%_\\"}).json()["totalCount"] == 1
    assert all(
        not value["inStock"] for value in client.get(a + "/" + product_id).json()["variants"]
    )
    assert client.get(f"/api/v1/stores/{uuid4()}/products").status_code == 404


def test_store_hours_cutoff_override_and_inactive_product(api):
    client, clock, engine, _ = api
    stores = client.get("/api/v1/stores").json()["items"]
    assert len(stores) == 2 and all(value["canOrderNow"] for value in stores)
    clock.set(datetime(2026, 11, 2, 11, 0, tzinfo=UTC))
    assert all(value["canOrderNow"] for value in client.get("/api/v1/stores").json()["items"])
    clock.advance(timedelta(microseconds=1))
    assert all(
        not value["canOrderNow"] and value["earliestReadyAt"] is None
        for value in client.get("/api/v1/stores").json()["items"]
    )
    with engine.begin() as conn:
        conn.execute(
            insert(BusinessHours).values(
                id=str(uuid4()),
                store_id=seed_id("store", "SHINJUKU"),
                business_date=clock.now()
                .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Tokyo"))
                .date(),
                closed=True,
                version=0,
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        conn.execute(
            update(Product).where(Product.id == seed_id("product", "1")).values(is_active=False)
        )
    latest = client.get("/api/v1/stores").json()["items"]
    assert next(value for value in latest if value["code"] == "SHINJUKU")["today"]["closed"] is True
    assert (
        client.get(
            f"/api/v1/stores/{seed_id('store', 'SHINJUKU')}/products/{seed_id('product', '1')}"
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "params",
    [
        {"q": ""},
        {"q": "x" * 101},
        {"q": "a\nb"},
        {"page": 0},
        {"pageSize": 101},
        {"category": "INVALID"},
        {"sort": "name;drop"},
    ],
)
def test_catalog_query_boundaries(api, params):
    result = api[0].get(f"/api/v1/stores/{seed_id('store', 'SHINJUKU')}/products", params=params)
    assert result.status_code == 400 and result.json()["code"] == "VALIDATION_ERROR"
