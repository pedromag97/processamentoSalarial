import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lsc_presencas import db  # noqa: E402
from lsc_presencas.dados_base import carregar_dados_base  # noqa: E402
from lsc_presencas.modelos import Base  # noqa: E402


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
