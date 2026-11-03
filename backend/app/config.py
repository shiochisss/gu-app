from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

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
    database_url: SecretStr | None = None
    database_host: str | None = None
    database_port: int = 3306
    database_name: str | None = None
    database_user: SecretStr | None = None
    database_password: SecretStr | None = None
    database_ssl: bool = True
    seed_password: SecretStr | None = None
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
                valid = (
                    url.drivername == "mysql+pymysql"
                    and bool(url.database)
                    and set(url.query) <= {"charset"}
                    and url.query.get("charset", "utf8mb4") == "utf8mb4"
                )
            except Exception:
                valid = False
            if not valid:
                raise ValueError("MySQLの同期PyMySQL接続URLを指定してください（charset=utf8mb4）")
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
        if self.database_url is None and not all(
            [
                self.database_host,
                self.database_name,
                self.database_user and self.database_user.get_secret_value(),
                self.database_password and self.database_password.get_secret_value(),
            ]
        ):
            raise ValueError("DB接続URL、またはホスト・DB名・ユーザー名・パスワードが必要です")
        if not 1 <= self.database_port <= 65535:
            raise ValueError("DBポートは1〜65535で指定してください")
        if not self.database_ssl and self.connection_url().host not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("ローカルPC以外のMySQL接続ではTLSが必要です")
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

    def connection_url(self) -> URL:
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        return URL.create(
            "mysql+pymysql",
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
            username=self.database_user.get_secret_value() if self.database_user else None,
            password=self.database_password.get_secret_value() if self.database_password else None,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
