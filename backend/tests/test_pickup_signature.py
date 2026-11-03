from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import ApiError
from app.security.pickup import decode, manual_code, qr_value


def test_qr_is_stable_signed_and_contains_no_personal_information():
    token = SimpleNamespace(
        order_id=str(uuid4()), token_id=str(uuid4()), issued_at=datetime(2026, 11, 3, tzinfo=UTC)
    )
    value = qr_value("q" * 64, token)
    assert qr_value("q" * 64, token) == value
    assert decode("q" * 64, value) == {
        "o": token.order_id,
        "t": token.token_id,
        "i": int(token.issued_at.timestamp()),
    }
    assert len(manual_code("q" * 64, token.token_id)) == 6
    with pytest.raises(ApiError):
        decode("x" * 64, value)
    with pytest.raises(ApiError):
        decode("q" * 64, value[:-1] + ("A" if value[-1] != "A" else "B"))


def test_manual_code_can_start_with_zero():
    found = next(
        str(index) for index in range(100) if manual_code("q" * 64, str(index)).startswith("0")
    )
    assert len(manual_code("q" * 64, found)) == 6
