"""Ambiente do Alembic. O URL vem da configuração da app (nunca de um caminho fixo)."""

from alembic import context
from sqlalchemy import create_engine

from lsc_presencas import config as config_app
from lsc_presencas.modelos import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or config_app.url_bd()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as ligacao:
        context.configure(connection=ligacao, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
