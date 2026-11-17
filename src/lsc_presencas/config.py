"""Caminhos e configuração. Tudo vem de variáveis de ambiente (ver .env.example)."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

NOME_APP = "LSC-Presencas"
NOME_BD = "presencas.db"

load_dotenv(find_dotenv(usecwd=True))


def _pasta(caminho: Path) -> Path:
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def pasta_app() -> Path:
    """Pasta de dados da app: base de dados, backups e ficheiros gerados."""
    definida = os.environ.get("LSC_APP_DIR", "").strip()
    if definida:
        return _pasta(Path(os.path.expandvars(definida)).expanduser())
    base = os.environ.get("APPDATA") or str(Path.home())
    return _pasta(Path(base) / NOME_APP)


def caminho_bd() -> Path:
    return pasta_app() / NOME_BD


def url_bd() -> str:
    return f"sqlite:///{caminho_bd().as_posix()}"


def pasta_backups() -> Path:
    return _pasta(pasta_app() / "backups")


def pasta_saidas() -> Path:
    return _pasta(pasta_app() / "saidas")


def pasta_dados_reais() -> Path | None:
    """Pasta local com o Excel real (só para a importação). None se não estiver definida."""
    definida = os.environ.get("LSC_DADOS_DIR", "").strip()
    return Path(os.path.expandvars(definida)).expanduser() if definida else None
