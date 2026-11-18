import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lsc_presencas import db  # noqa: E402
from lsc_presencas.dados_base import carregar_dados_base  # noqa: E402
from lsc_presencas.modelos import Base  # noqa: E402


@pytest.fixture(autouse=True)
def pasta_da_app(tmp_path, monkeypatch):
    """Nenhum teste escreve na pasta de dados verdadeira (backups, ficheiros exportados)."""
    pasta = tmp_path / "app"
    monkeypatch.setenv("LSC_APP_DIR", str(pasta))
    monkeypatch.delenv("LSC_BD_URL", raising=False)
    return pasta


@pytest.fixture(autouse=True)
def cofre(monkeypatch):
    """Cofre de palavras-passe a fingir: os testes nunca tocam no cofre do Windows."""
    import keyring
    import keyring.errors

    guardadas: dict[tuple[str, str], str] = {}

    def apagar(servico, nome):
        if (servico, nome) not in guardadas:
            raise keyring.errors.PasswordDeleteError(nome)
        del guardadas[(servico, nome)]

    monkeypatch.setattr(keyring, "set_password", lambda s, n, p: guardadas.update({(s, n): p}))
    monkeypatch.setattr(keyring, "get_password", lambda s, n: guardadas.get((s, n)))
    monkeypatch.setattr(keyring, "delete_password", apagar)
    return guardadas


@pytest.fixture(scope="session")
def servidor_pg(tmp_path_factory):
    """Um servidor PostgreSQL verdadeiro, só para os testes (pacote `pgserver`)."""
    pgserver = pytest.importorskip("pgserver")
    from sqlalchemy import make_url

    servidor = pgserver.get_server(tmp_path_factory.mktemp("pg") / "dados", cleanup_mode="stop")
    yield make_url(servidor.get_uri()).set(drivername="postgresql+psycopg")
    servidor.cleanup()


_numero_bd = 0


@pytest.fixture
def url_pg(servidor_pg):
    """URL de uma base de dados PostgreSQL nova e vazia (sem tabelas)."""
    global _numero_bd
    from sqlalchemy import create_engine, text

    _numero_bd += 1
    nome = f"teste_{_numero_bd}"
    administracao = create_engine(servidor_pg, isolation_level="AUTOCOMMIT")
    with administracao.connect() as ligacao:
        ligacao.execute(text(f"CREATE DATABASE {nome}"))
    administracao.dispose()
    return servidor_pg.set(database=nome).render_as_string(hide_password=False)


@pytest.fixture
def fabrica_pg(url_pg):
    """Fábrica de sessões sobre PostgreSQL, com as migrações feitas e os dados base."""
    db.migrar(url_pg)
    engine = db.criar_engine(url_pg)
    fabrica = db.criar_fabrica_sessoes(engine)
    with fabrica() as sessao:
        carregar_dados_base(sessao)
        sessao.commit()
    yield fabrica
    engine.dispose()


@pytest.fixture(autouse=True)
def destruir_ecras():
    """Destrói os ecrãs Qt no fim de cada teste.

    Os ecrãs têm referências circulares (sinais ligados a funções do próprio ecrã). Sem isto,
    alguns só eram destruídos ao sair do Python, já depois da aplicação Qt, e o processo
    terminava com erro apesar de os testes passarem.
    """
    yield
    _limpar_qt()
    from lsc_presencas import contas

    contas.terminar_sessao()  # nenhum teste herda o login de outro


def _limpar_qt() -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    gc.collect()
    if QCoreApplication.instance() is not None:
        # Executa os `deleteLater()` pendentes (não há ciclo de eventos a correr nos testes).
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def pytest_sessionfinish(session, exitstatus):
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is not None:
        for janela in QApplication.topLevelWidgets():
            janela.close()
            janela.deleteLater()
    _limpar_qt()


@pytest.fixture(scope="session")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def fabrica():
    """Fábrica de sessões sobre uma base de dados em memória, já com os dados base."""
    engine = db.criar_engine("sqlite://")
    Base.metadata.create_all(engine)
    fabrica = db.criar_fabrica_sessoes(engine)
    with fabrica() as sessao:
        carregar_dados_base(sessao)
        sessao.commit()
    yield fabrica
    engine.dispose()


@pytest.fixture
def sessao(fabrica):
    with fabrica() as sessao:
        yield sessao
