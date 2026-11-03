import app.models  # noqa: F401 -- registers all tables in Base.metadata
from alembic import context
from app.config import get_settings
from app.db import Base, create_db_engine

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=(context.config.attributes.get("settings") or get_settings()).connection_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    settings = context.config.attributes.get("settings") or get_settings()
    url = settings.connection_url()
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        confirmed = context.get_x_argument(as_dictionary=True).get("confirm_database")
        if confirmed != url.database:
            raise RuntimeError(
                "外部DBのマイグレーションは承認後に -x confirm_database=<DB名> を指定してください。"
            )
    engine = create_db_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
