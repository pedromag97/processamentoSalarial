"""Ligação à base de dados SQLite e execução das migrações."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from . import config

PASTA_MIGRACOES = Path(__file__).parent / "migracoes"


def criar_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or config.url_bd())

    @event.listens_for(engine, "connect")
    def _ativar_chaves_estrangeiras(ligacao, _registo):
        cursor = ligacao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def criar_fabrica_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def config_alembic(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(PASTA_MIGRACOES).replace("%", "%%"))
    cfg.set_main_option("sqlalchemy.url", (url or config.url_bd()).replace("%", "%%"))
    return cfg


def migrar(url: str | None = None) -> None:
    """Leva a base de dados até à última migração (cria-a se não existir)."""
    command.upgrade(config_alembic(url), "head")
