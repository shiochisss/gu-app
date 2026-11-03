from datetime import datetime
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import SecretStr, field_validator

from app.schemas.common import ApiModel


class Credentials(ApiModel):
    email: str
    password: SecretStr

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        try:
            validate_email(value, check_deliverability=False, test_environment=True)
        except EmailNotValidError:
            raise ValueError("メールアドレスの形式を確認してください") from None
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: SecretStr) -> SecretStr:
        if not 12 <= len(value.get_secret_value()) <= 128:
            raise ValueError("パスワードは12〜128文字で入力してください")
        return value


class RefreshInput(ApiModel):
    refresh_token: SecretStr


class UserInfo(ApiModel):
    user_id: str
    email: str
    role: Literal["CUSTOMER", "STAFF"]
    store_id: str | None = None
    store_name: str | None = None


class SessionTokens(ApiModel):
    user: UserInfo
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
