from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FieldError(ApiModel):
    field: str
    code: str
    message: str


class ErrorResponse(ApiModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    field_errors: list[FieldError] = Field(default_factory=list)
    trace_id: str
    latest_resource: dict[str, Any] | None = None


class HealthResponse(ApiModel):
    status: str = "ok"
