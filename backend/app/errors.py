from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import ErrorResponse, FieldError

MESSAGES = {
    "VALIDATION_ERROR": "入力内容を確認してください。",
    "NOT_FOUND": "対象が見つかりません。",
    "FORBIDDEN": "この操作は行えません。",
    "INTERNAL_ERROR": "エラーが発生しました。時間をおいてお試しください。",
}


def error_response(request: Request, status: int, code: str, **kwargs) -> JSONResponse:
    body = ErrorResponse(
        code=code,
        message=MESSAGES[code],
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
