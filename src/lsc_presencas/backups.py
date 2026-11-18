"""Cópias de segurança da base de dados (guardam-se as últimas 30)."""

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine

from . import config

MAX_BACKUPS = 30
PREFIXO = "presencas_"


def fazer_backup(engine: Engine, etiqueta: str = "", pasta: Path | None = None) -> Path:
    """Copia a base de dados para a pasta de backups e apaga as cópias mais antigas.

    Usa a cópia própria do SQLite, que é segura mesmo com a base de dados aberta.
    """
    pasta = pasta or config.pasta_backups()
    pasta.mkdir(parents=True, exist_ok=True)
    nome = PREFIXO + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if etiqueta:
        nome += f"_{etiqueta}"
    destino = pasta / f"{nome}.db"

    origem = engine.raw_connection()
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.driver_connection.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()

    limpar(pasta)
    return destino


def listar(pasta: Path | None = None) -> list[Path]:
    """Backups existentes, do mais antigo para o mais recente."""
    pasta = pasta or config.pasta_backups()
    return sorted(pasta.glob(f"{PREFIXO}*.db"))


def limpar(pasta: Path | None = None, manter: int = MAX_BACKUPS) -> None:
    existentes = listar(pasta)
    for antigo in existentes[: max(len(existentes) - manter, 0)]:
        antigo.unlink(missing_ok=True)
