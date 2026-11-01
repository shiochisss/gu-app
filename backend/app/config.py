from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

MAX_ORDER_QUANTITY = 10
WORK_MINUTES_PER_ITEM = 2
WORK_MINUTES_PER_ORDER = 10
BUFFER_MINUTES = 15
MAX_LEAD_MINUTES = 60
CLOSE_MARGIN_MINUTES = 15
ORDER_CUTOFF_MINUTES = 60
ESTIMATE_TTL_MINUTES = 10
HOLD_TTL_MINUTES = 15
READY_TOLERANCE_MINUTES = 5
PICKUP_KEEP_DAYS = 7
BUSINESS_DAY_SEARCH_LIMIT = 31
ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_MINUTES = 15
PICKUP_QR_LIMIT = 60
PICKUP_QR_WINDOW_MINUTES = 10
PICKUP_MANUAL_LIMIT = 5
PICKUP_MANUAL_WINDOW_MINUTES = 10
MAIL_MAX_ATTEMPTS = 5
PAYMENT_STALE_MINUTES = 5
IDEMPOTENCY_TTL_HOURS = 24
IDEMPOTENCY_LOCK_MINUTES = 2
REFRESH_REUSE_GRACE_SECONDS = 30
POS_MAX_LINE_QUANTITY = 99
TIMEZONE = "Asia/Tokyo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["local", "azure-test", "production"]
    database_url: SecretStr
    test_database_url: SecretStr | None = None
    jwt_secret: SecretStr
    qr_secret: SecretStr
    bff_shared_secret: SecretStr
    job_secret: SecretStr
    stripe_secret_key: SecretStr
    stripe_webhook_secret: SecretStr
    frontend_base_url: AnyHttpUrl
    mail_mode: Literal["simulate", "smtp"]
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: SecretStr | None = None
    smtp_password: SecretStr | None = None
    mail_from: SecretStr | None = None
    dev_tools_enabled: bool = False
    overdue_policy_text: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
                valid = url.drivername == "postgresql+psycopg" and bool(url.database)
            except Exception:
                valid = False
            if not valid:
                raise ValueError("PostgreSQLの同期psycopg接続URLを指定してください")
        return value

    @field_validator("jwt_secret", "qr_secret", "bff_shared_secret", "job_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 64:
            raise ValueError("秘密値は64文字以上で指定してください")
        return value

    @field_validator("stripe_secret_key")
    @classmethod
    def test_stripe_only(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("sk_test_"):
            raise ValueError("Stripeはsk_test_で始まるテストキーだけ使用できます")
        return value

    @model_validator(mode="after")
    def validate_related_settings(self) -> "Settings":
        if self.jwt_secret == self.qr_secret:
            raise ValueError("JWT_SECRETとQR_SECRETは別の値にしてください")
        if self.mail_mode == "smtp" and not all(
            [
                self.smtp_host,
                self.smtp_port,
                self.smtp_username,
                self.smtp_password,
                self.mail_from,
            ]
        ):
            raise ValueError("SMTPモードにはSMTP接続設定とMAIL_FROMが必要です")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
