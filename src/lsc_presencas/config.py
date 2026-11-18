"""Caminhos e configuração. Tudo vem de variáveis de ambiente (ver .env.example)."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import keyring
import keyring.errors
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import URL

NOME_APP = "LSC-Presencas"
NOME_BD = "presencas.db"

# O executável instalado nunca lê um .env (usa sempre a pasta de dados do utilizador).
if not getattr(sys, "frozen", False):
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


def url_local() -> str:
    """Base de dados em ficheiro (SQLite), na pasta de dados deste PC."""
    return f"sqlite:///{caminho_bd().as_posix()}"


def url_bd() -> str:
    """Onde está a base de dados, por esta ordem:

    1. a variável de ambiente `LSC_BD_URL` (desenvolvimento e testes);
    2. o servidor configurado em `ligacao.json` (palavra-passe no cofre do Windows);
    3. o ficheiro local.
    """
    definido = os.environ.get("LSC_BD_URL", "").strip()
    if definido:
        return definido
    ligacao = ler_ligacao()
    if ligacao is not None:
        return url_servidor(ligacao, ler_senha(ligacao))
    return url_local()


def usa_servidor() -> bool:
    return not url_bd().startswith("sqlite")


def descricao_bd() -> str:
    """Onde estão os dados, para mostrar no ecrã (sem a palavra-passe)."""
    ligacao = ler_ligacao()
    if os.environ.get("LSC_BD_URL", "").strip():
        return "definida pela variável LSC_BD_URL"
    if ligacao is not None:
        return (
            f"servidor {ligacao.servidor}:{ligacao.porta}, base de dados «{ligacao.base}», "
            f"utilizador «{ligacao.utilizador}»"
        )
    return f"ficheiro neste PC: {caminho_bd()}"


# --- Ligação a um servidor PostgreSQL ---------------------------------------------------------

NOME_COFRE = "LSC-Presencas"
PORTA_POSTGRESQL = 5432


@dataclass(frozen=True)
class Ligacao:
    servidor: str
    base: str
    utilizador: str
    porta: int = PORTA_POSTGRESQL

    @property
    def chave(self) -> str:
        """Nome com que a palavra-passe fica guardada no cofre do Windows."""
        return f"{self.utilizador}@{self.servidor}:{self.porta}/{self.base}"


def ficheiro_ligacao() -> Path:
    return pasta_app() / "ligacao.json"


def ler_ligacao() -> Ligacao | None:
    """A ligação ao servidor guardada neste PC (None = usa o ficheiro local)."""
    try:
        dados = json.loads(ficheiro_ligacao().read_text(encoding="utf-8"))
        return Ligacao(
            servidor=str(dados["servidor"]),
            base=str(dados["base"]),
            utilizador=str(dados["utilizador"]),
            porta=int(dados.get("porta", PORTA_POSTGRESQL)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def guardar_ligacao(ligacao: Ligacao, senha: str) -> None:
    """Guarda a ligação. A palavra-passe vai para o cofre de credenciais do Windows, nunca
    para o ficheiro."""
    keyring.set_password(NOME_COFRE, ligacao.chave, senha)
    ficheiro_ligacao().write_text(
        json.dumps(
            {
                "servidor": ligacao.servidor,
                "porta": ligacao.porta,
                "base": ligacao.base,
                "utilizador": ligacao.utilizador,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def remover_ligacao() -> None:
    """Volta a usar o ficheiro local (não apaga nada no servidor)."""
    ligacao = ler_ligacao()
    ficheiro_ligacao().unlink(missing_ok=True)
    if ligacao is not None:
        try:
            keyring.delete_password(NOME_COFRE, ligacao.chave)
        except keyring.errors.PasswordDeleteError:
            pass


def ler_senha(ligacao: Ligacao) -> str:
    return keyring.get_password(NOME_COFRE, ligacao.chave) or ""


def url_servidor(ligacao: Ligacao, senha: str) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=ligacao.utilizador,
        password=senha,
        host=ligacao.servidor,
        port=ligacao.porta,
        database=ligacao.base,
    ).render_as_string(hide_password=False)


def caminho_icone() -> Path:
    """O símbolo do programa (vai dentro do pacote, por isso também dentro do executável)."""
    return Path(__file__).parent / "recursos" / "icone.png"


def pasta_backups() -> Path:
    return _pasta(pasta_app() / "backups")


def pasta_saidas() -> Path:
    return _pasta(pasta_app() / "saidas")


def pasta_dados_reais() -> Path | None:
    """Pasta local com o Excel real (só para a importação). None se não estiver definida."""
    definida = os.environ.get("LSC_DADOS_DIR", "").strip()
    return Path(os.path.expandvars(definida)).expanduser() if definida else None
