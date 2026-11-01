import os

import pytest

# Test-only values, never load a developer's real credentials.
os.environ.update(
    {
        "APP_ENV": "local",
        "DATABASE_URL": "postgresql+psycopg://pickup_app:pickup_local@127.0.0.1:5432/pickup_test",
        "JWT_SECRET": "j" * 64,
        "QR_SECRET": "q" * 64,
        "BFF_SHARED_SECRET": "b" * 64,
        "JOB_SECRET": "o" * 64,
        "STRIPE_SECRET_KEY": "sk_test_fixture",
        "STRIPE_WEBHOOK_SECRET": "whsec_fixture",
        "FRONTEND_BASE_URL": "http://localhost:3000",
        "MAIL_MODE": "simulate",
    }
)


@pytest.fixture
def settings():
    from app.config import Settings

    return Settings(_env_file=None)
