"""Ligação à base de dados (ficheiro SQLite ou servidor PostgreSQL) e migrações."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from . import config

PASTA_MIGRACOES = Path(__file__).parent / "migracoes"
TEMPO_LIMITE_LIGACAO = 8  # segundos


def criar_engine(url: str | None = None) -> Engine:
    url = url or config.url_bd()
    if not url.startswith("sqlite"):
        # Servidor: confirma a ligação antes de a usar (a rede ou a VPN podem ter caído).
        return create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": TEMPO_LIMITE_LIGACAO}
        )

    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _ativar_chaves_estrangeiras(ligacao, _registo):
        cursor = ligacao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def criar_fabrica_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def testar_ligacao(url: str) -> None:
    """Liga-se e faz uma consulta mínima. Levanta a exceção do controlador se falhar."""
    engine = criar_engine(url)
    try:
        with engine.connect() as ligacao:
            ligacao.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def config_alembic(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(PASTA_MIGRACOES).replace("%", "%%"))
    cfg.set_main_option("sqlalchemy.url", (url or config.url_bd()).replace("%", "%%"))
    return cfg


def migrar(url: str | None = None) -> None:
    """Leva a base de dados até à última migração (cria-a se não existir)."""
    from . import concorrencia

    engine = criar_engine(url)
    try:
        with concorrencia.so_um_a_migrar(engine):
            command.upgrade(config_alembic(url), "head")
    finally:
        engine.dispose()


def criar_vazia(url: str) -> None:
    """Cria todas as tabelas de uma vez e marca a base de dados como estando na última
    migração. Mais rápido do que correr as migrações; usado nas cópias de segurança."""
    from .modelos import Base

    engine = criar_engine(url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    command.stamp(config_alembic(url), "head")
