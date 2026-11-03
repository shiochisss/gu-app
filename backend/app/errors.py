from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import ErrorResponse, FieldError

MESSAGES = {
    "VALIDATION_ERROR": "入力内容を確認してください。",
    "CSRF_REJECTED": "画面を再読み込みしてから、もう一度お試しください。",
    "UNAUTHENTICATED": "ログインしてください。",
    "TOKEN_EXPIRED": "ログインの有効期限が切れました。",
    "INVALID_CREDENTIALS": "メールアドレスまたはパスワードが正しくありません。",
    "FORBIDDEN": "この操作は行えません。",
    "NOT_FOUND": "対象が見つかりません。",
    "STORE_NOT_FOUND": "対象が見つかりません。",
    "PRODUCT_NOT_FOUND": "対象が見つかりません。",
    "ORDER_NOT_FOUND": "対象が見つかりません。",
    "EMAIL_ALREADY_REGISTERED": "このメールアドレスは登録済みです。",
    "CONFLICTING_UPDATE": "ほかの操作で内容が更新されました。最新の内容を確認してください。",
    "CALCULATION_CHANGED": "金額または準備完了予定が変わりました。内容を確認してください。",
    "ESTIMATE_EXPIRED": "確認画面の有効期限が切れました。もう一度確認してください。",
    "INSUFFICIENT_STOCK": "販売できる在庫が足りません。",
    "INVALID_STATE": "現在の状態ではこの操作は行えません。",
    "IDEMPOTENCY_IN_PROGRESS": "処理中です。しばらくしてから確認してください。",
    "IDEMPOTENCY_KEY_REUSED": "同じ操作番号で別の内容が送信されました。",
    "ORDER_LIMIT_EXCEEDED": "1回の注文は合計10点までです。",
    "STORE_NOT_ACCEPTING": "この店舗は現在、注文の受付を停止しています。",
    "ORDER_CLOSED": "本日の注文受付は終了しました。",
    "OUT_OF_STOCK": "在庫が足りない商品があります。",
    "CAPACITY_FULL": "混雑のため、閉店までに準備が間に合いません。",
    "TERMS_NOT_AGREED": "受取期限と期限を過ぎた場合の扱いを確認してください。",
    "PAYMENT_DECLINED": "カードでのお支払いができませんでした。別のカードをお試しください。",
    "CANCEL_NOT_ALLOWED": "このご注文は取り消せません。",
    "INVALID_PICKUP_CODE": "QRコードまたは受取コードが正しくありません。",
    "RATE_LIMITED": "試行回数が多すぎます。しばらくしてからお試しください。",
    "NO_BUSINESS_DAY": "営業日を判定できませんでした。店舗の営業時間を確認してください。",
    "PAYMENT_PROVIDER_ERROR": "決済サービスに接続できませんでした。",
    "INTERNAL_ERROR": "エラーが発生しました。時間をおいてお試しください。",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, *, headers=None, **payload):
        self.status = status
        self.code = code
        self.headers = headers or {}
        self.payload = payload


def api_error(request: Request, exc: ApiError) -> JSONResponse:
    response = error_response(request, exc.status, exc.code, **exc.payload)
    response.headers.update(exc.headers)
    return response


def error_response(request: Request, status: int, code: str, **kwargs) -> JSONResponse:
    body = ErrorResponse(
        code=code,
        message=kwargs.pop("message", MESSAGES[code]),
        trace_id=request.state.request_id,
        **kwargs,
    )
    return JSONResponse(status_code=status, content=body.model_dump(by_alias=True))


def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for error in exc.errors():
        loc = list(error["loc"])
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc.pop(0)
        path = ""
        for part in loc:
            path += f"[{part}]" if isinstance(part, int) else ("." if path else "") + part
        kind = error["type"]
        if kind == "missing":
            code, message = "REQUIRED", "入力してください。"
        elif kind in {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}:
            code, message = "OUT_OF_RANGE", "指定された範囲で入力してください。"
        elif kind in {"string_too_long", "too_long"}:
            code, message = "TOO_LONG", "文字数を確認してください。"
        elif kind in {"enum", "literal_error", "value_error"}:
            code, message = "INVALID_VALUE", "入力内容を確認してください。"
        else:
            code, message = "INVALID_FORMAT", "形式を確認してください。"
        # Never serialize input/ctx or Pydantic's message: they can contain secrets.
        fields.append(FieldError(field=path, code=code, message=message))
    return error_response(request, 400, "VALIDATION_ERROR", field_errors=fields)


def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "NOT_FOUND", 403: "FORBIDDEN"}.get(exc.status_code, "INTERNAL_ERROR")
    return error_response(request, exc.status_code, code)
