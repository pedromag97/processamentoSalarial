"""Várias pessoas ao mesmo tempo sobre o mesmo servidor: bloqueios entre operações.

No PostgreSQL usam-se "advisory locks" ligados à transação: libertam-se sozinhos no commit ou
no rollback, mesmo que o programa caia. Com a base de dados em ficheiro (SQLite) só há uma
pessoa de cada vez, por isso estas funções não fazem nada.

- Quem altera marcações ou lançamentos pede o bloqueio PARTILHADO (várias pessoas ao mesmo
  tempo) antes de confirmar que o mês não está fechado.
- Quem fecha ou reabre um mês pede o bloqueio EXCLUSIVO: espera que acabem as alterações em
  curso e, enquanto fecha, ninguém grava. Assim a fotografia do fecho bate sempre certo com
  o que ficou gravado.
"""

from contextlib import contextmanager

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

# Números arbitrários, mas fixos: identificam os bloqueios desta app no servidor.
CHAVE_MARCACOES = 5_727_001
CHAVE_MIGRACOES = 5_727_002


def _em_servidor(sessao: Session) -> bool:
    return sessao.get_bind().dialect.name == "postgresql"


def alterar_marcacoes(sessao: Session) -> None:
    """Pede o bloqueio partilhado até ao fim da transação em curso."""
    if _em_servidor(sessao):
        sessao.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": CHAVE_MARCACOES})


def fechar_ou_reabrir(sessao: Session) -> None:
    """Pede o bloqueio exclusivo até ao fim da transação em curso."""
    if _em_servidor(sessao):
        sessao.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CHAVE_MARCACOES})


@contextmanager
def so_um_a_migrar(engine: Engine):
    """Só um PC de cada vez corre as migrações; os outros esperam e depois não têm nada a
    fazer."""
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as ligacao:
        ligacao.execute(text("SELECT pg_advisory_lock(:k)"), {"k": CHAVE_MIGRACOES})
        try:
            yield
        finally:
            ligacao.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CHAVE_MIGRACOES})
            ligacao.commit()


def libertar_leitura(sessao: Session) -> None:
    """Fecha a transação de leitura sem deitar fora o que está carregado.

    A interface usa uma única sessão. Sem isto, depois de qualquer consulta a ligação ficava
    "a meio de uma transação" no servidor durante horas. Só atua se não houver nada por gravar.
    """
    if not sessao.in_transaction() or sessao.new or sessao.dirty or sessao.deleted:
        return
    expirar = sessao.expire_on_commit
    sessao.expire_on_commit = False
    try:
        sessao.commit()
    finally:
        sessao.expire_on_commit = expirar
