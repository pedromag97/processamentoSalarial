from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select

from lsc_presencas import db
from lsc_presencas.demo import ja_tem_dados, semear
from lsc_presencas.modelos import Base, Marcacao, ParametrosEmpresa, Trabalhador


def _bd_migrada(tmp_path):
    url = f"sqlite:///{(tmp_path / 'teste.db').as_posix()}"
    db.migrar(url)
    return db.criar_engine(url)


def test_migracoes_criam_todas_as_tabelas_do_modelo(tmp_path):
    engine = _bd_migrada(tmp_path)
    tabelas = set(inspect(engine).get_table_names())
    assert tabelas == set(Base.metadata.tables) | {"alembic_version"}
    engine.dispose()


def test_migracoes_estao_em_dia_com_o_modelo(tmp_path):
    engine = _bd_migrada(tmp_path)
    with engine.connect() as ligacao:
        diferencas = compare_metadata(MigrationContext.configure(ligacao), Base.metadata)
    engine.dispose()
    assert diferencas == [], "o modelo mudou: falta criar uma migração"


def test_seed_de_demonstracao(tmp_path):
    engine = _bd_migrada(tmp_path)
    fabrica = db.criar_fabrica_sessoes(engine)
    with fabrica() as sessao:
        assert not ja_tem_dados(sessao)
        assert semear(sessao) == 24
        sessao.commit()
    with fabrica() as sessao:
        assert ja_tem_dados(sessao)
        assert sessao.scalar(select(func.count()).select_from(Marcacao)) > 300
        # Nenhuma marcação fora do período de contrato.
        for t in sessao.scalars(select(Trabalhador)):
            for m in t.marcacoes:
                assert t.data_admissao is None or m.data >= t.data_admissao
                assert t.data_saida is None or m.data <= t.data_saida
        # O seed não inventa valores legais.
        for p in sessao.scalars(select(ParametrosEmpresa)):
            assert p.subsidio_alimentacao_dia is None
            assert p.limite_isencao_subsidio_dia is None
    engine.dispose()


def test_a_janela_principal_abre(fabrica):
    from PySide6.QtWidgets import QApplication

    from lsc_presencas.ui.app import JanelaPrincipal, resumo_bd

    app = QApplication.instance() or QApplication([])
    janela = JanelaPrincipal(fabrica)
    janela.show()
    app.processEvents()
    assert "LSC Presenças" in janela.windowTitle()
    with fabrica() as sessao:
        assert resumo_bd(sessao)["Códigos de presença"] == 10
    janela.close()


def test_o_programa_tem_o_simbolo_nas_janelas(app):
    from lsc_presencas import config
    from lsc_presencas.ui.app import aplicacao

    assert config.caminho_icone().is_file()
    assert config.caminho_icone().with_suffix(".ico").is_file()  # o do executável e dos atalhos
    assert not aplicacao().windowIcon().isNull()
