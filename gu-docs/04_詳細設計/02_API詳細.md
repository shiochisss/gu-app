# 詳細設計書 02 API詳細

版：1.0／作成日：2026年10月31日
関連：[01_DB設計](./01_DB設計.md)、[03_業務ロジック](./03_業務ロジック.md)、[基本設計書 13章](../03_基本設計書.md)

## 1. 共通仕様

### 1.1 構成

```text
ブラウザ ──(同一オリジン /api/v1/...)──> Frontend（Next.js Route Handler＝BFF）
                                          └─(サーバー間通信 /api/v1/...)──> Backend（FastAPI）
Stripe ──(Webhook /api/v1/payments/webhook)──> Backend
GitHub Actions ──(/internal/jobs/run)──> Backend
```

- ブラウザが呼ぶパスとBackendのパスは同じ `/api/v1/...` とする。BFFは2章の規則で転送する。
- BackendはBFFからの要求だけを受け付ける。パスが `/api/v1/` で始まる要求のうち、API-13（`/api/v1/payments/webhook`）以外は、ヘッダー `X-BFF-Secret` が環境変数 `BFF_SHARED_SECRET` と一致しなければ403 `FORBIDDEN` を返す（`hmac.compare_digest` で比較）。`/api/v1/` 以外のパス（`/healthz`、`/internal/jobs/run`、ローカルの `/docs`・`/openapi.json`）はこの確認の対象外とする（`/internal/jobs/run` は `X-Job-Secret` で確認する）。
- BackendはCORSを許可しない（CORSミドルウェアを入れない。ブラウザから直接呼ばれないため）。
- `APP_ENV` が `local` 以外のときは `docs_url=None`、`redoc_url=None`、`openapi_url=None` で起動する（Azureのテスト環境でもSwagger UIとOpenAPI定義を公開しない。存在しないパスとして404になる）。

### 1.2 形式

| 項目 | 規則 |
|---|---|
| 文字コード | UTF-8、`Content-Type: application/json` |
| 項目名 | JSONはキャメルケース（Pydanticの `alias_generator=to_camel`、`populate_by_name=True`） |
| ID | UUID文字列 |
| 日時 | ISO 8601、`+09:00` 付きで返す（例：`2026-10-31T18:40:00+09:00`）。受け取りはタイムゾーン付きを必須とする |
| 日付・時刻 | 日付 `YYYY-MM-DD`、時刻 `HH:MM` |
| 金額 | 円の整数（税込） |
| 一覧 | クエリ `page`（1以上、既定1）・`pageSize`（1〜100、既定20）。レスポンスは `{"items": [...], "page": 1, "pageSize": 20, "totalCount": 123}` |
| 楽観ロック | 更新系は `version` を受け取り、不一致は409 `CONFLICTING_UPDATE`（`latestResource` に最新値） |
| 冪等キー | 「冪等キー：必須」のAPIはヘッダー `Idempotency-Key`（UUID）が必須（03_業務ロジック 13章） |
| 追跡ID | 全レスポンスにヘッダー `X-Request-Id`（BFFが付けたもの、なければBackendが生成） |

### 1.3 エラー形式

```json
{
  "code": "OUT_OF_STOCK",
  "message": "在庫が足りない商品があります。",
  "details": {"items": [{"productVariantId": "…", "requested": 3, "available": 1}]},
  "fieldErrors": [{"field": "items[0].quantity", "code": "OUT_OF_RANGE", "message": "1〜10で入力してください。"}],
  "traceId": "…",
  "latestResource": null
}
```

FastAPIの入力エラー（既定は422）は400 `VALIDATION_ERROR` に変換する。

`fieldErrors[].code` の値：`REQUIRED`（必須）、`INVALID_FORMAT`（形式違い）、`OUT_OF_RANGE`（数値・日時の範囲外）、`TOO_LONG`（文字数超過）、`INVALID_VALUE`（列挙値以外・重複など）。`field` はJSONのパス（例：`items[0].quantity`）。

検索文字列（`q`・`sku`）を `LIKE`・`ILIKE` に使うときは、`\`・`%`・`_` を `\` でエスケープし、`ESCAPE '\'` を指定する。

### 1.4 エラーコード一覧

| code | HTTP | message（画面にそのまま表示してよい文） |
|---|---|---|
| VALIDATION_ERROR | 400 | 入力内容を確認してください。 |
| CSRF_REJECTED | 403 | 画面を再読み込みしてから、もう一度お試しください。（BFFが返す） |
| UNAUTHENTICATED | 401 | ログインしてください。 |
| TOKEN_EXPIRED | 401 | ログインの有効期限が切れました。 |
| INVALID_CREDENTIALS | 401 | メールアドレスまたはパスワードが正しくありません。 |
| FORBIDDEN | 403 | この操作は行えません。 |
| NOT_FOUND / STORE_NOT_FOUND / PRODUCT_NOT_FOUND / ORDER_NOT_FOUND | 404 | 対象が見つかりません。 |
| EMAIL_ALREADY_REGISTERED | 409 | このメールアドレスは登録済みです。 |
| CONFLICTING_UPDATE | 409 | ほかの操作で内容が更新されました。最新の内容を確認してください。 |
| CALCULATION_CHANGED | 409 | 金額または準備完了予定が変わりました。内容を確認してください。 |
| ESTIMATE_EXPIRED | 409 | 確認画面の有効期限が切れました。もう一度確認してください。 |
| INSUFFICIENT_STOCK | 409 | 販売できる在庫が足りません。 |
| INVALID_STATE | 409 | 現在の状態ではこの操作は行えません。 |
| IDEMPOTENCY_IN_PROGRESS | 409 | 処理中です。しばらくしてから確認してください。 |
| IDEMPOTENCY_KEY_REUSED | 422 | 同じ操作番号で別の内容が送信されました。 |
| ORDER_LIMIT_EXCEEDED | 422 | 1回の注文は合計10点までです。 |
| STORE_NOT_ACCEPTING | 422 | この店舗は現在、注文の受付を停止しています。 |
| ORDER_CLOSED | 422 | 本日の注文受付は終了しました。 |
| OUT_OF_STOCK | 422 | 在庫が足りない商品があります。 |
| CAPACITY_FULL | 422 | 混雑のため、閉店までに準備が間に合いません。 |
| TERMS_NOT_AGREED | 422 | 受取期限と期限を過ぎた場合の扱いを確認してください。 |
| PAYMENT_DECLINED | 422 | カードでのお支払いができませんでした。別のカードをお試しください。 |
| CANCEL_NOT_ALLOWED | 422 | このご注文は取り消せません。 |
| INVALID_PICKUP_CODE | 422 | QRコードまたは受取コードが正しくありません。 |
| RATE_LIMITED | 429 | 試行回数が多すぎます。しばらくしてからお試しください。 |
| NO_BUSINESS_DAY | 500 | 営業日を判定できませんでした。店舗の営業時間を確認してください。 |
| PAYMENT_PROVIDER_ERROR | 502 | 決済サービスに接続できませんでした。 |
| INTERNAL_ERROR | 500 | エラーが発生しました。時間をおいてお試しください。 |

## 2. BFF（Next.js Route Handler）

### 2.1 転送

- `frontend/src/app/api/v1/[...path]/route.ts` で受け、4章のAPI一覧のうち「BFF経由」のものだけを転送する（一覧にないパスは404）。転送先は `BACKEND_BASE_URL + 同じパス + 同じクエリ`。
- 転送するヘッダー：`Content-Type`、`Idempotency-Key`、`X-Request-Id`（なければBFFがUUIDを生成）。追加するヘッダー：`X-BFF-Secret`、`Authorization: Bearer <pa_atクッキーの値>`（あれば）。それ以外のヘッダーとクッキーは転送しない。
- Backendのレスポンスのステータスと本文をそのまま返す（`Set-Cookie` は転送しない）。

### 2.2 クッキー

| 名前 | 中身 | 属性 |
|---|---|---|
| `pa_at` | アクセストークン（JWT） | HttpOnly、Secure、SameSite=Lax、Path=/、Max-Age=900 |
| `pa_rt` | リフレッシュトークン | HttpOnly、Secure、SameSite=Strict、Path=/api/v1、Max-Age=604800 |

`FRONTEND_BASE_URL` が `http://localhost` で始まる場合だけ Secure を外す（ローカル開発用）。トークンをレスポンス本文やJavaScriptに渡さない。

### 2.3 認証APIの特別な扱い

| パス | BFFの処理 |
|---|---|
| POST /api/v1/auth/register、/auth/login | Backendへ転送し、成功時は返ってきた `accessToken`・`refreshToken` をクッキーに設定して、本文からトークンを除いた `{"user": …}` を返す |
| POST /api/v1/auth/refresh | `pa_rt` クッキーの値を本文 `{"refreshToken": …}` にしてBackendへ送り、成功時はクッキーを更新して `{"user": …}` を返す。失敗時は両クッキーを削除して401 |
| POST /api/v1/auth/logout | `pa_rt` の値を本文にしてBackendへ送り、結果にかかわらず両クッキーを削除して204 |

### 2.4 自動更新

- 転送の前に、`pa_at` がなく `pa_rt` がある場合は、先に refresh を行う。この先回りの refresh に失敗した場合は、両クッキーを削除し、`Authorization` なしで転送を続ける（ログイン不要のAPIはそのまま成功し、ログインが必要なAPIはBackendが401を返す）。
- 転送した要求に対し、Backendが401（`UNAUTHENTICATED` または `TOKEN_EXPIRED`）を返し、`pa_rt` クッキーがある場合は、BFFが一度だけ refresh を行ってクッキーを更新し、同じ要求（同じ `Idempotency-Key`）を再送する。
- refreshに失敗したら両クッキーを削除して401を返す。
- 同時に複数の要求が同じ `pa_rt` で refresh しようとした場合に備え、BFFはプロセス内のMap（キー：`pa_rt` のSHA-256、値：refreshのPromise）で1回にまとめ、結果を30秒間再利用する。2本目以降の要求も同じ新しいトークンでクッキーを設定する（Freeプランはインスタンスが1つのため、プロセス内でまとめれば足りる）。

### 2.5 CSRF対策

GET以外の要求では、BFFは次の両方を確認し、満たさなければ403 `CSRF_REJECTED` を返す。

- `Origin` ヘッダーが `FRONTEND_BASE_URL` と一致する。
- ヘッダー `X-Requested-With: pickup-app` がある（Frontendの共通fetch関数が必ず付ける）。

## 3. 認可の規則

| ロール指定 | 意味 |
|---|---|
| なし | ログイン不要 |
| ログイン | CUSTOMER・STAFFどちらでも可 |
| 購入者 | role=CUSTOMER。注文は `purchaser_id = sub` のものだけ。他人の注文は404 `ORDER_NOT_FOUND` |
| 店員 | role=STAFF。対象（注文・在庫・売上・店舗）の店舗がJWTの `store_id` と一致しなければ404 |

ロールが違う場合は403 `FORBIDDEN`。

例外：API-19（受け取り照合）は、署名の正しいQRが他店舗の注文だった場合に、200で `canHandOver=false`・`reasonCode=OTHER_STORE`・`orderNumber` だけを返す（店員に「別の店舗の注文」と伝えるため）。手入力で他店舗の注文番号を指定した場合は、存在を明かさないため422 `INVALID_PICKUP_CODE` とする。

## 4. API一覧

API-33・API-34は欠番（運営担当APIは作らない。基本設計書 BD-T06）。

| ID | Method | Path | ロール | 冪等キー | BFF経由 |
|---|---|---|---|---|---|
| API-01 | POST | /api/v1/auth/register | なし | ― | ○ |
| API-02 | POST | /api/v1/auth/login | なし | ― | ○ |
| API-03 | POST | /api/v1/auth/refresh | なし（リフレッシュトークン） | ― | ○ |
| API-04 | POST | /api/v1/auth/logout | なし（リフレッシュトークン） | ― | ○ |
| API-40 | GET | /api/v1/auth/me | ログイン | ― | ○ |
| API-05 | GET | /api/v1/stores | なし | ― | ○ |
| API-06 | GET | /api/v1/stores/{storeId}/products | なし | ― | ○ |
| API-07 | GET | /api/v1/stores/{storeId}/products/{productId} | なし | ― | ○ |
| API-08 | POST | /api/v1/orders/estimate | 購入者 | ― | ○ |
| API-09 | POST | /api/v1/orders | 購入者 | 必須 | ○ |
| API-36 | POST | /api/v1/orders/{orderId}/payment/refresh | 購入者 | ― | ○ |
| API-10 | GET | /api/v1/orders | 購入者 | ― | ○ |
| API-11 | GET | /api/v1/orders/{orderId} | 購入者 | ― | ○ |
| API-12 | POST | /api/v1/orders/{orderId}/cancel | 購入者 | 必須 | ○ |
| API-37 | POST | /api/v1/orders/{orderId}/pickup-token/reissue | 購入者 | 必須 | ○ |
| API-13 | POST | /api/v1/payments/webhook | Stripeの署名 | ― | × |
| API-14 | GET | /api/v1/staff/orders | 店員 | ― | ○ |
| API-41 | GET | /api/v1/staff/orders/{orderId} | 店員 | ― | ○ |
| API-15 | POST | /api/v1/staff/orders/{orderId}/preparation/start | 店員 | ― | ○ |
| API-16 | POST | /api/v1/staff/orders/{orderId}/shortages | 店員 | 必須 | ○ |
| API-17 | POST | /api/v1/staff/orders/{orderId}/delay | 店員 | 必須 | ○ |
| API-18 | POST | /api/v1/staff/orders/{orderId}/ready | 店員 | 必須 | ○ |
| API-19 | POST | /api/v1/staff/pickups/verify | 店員 | ― | ○ |
| API-20 | POST | /api/v1/staff/orders/{orderId}/handover | 店員 | 必須 | ○ |
| API-35 | POST | /api/v1/staff/orders/{orderId}/return-to-stock | 店員 | 必須 | ○ |
| API-21 | GET | /api/v1/staff/store | 店員 | ― | ○ |
| API-22 | PUT | /api/v1/staff/store/acceptance | 店員 | ― | ○ |
| API-23 | PUT | /api/v1/staff/store/business-hours/{date} | 店員 | ― | ○ |
| API-24 | GET | /api/v1/staff/products | 店員 | ― | ○ |
| API-25 | POST | /api/v1/staff/pos/sales/estimate | 店員 | ― | ○ |
| API-26 | POST | /api/v1/staff/pos/sales | 店員 | 必須 | ○ |
| API-27 | GET | /api/v1/staff/pos/sales | 店員 | ― | ○ |
| API-28 | POST | /api/v1/staff/pos/sales/{saleId}/void | 店員 | 必須 | ○ |
| API-29 | GET | /api/v1/staff/inventories | 店員 | ― | ○ |
| API-30 | GET | /api/v1/staff/inventories/{inventoryId}/transactions | 店員 | ― | ○ |
| API-31 | POST | /api/v1/staff/inventories/{inventoryId}/receipts | 店員 | 必須 | ○ |
| API-32 | POST | /api/v1/staff/inventories/{inventoryId}/adjustments | 店員 | 必須 | ○ |
| API-38 | POST | /internal/jobs/run | ジョブ用の秘密 | ― | × |
| API-39 | GET | /api/v1/dev/mails | ログイン | ― | ○（`DEV_TOOLS_ENABLED=true` のときだけ） |

## 5. 各APIの詳細

以下、レスポンス例の値は説明用である。

### API-01 会員登録

- 入力：`{"email": "buyer9@example.com", "password": "TestPassw0rd!"}`。email：前後空白除去・小文字化・最大254文字・メール形式。password：12〜128文字。
- 処理：同じemailがあれば409 `EMAIL_ALREADY_REGISTERED`。role=CUSTOMERで作成し、API-02と同じトークンを発行する。メール確認は行わない。
- 出力（201）：`{"user": {"userId": "…", "email": "…", "role": "CUSTOMER", "storeId": null}, "accessToken": "…", "accessTokenExpiresAt": "…", "refreshToken": "…", "refreshTokenExpiresAt": "…"}`（BFFがトークンを除いて返す）。

### API-02 ログイン

- 入力：`{"email": "…", "password": "…"}`
- 処理：試行回数の制限（03_業務ロジック 9.4）→ ユーザーがいない・パスワード不一致・DISABLEDはすべて401 `INVALID_CREDENTIALS`（同じ文言）。
- 出力（200）：API-01と同じ形。店員は `storeId` に担当店舗IDが入る。

### API-03 トークン更新

- 入力：`{"refreshToken": "…"}`
- 処理：03_業務ロジック 9.3。無効なら401 `UNAUTHENTICATED`。
- 出力（200）：API-01と同じ形。

### API-04 ログアウト

- 入力：`{"refreshToken": "…"}`（無効でもエラーにしない）
- 出力：204

### API-40 ログイン中の利用者

- 出力（200）：`{"userId": "…", "email": "…", "role": "STAFF", "storeId": "…", "storeName": "テスト新宿店"}`

### API-05 店舗一覧

- 入力：なし
- 処理：全店舗について今日の営業時間（03_業務ロジック 2.1）と受付可否を計算する。
- 出力（200）：

```json
{"items": [{
  "storeId": "…", "code": "SHINJUKU", "name": "テスト新宿店", "address": "…",
  "today": {"date": "2026-10-31", "closed": false, "opensAt": "10:00", "closesAt": "21:00"},
  "acceptingOrders": true,
  "orderCutoffAt": "2026-10-31T20:00:00+09:00",
  "canOrderNow": true,
  "earliestReadyAt": "2026-10-31T18:52:00+09:00"
}]}
```

`canOrderNow` は受付中・本日営業・締切前のすべてを満たすとき true。`earliestReadyAt` は「1点の注文を今した場合の予定時刻」（03_業務ロジック 3.1の計算。見積もりは保存しない）。`canOrderNow=false` または03_業務ロジック 3.2の8に該当する場合は null。

### API-06 商品一覧（店舗別）

- 入力（クエリ）：`q`（1〜100文字、制御文字不可）、`category`（01_DB設計 2章の値）、`color`（色名。完全一致）、`size`、`sort`（`new`＝新着順・既定、`price_asc`、`price_desc`）、`page`、`pageSize`。
- 処理：is_active の商品のうち、その店舗で販売可能数1以上のバリエーションを1つ以上持つ商品だけを返す。`color`・`size` を指定した場合は、条件に合うバリエーションが販売可能なものに絞る。
- `priceYen` は販売可能なバリエーションの最小価格。並び順：`new` は `products.created_at` 降順、`price_asc`・`price_desc` は `priceYen` の昇順・降順。同順位は `products.created_at` 降順、次に `products.id` 昇順。
- 出力（200）：

```json
{"items": [{
  "productId": "…", "name": "コットンT 001", "category": "TOPS", "categoryLabel": "トップス",
  "priceYen": 990, "imageColor": "#F5F5F5",
  "colors": [{"name": "ホワイト", "hex": "#F5F5F5"}, {"name": "ブラック", "hex": "#222222"}],
  "availableSizes": ["S", "M"]
}], "page": 1, "pageSize": 20, "totalCount": 85}
```

`colors`・`availableSizes` は販売可能なバリエーションだけから作る。

### API-07 商品詳細（店舗別）

- 出力（200）：

```json
{"productId": "…", "name": "コットンT 001", "category": "TOPS", "categoryLabel": "トップス",
 "description": "テスト用の商品です。", "imageColor": "#F5F5F5",
 "variants": [{"productVariantId": "…", "sku": "P001-0-M", "colorName": "ホワイト", "colorHex": "#F5F5F5",
               "size": "M", "priceYen": 990, "inStock": true, "maxSelectableQuantity": 5}]}
```

`maxSelectableQuantity = min(販売可能数, 10)`。販売可能数0のバリエーションも `inStock=false` で返す（選択肢を灰色で表示するため）。非アクティブの商品・店舗外は404。

### API-08 見積もり

- 入力：

```json
{"storeId": "…", "items": [{"productVariantId": "…", "quantity": 2}], "shortagePolicy": "CANCEL_ALL"}
```

- 処理：03_業務ロジック 3.4。
- 出力（200）：

```json
{"accepted": true, "rejectionCode": null, "rejectionDetails": null,
 "estimateId": "…", "storeId": "…", "storeName": "テスト新宿店",
 "items": [{"productVariantId": "…", "productName": "コットンT 001", "sku": "P001-0-M", "colorName": "ホワイト",
            "size": "M", "unitPriceYen": 990, "quantity": 2, "lineAmountYen": 1980}],
 "totalQuantity": 2, "totalAmountYen": 1980, "shortagePolicy": "CANCEL_ALL",
 "estimatedReadyAt": "2026-10-31T18:40:00+09:00", "estimateExpiresAt": "2026-10-31T18:10:00+09:00",
 "pickupDeadlineRuleText": "準備完了日の1週間後の閉店時刻まで（休業日の場合は次の営業日の閉店時刻まで）",
 "overduePolicyText": "受取期限を過ぎた場合も、店舗が商品を棚に戻すまでは受け取れます。棚に戻した後は受け取れず、代金は返金されません。"}
```

受付不可のときは `accepted=false`、`rejectionCode`（`STORE_NOT_ACCEPTING`・`ORDER_CLOSED`・`OUT_OF_STOCK`・`CAPACITY_FULL`）、`rejectionDetails`（OUT_OF_STOCKなら不足明細）を入れ、`estimateId`・`estimatedReadyAt`・`estimateExpiresAt` はnull。`overduePolicyText` は環境変数 `OVERDUE_POLICY_TEXT`（未設定時は上の文）。

### API-09 注文作成

- 入力：

```json
{"estimateId": "…", "storeId": "…", "items": [{"productVariantId": "…", "quantity": 2}],
 "shortagePolicy": "CANCEL_ALL", "clientTotalAmountYen": 1980,
 "clientEstimatedReadyAt": "2026-10-31T18:40:00+09:00",
 "confirmationTokenId": "ctoken_…", "agreedToPickupTerms": true}
```

- 処理：03_業務ロジック 3.5。
- 出力：
  - 201：`{"orderId": "…", "orderNumber": "P000123", "status": "RECEIVED", "paymentStatus": "AUTHORIZED", "originalReadyAt": "…", "nextAction": null}`
  - 202（追加認証）：`{"orderId": "…", "orderNumber": "P000123", "status": "PENDING_PAYMENT", "paymentStatus": "REQUIRES_ACTION", "originalReadyAt": "…", "nextAction": {"type": "STRIPE_HANDLE_NEXT_ACTION", "clientSecret": "pi_…_secret_…"}}`
  - 202（結果不明）：`paymentStatus: "UNKNOWN"`、`nextAction: null`
- エラー：409 `ESTIMATE_EXPIRED`・`CALCULATION_CHANGED`（`latestResource` に最新の金額・予定。ただし estimateId は発行しない）、422 `STORE_NOT_ACCEPTING`・`ORDER_CLOSED`・`OUT_OF_STOCK`・`TERMS_NOT_AGREED`・`PAYMENT_DECLINED`（カード拒否とStripeのエラー応答）。段階1のコミット後は5xxを返さない（例外も含めて202 UNKNOWN。03_業務ロジック 3.5）。

### API-36 支払結果の確認

- 入力：なし（パスの注文ID）
- 処理：注文が PENDING_PAYMENT で PaymentIntent ID が保存済みのときだけ、Stripeから PaymentIntent を取得して反映する（03_業務ロジック 3.6）。それ以外は何もせず現在の状態を返す。
- 出力（200）：`{"orderId": "…", "status": "RECEIVED", "paymentStatus": "AUTHORIZED", "failureMessage": null}`。FAILEDなら `status: "NOT_ACCEPTED"`、`failureMessage` に `PAYMENT_DECLINED` の文言。

### API-10 自分の注文一覧

- 入力（クエリ）：`page`、`pageSize`
- 処理：自分の注文を `created_at` の降順で返す。NOT_ACCEPTED は作成から24時間以内のものだけ。各注文に03_業務ロジック 8章の同期を行う。
- 出力（200）：`items` の各要素は `{"orderId", "orderNumber", "storeName", "status", "statusLabel", "paymentStatus", "totalQuantity", "orderedAmountYen", "capturedAmountYen", "originalReadyAt", "currentReadyAt", "isDelayed", "createdAt"}`。`currentReadyAt` は `updated_ready_at`、確認中ならnull、遅延していなければ `original_ready_at`。

状態の表示名（statusLabel）：PENDING_PAYMENT＝支払確認中、NOT_ACCEPTED＝注文不成立、RECEIVED＝受付済み、PREPARING＝準備中、READY＝受け取り可能、ACTION_REQUIRED＝確認中（店舗対応中）、PICKED_UP＝受け取り済み、CANCELLED＝取消済み、EXPIRED＝受取期限切れ、EXPIRED_RETURNED＝受取期限切れ（終了）。

### API-11 自分の注文詳細

- 処理：03_業務ロジック 8章の同期を行ってから返す。
- 出力（200）：

```json
{"orderId": "…", "orderNumber": "P000123", "status": "READY", "statusLabel": "受け取り可能",
 "paymentStatus": "CAPTURED", "paymentStatusLabel": "お支払い確定",
 "store": {"storeId": "…", "name": "テスト新宿店", "address": "…"},
 "items": [{"orderItemId": "…", "productName": "コットンT 001", "sku": "P001-0-M", "colorName": "ホワイト", "size": "M",
            "unitPriceYen": 990, "orderedQuantity": 2, "shortageQuantity": 0, "preparedQuantity": 2}],
 "totalQuantity": 2, "orderedAmountYen": 1980, "capturedAmountYen": 1980,
 "shortagePolicy": "CANCEL_ALL", "createdAt": "…", "acceptedAt": "…",
 "originalReadyAt": "…", "updatedReadyAt": null, "readyAt": "…", "pickupDeadlineAt": "…",
 "pickedUpAt": null, "cancelledAt": null, "cancelReasonLabel": null,
 "isDelayed": false, "delayOccurred": false,
 "delays": [{"source": "STAFF", "reasonText": "店舗が混雑しているため", "newReadyAt": null, "registeredAt": "…"}],
 "pickup": {"qrValue": "PA1.…", "manualCode": "123456"},
 "canCancel": false, "canReissuePickupCode": true, "version": 7}
```

- `pickup` はQRの表示可否（03_業務ロジック 9.5の末尾）が真のときだけ値を入れ、それ以外は null。
- `paymentStatusLabel`：AUTHORIZING・REQUIRES_ACTION・UNKNOWN＝支払確認中、AUTHORIZED＝カード利用枠確保済み、CAPTURING＝お支払い確定処理中、CAPTURED＝お支払い確定、RELEASING・RELEASED＝利用枠を解放、REFUNDING＝返金処理中、REFUNDED＝返金済み、FAILED＝お支払いできませんでした、NOT_STARTED＝未処理。
- `canCancel`：03_業務ロジック 4章の購入者取消の条件。`canReissuePickupCode`：`pickup` が null でないとき true。

### API-12 注文の取消（購入者）

- 入力：`{"version": 7}`
- 処理：03_業務ロジック 7.3。判定順は03_業務ロジック 4章の末尾（version不一致 → 409 `CONFLICTING_UPDATE`、取消条件を満たさない → 422 `CANCEL_NOT_ALLOWED`）。
- 出力（200）：API-11と同じ形。

### API-37 受取QRの再発行

- 入力：`{"version": 7}`
- 処理：03_業務ロジック 9.5の再発行。QR表示可否が偽なら409 `INVALID_STATE`。監査 `PICKUP_TOKEN_REISSUED`。
- 出力（200）：API-11と同じ形（新しい `pickup`）。

### API-13 Stripe Webhook

- 入力：Stripeのイベント（生の本文を署名検証に使うため、JSONとして解析する前の bytes を受け取る）
- 処理：03_業務ロジック 5.4。
- 出力：200 `{"received": true}`、署名不正は400。

### API-14 店員の注文一覧

- 入力（クエリ）：`tab`（必須）、`page`、`pageSize`

| tab | 対象 | 並び順 |
|---|---|---|
| ACTIVE | RECEIVED、PREPARING | accepted_at の昇順（受付順） |
| DELAYED | is_delayed=true かつ RECEIVED・PREPARING・ACTION_REQUIRED | accepted_at の昇順 |
| ACTION_REQUIRED | ACTION_REQUIRED | accepted_at の昇順 |
| READY | READY | ready_at の昇順 |
| EXPIRED | EXPIRED | expired_at の昇順 |
| DONE | PICKED_UP・CANCELLED・EXPIRED_RETURNED のうち、`coalesce(picked_up_at, cancelled_at, returned_to_stock_at)` の日付（Asia/Tokyo）が今日のもの | 同じ値の降順 |

- 処理：自店舗の対象注文に03_業務ロジック 8章の同期を行ってから返す。
- 出力（200）：`items` の各要素は `{"orderId", "orderNumber", "status", "statusLabel", "acceptedAt", "originalReadyAt", "currentReadyAt", "isDelayed", "delayPending"（確認中ならtrue）, "totalQuantity", "shortageRisk"（明細のどれかの在庫で欠品見込みがあればtrue）, "pickupDeadlineAt"}`。加えて、レスポンスのトップレベルに `"tabCounts": {"ACTIVE": 3, "DELAYED": 1, "ACTION_REQUIRED": 0, "READY": 2, "EXPIRED": 0, "DONE": 5}` を返す。

### API-41 店員の注文詳細

- 処理：03_業務ロジック 8章の同期を行ってから返す。
- 出力（200）：API-11の形から `pickup`・`canCancel`・`canReissuePickupCode` を除き、次を加えたもの：`"items[].shortageRiskQuantity"`（その在庫の欠品見込み数）、`"items[].onHandQuantity"`、`"payment": {"status", "authorizedAmountYen", "capturedAmountYen", "failureCode"}`、`"allowedActions": ["START_PREPARATION", "REGISTER_SHORTAGE", "REGISTER_DELAY", "MARK_READY", "RETURN_TO_STOCK"]`（状態から可能な操作だけ）。

allowedActions の規則：RECEIVED → START_PREPARATION・REGISTER_DELAY。PREPARING → REGISTER_DELAY、決済が AUTHORIZED なら REGISTER_SHORTAGE・MARK_READY も。ACTION_REQUIRED → REGISTER_DELAY、決済が AUTHORIZED または FAILED（last_operation=CAPTURE）なら MARK_READY も（決済確定の再試行）。EXPIRED → RETURN_TO_STOCK。

### API-15 準備開始

- 入力：`{"version": 3}`
- 処理：T4。RECEIVED以外は409 `INVALID_STATE`。
- 出力（200）：API-41と同じ形。

### API-16 欠品の登録

- 入力：`{"version": 4, "items": [{"orderItemId": "…", "shortageQuantity": 1}]}`（指定しない明細は変更しない）
- 処理：03_業務ロジック 6.3。PREPARING以外、または決済が AUTHORIZED 以外は409 `INVALID_STATE`。shortageQuantity が 0未満・ordered超・既存未満、または他の注文の明細IDは400。取消になった場合はトランザクション後に RELEASE を呼ぶ（03_業務ロジック 7.3の3・4と同じ）。
- 出力（200）：API-41と同じ形（取消になった場合は status=CANCELLED）。

### API-17 遅延の登録

- 入力：`{"version": 4, "reasonCode": "CONGESTION", "reasonText": null, "updatedReadyAt": "2026-10-31T19:20:00+09:00"}`（確認中は `updatedReadyAt: null`）
- 処理：03_業務ロジック 7.1。
- 出力（200）：API-41と同じ形。

### API-18 準備完了（決済確定）

- 入力：`{"version": 5}`
- 処理：PREPARING で決済が AUTHORIZED、または ACTION_REQUIRED で決済が AUTHORIZED・FAILED(CAPTURE) のとき、確定額＝Σ(単価×(ordered−shortage))で CAPTURE する。段階1（トランザクション）で、各明細の出庫数が帳簿在庫以下であることを確認し（03_業務ロジック 6.4）、決済を CAPTURING（新しい操作。FAILED(CAPTURE) からの再実行は `operation_attempt += 1`）、注文の `version += 1` にしてコミットする。その後 Stripe を呼び、結果を反映する。確定額が0になる状態（全欠品）は03_業務ロジック 6.3で取消済みのため発生しない。
- 出力：200（READY）／409 `INVALID_STATE`（状態・決済が条件外。決済が CAPTURING・UNKNOWN の場合は `message` を「決済確定の結果を確認しています。しばらくしてから再度ご確認ください。」にする）／409 `INSUFFICIENT_STOCK`（帳簿在庫が足りない。欠品登録を促す）／決済失敗・結果不明は200で status=ACTION_REQUIRED を返し、画面で「決済確定ができませんでした。時間をおいて再実行してください」と表示する。

### API-19 受け取り照合

- 入力：`{"qrValue": "PA1.…"}` または `{"orderNumber": "P000123", "manualCode": "123456"}`
- 処理：03_業務ロジック 9.6。
- 出力（200）：

```json
{"canHandOver": true, "reasonCode": null, "reasonMessage": null,
 "pickupVerificationId": "…", "orderId": "…", "orderNumber": "P000123", "status": "READY",
 "items": [{"productName": "コットンT 001", "colorName": "ホワイト", "size": "M", "preparedQuantity": 2}],
 "capturedAmountYen": 1980, "pickupDeadlineAt": "…", "version": 8}
```

`reasonCode=OTHER_STORE` のときは `canHandOver`・`reasonCode`・`reasonMessage`・`orderNumber` 以外を null にする。

不可の reasonMessage：OTHER_STORE＝別の店舗の注文です、NOT_READY＝まだ準備が完了していません、CANCELLED＝取り消された注文です、ALREADY_PICKED_UP＝受け取り済みです、RETURNED_TO_STOCK＝受取期限を過ぎ、商品を棚に戻した注文です、PAYMENT_NOT_CAPTURED＝お支払いが確定していません。

### API-20 引き渡し確定

- 入力：`{"pickupVerificationId": "…", "version": 8}`
- 処理：03_業務ロジック 9.6の引き渡しの判定（version不一致 → 409 `CONFLICTING_UPDATE`、状態・決済が条件外 → 409 `INVALID_STATE`、トークン不一致・失効・使用済み → 422 `INVALID_PICKUP_CODE`）の後、T12。
- 出力（200）：`{"orderId": "…", "orderNumber": "…", "status": "PICKED_UP", "pickedUpAt": "…"}`

### API-35 期限切れ品を棚に戻す

- 入力：`{"version": 9}`
- 処理：T14。EXPIRED以外は409 `INVALID_STATE`。
- 出力（200）：API-41と同じ形。

### API-21 自店舗の受付状態・営業時間

- 出力（200）：

```json
{"storeId": "…", "name": "テスト新宿店", "acceptingOrders": true, "acceptanceReason": null,
 "acceptanceChangedAt": null, "version": 2,
 "defaultHours": {"opensAt": "10:00", "closesAt": "21:00", "regularClosedWeekdays": []},
 "days": [{"date": "2026-10-31", "closed": false, "opensAt": "10:00", "closesAt": "21:00",
           "source": "DEFAULT", "overrideVersion": null}]}
```

`days` は今日から14日分。`source` は `DEFAULT`（通常営業・定休）または `OVERRIDE`（business_hoursの行）。

### API-22 受付停止・再開

- 入力：`{"acceptingOrders": false, "reason": "準備担当が不在のため", "version": 2}`（停止時は reason 必須、再開時は null）
- 出力（200）：API-21と同じ形。停止中も既存注文の処理、POS・在庫の操作はできる。

### API-23 営業時間の登録

- 入力：`{"useDefault": false, "closed": false, "opensAt": "10:00", "closesAt": "20:00", "version": null}`。`useDefault=true` なら上書きの行を削除して通常営業に戻す。既存の行を更新する場合は `version` 必須。
- 制約：今日以降・60日以内の日付。今日の閉店時刻を早める変更で、今日受付済みの注文（RECEIVED・PREPARING）の予定時刻が新しい閉店時刻を超える場合も登録は許すが、レスポンスに `warnings: ["今日の受付済み注文のうちN件の予定時刻が閉店後になります"]` を入れる。
- 出力（200）：API-21と同じ形＋`warnings`。

### API-24 店員用の商品検索

- 入力（クエリ）：`sku`（完全一致。大文字化して検索）または `q`（商品名の部分一致）。どちらか必須。`page`、`pageSize`。
- 出力（200）：`items` の各要素は `{"productVariantId", "sku", "productName", "colorName", "size", "priceYen", "inventoryId", "onHandQuantity", "reservedQuantity", "availableQuantity"}`（自店舗の在庫）。

### API-25 POSの見積もり

- 入力：`{"items": [{"productVariantId": "…", "quantity": 2}]}`（数量1〜99、同じSKUの重複不可）
- 処理：保存しない。単価・合計・販売可能数を計算する。存在しない・非アクティブなSKU、または自店舗の在庫行がないSKUは404 `PRODUCT_NOT_FOUND`（`details` に該当のproductVariantId）。
- 出力（200）：`{"lines": [{"productVariantId", "sku", "productName", "colorName", "size", "unitPriceYen", "quantity", "lineAmountYen", "availableQuantity", "reservedQuantity", "ok": true, "reasonCode": null}], "totalQuantity": 3, "totalAmountYen": 4970, "allOk": true}`。`ok=false` の reasonCode：`RESERVED_FOR_EC`（帳簿在庫は足りるがEC確保で足りない）または `OUT_OF_STOCK`。

### API-26 POS売上の確定

- 入力：`{"items": [{"productVariantId": "…", "quantity": 2}], "clientTotalAmountYen": 4970, "paymentMethod": "CASH"}`
- 処理：SKUの確認（API-25と同じ。404 `PRODUCT_NOT_FOUND`）→在庫行をID順にロック→03_業務ロジック 6.1で販売可能数を確認（不足は409 `INSUFFICIENT_STOCK`、`details` にAPI-25と同じ lines）→合計を照合（不一致は409 `CALCULATION_CHANGED`）→売上・明細・在庫・履歴・監査を1トランザクションで登録。
- 出力（201）：`{"saleId": "…", "saleNumber": "S000045", "status": "COMPLETED", "totalQuantity": 3, "totalAmountYen": 4970, "paymentMethod": "CASH", "soldAt": "…", "lines": […]}`

### API-27 POS売上一覧

- 入力（クエリ）：`date`（既定は今日）、`page`、`pageSize`
- 出力（200）：`items` は API-26 の出力の形に `voidedAt`・`voidReason`・`staffEmail`・`version`・`canVoid`（03_業務ロジック 6.7の条件）を加えたもの。トップレベルに `"summary": {"completedCount", "completedAmountYen", "voidedCount"}`。

### API-28 POS売上の取消

- 入力：`{"reason": "数量の入力誤り", "version": 0}`（reason 1〜200文字）
- 処理：03_業務ロジック 6.7。他店舗の売上は404（3章）。自店舗で当日・COMPLETED でなければ409 `INVALID_STATE`。
- 出力（200）：API-27の要素と同じ形。

### API-29 在庫一覧

- 入力（クエリ）：`q`（商品名の部分一致）、`sku`（前方一致）、`filter`（`ALL`・既定、`OUT_OF_STOCK`＝販売可能数0、`SHORTAGE_RISK`＝欠品見込みあり）、`page`、`pageSize`
- 出力（200）：`items` の各要素は `{"inventoryId", "productVariantId", "sku", "productName", "colorName", "size", "priceYen", "onHandQuantity", "reservedQuantity", "availableQuantity", "shortageRiskQuantity", "version", "updatedAt"}`。並び順は sku の昇順。

### API-30 在庫履歴

- 入力（クエリ）：`page`、`pageSize`
- 出力（200）：`{"inventory": {API-29の要素と同じ}, "items": [{"transactionId", "type", "typeLabel", "quantityDelta", "onHandAfter", "countedQuantity", "referenceLabel"（注文番号または売上番号）, "reason", "actorEmail", "occurredAt"}], "page", "pageSize", "totalCount"}`。新しい順。

typeLabel：INITIAL＝初期登録、RECEIVE＝入荷、POS_SALE＝店頭販売、POS_VOID＝店頭販売の取消、EC_PICKUP_OUT＝EC注文の準備完了、EC_SHORTAGE＝EC注文の欠品、EC_CANCEL_RETURN＝EC注文の取消で戻し、EC_EXPIRED_RETURN＝受取期限切れで戻し、STOCKTAKE＝棚卸、DAMAGE＝破損・紛失。

### API-31 入荷の登録

- 入力：`{"quantity": 3, "reason": null, "version": 4}`
- 処理：03_業務ロジック 6.6。
- 出力（200）：`{"inventory": {API-29の要素}, "transactionId": "…", "shortageRiskQuantity": 0, "shortageRiskOrderCount": 0}`

### API-32 棚卸・破損の登録

- 入力：棚卸 `{"type": "STOCKTAKE", "countedQuantity": 2, "reason": "棚卸で不足", "version": 4}`、破損 `{"type": "DAMAGE", "quantity": 1, "reason": "汚れ", "version": 4}`
- 処理：03_業務ロジック 6.6。
- 出力（200）：API-31と同じ形。

### API-38 ジョブ実行

- 入力：ヘッダー `X-Job-Secret`（環境変数 `JOB_SECRET` と一致しなければ403）。本文 `{"jobs": ["J-01", "J-02"]}`（省略時は J-01〜J-05）。
- 処理：03_業務ロジック 12章。全体で25秒を超えたら残りのジョブを打ち切る。
- 出力（200）：`{"results": [{"job": "J-01", "result": "SUCCESS", "processedCount": 3}]}`

### API-39 送信メール一覧（開発用）

- 有効条件：環境変数 `DEV_TOOLS_ENABLED=true`。偽なら404。
- 対象：購入者は自分宛てのメール、店員は自店舗の注文に関するメール。
- 出力（200）：`items` の各要素は `{"notificationId", "type", "recipientEmail", "subject", "bodyText", "status", "attemptCount", "sentAt", "createdAt", "orderId", "orderNumber"}`。新しい順。
