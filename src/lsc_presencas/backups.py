"""Cópias de segurança da base de dados (guardam-se as últimas 30).

Com a base de dados em ficheiro, copia-se o ficheiro. Com um servidor, descarregam-se todos
os dados para um ficheiro SQLite local, que a app sabe abrir e voltar a enviar. Isto não
dispensa as cópias de segurança feitas no próprio servidor.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine

from . import config, db, transferencia

MAX_BACKUPS = 30
PREFIXO = "presencas_"


def fazer_backup(engine: Engine, etiqueta: str = "", pasta: Path | None = None) -> Path:
    """Copia a base de dados para a pasta de backups e apaga as cópias mais antigas."""
    pasta = pasta or config.pasta_backups()
    pasta.mkdir(parents=True, exist_ok=True)
    nome = PREFIXO + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if etiqueta:
        nome += f"_{etiqueta}"
    destino = pasta / f"{nome}.db"

    if engine.dialect.name == "sqlite":
        _copiar_ficheiro(engine, destino)
    else:
        _descarregar_do_servidor(engine, destino)

    limpar(pasta)
    return destino


def _copiar_ficheiro(engine: Engine, destino: Path) -> None:
    """Cópia própria do SQLite, segura mesmo com a base de dados aberta."""
    origem = engine.raw_connection()
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.driver_connection.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()


def _descarregar_do_servidor(engine: Engine, destino: Path) -> None:
    url = f"sqlite:///{destino.as_posix()}"
    try:
        db.criar_vazia(url)
        local = db.criar_engine(url)
        try:
            transferencia.copiar(engine, local, substituir=True)
        finally:
            local.dispose()
    except Exception:
        destino.unlink(missing_ok=True)  # não fica uma cópia a meio
        raise


def listar(pasta: Path | None = None) -> list[Path]:
    """Backups existentes, do mais antigo para o mais recente."""
    pasta = pasta or config.pasta_backups()
    return sorted(pasta.glob(f"{PREFIXO}*.db"))


def limpar(pasta: Path | None = None, manter: int = MAX_BACKUPS) -> None:
    existentes = listar(pasta)
    for antigo in existentes[: max(len(existentes) - manter, 0)]:
        antigo.unlink(missing_ok=True)
