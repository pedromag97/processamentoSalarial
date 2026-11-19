"""A app sobre um servidor PostgreSQL: migrações, cálculo, fecho, cópias e ligação."""

from datetime import date
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, make_url, select
from sqlalchemy.exc import IntegrityError

from lsc_presencas import __main__ as principal
from lsc_presencas import (
    backups,
    config,
    contas,
    db,
    exportacao,
    fecho,
    mapa,
    presencas,
    servidor,
    transferencia,
)
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import (
    PERFIL_ADMIN,
    Auditoria,
    Base,
    Cliente,
    Empresa,
    Marcacao,
    ParametrosEmpresa,
    Trabalhador,
)
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_ligacao import DialogoLigacao
from lsc_presencas.ui.tabela import mensagem_de_erro

ANO, MES = MES_DEMO


def preencher_valores(sessao):
    for p in sessao.scalars(select(ParametrosEmpresa)):
        p.subsidio_alimentacao_dia = Decimal("6")
        p.ajuda_custo_franca_dia = Decimal("50")
        p.prevencao_dia = Decimal("30")
        p.taxa_seguranca_social = Decimal("0.11")
    sessao.commit()


@pytest.fixture
def pg(fabrica_pg):
    with fabrica_pg(expire_on_commit=True) as sessao:
        semear(sessao)
        preencher_valores(sessao)
        yield sessao


@pytest.fixture
def local(pasta_da_app):
    """O ficheiro SQLite deste PC (o de sempre), com os dados de demonstração."""
    db.migrar(config.url_local())
    engine = db.criar_engine(config.url_local())
    with db.criar_fabrica_sessoes(engine)() as sessao:
        semear(sessao)
        preencher_valores(sessao)
        contas.criar(sessao, "pedro", "Pedro Teste", "segredo-123", PERFIL_ADMIN)
    yield engine
    engine.dispose()


def partes(url_pg) -> tuple[config.Ligacao, str]:
    url = make_url(url_pg)
    return config.Ligacao(url.host, url.database, url.username, url.port), url.password or ""


# --- O mesmo comportamento no PostgreSQL ------------------------------------------------------


def test_migracoes_no_postgresql_estao_em_dia_com_o_modelo(fabrica_pg):
    engine = fabrica_pg.kw["bind"]
    assert engine.dialect.name == "postgresql"
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    with engine.connect() as ligacao:
        assert compare_metadata(MigrationContext.configure(ligacao), Base.metadata) == []


def test_calculo_fecho_e_exportacao_no_postgresql(pg, tmp_path):
    empresa = pg.scalars(select(Empresa).order_by(Empresa.nome)).first()
    antes = mapa.construir(pg, empresa.id, ANO, MES)
    assert antes.total > 0 and all(isinstance(t.total, Decimal) for t in antes.trabalhadores)

    fechado = fecho.fechar(pg, empresa.id, ANO, MES, confirmado=True, utilizador="teste")
    assert fecho.mapa_do_mes(pg, empresa.id, ANO, MES).trabalhadores == antes.trabalhadores
    assert exportacao.exportar(fechado, tmp_path).excel.is_file()

    # Mês fechado bloqueia as marcações; reabrir volta a deixar.
    t = pg.scalars(select(Trabalhador).where(Trabalhador.empresa_id == empresa.id)).first()
    alteracao = presencas.Alteracao(
        t.id, date(ANO, MES, 15), (presencas.codigos_ativos(pg)["FE"], Decimal("1.5"))
    )
    with pytest.raises(presencas.MesFechado):
        presencas.aplicar_alteracoes(pg, [alteracao])
    fecho.reabrir(pg, empresa.id, ANO, MES, "teste")
    presencas.aplicar_alteracoes(pg, [alteracao])
    gravada = pg.scalars(
        select(Marcacao).where(Marcacao.trabalhador_id == t.id, Marcacao.data == alteracao.data)
    ).one()
    assert gravada.horas_extra == Decimal("1.5")
    assert pg.scalar(select(func.count()).select_from(Auditoria)) >= 3


def test_copia_de_seguranca_de_um_servidor_e_um_ficheiro_que_se_volta_a_enviar(
    pg, url_pg, tmp_path
):
    engine = pg.get_bind()
    empresa = pg.scalars(select(Empresa)).first()
    total = mapa.construir(pg, empresa.id, ANO, MES).total
    linhas = transferencia.contar(engine)
    pg.commit()

    copia = backups.fazer_backup(engine, "teste", tmp_path / "copias")
    ficheiro = db.criar_engine(f"sqlite:///{copia.as_posix()}")
    assert transferencia.contar(ficheiro) == linhas
    db.migrar(f"sqlite:///{copia.as_posix()}")  # a cópia já está na última migração

    # Recuperar: enviar a cópia para um servidor; os totais ficam iguais.
    with pytest.raises(transferencia.DestinoComDados):
        transferencia.copiar(ficheiro, engine)
    assert transferencia.copiar(ficheiro, engine, substituir=True).total == sum(linhas.values())
    ficheiro.dispose()
    pg.expire_all()
    assert mapa.construir(pg, empresa.id, ANO, MES).total == total


def test_erros_do_postgresql_em_portugues(pg):
    existente = pg.scalars(select(Cliente.codigo)).first()
    pg.add(Cliente(codigo=existente))
    with pytest.raises(IntegrityError) as repetido:
        pg.flush()
    assert mensagem_de_erro(repetido.value) == "Já existe um registo com esse valor."
    pg.rollback()

    pg.delete(pg.scalars(select(Empresa)).first())
    with pytest.raises(IntegrityError) as em_uso:
        pg.flush()
    assert "a ser usado" in mensagem_de_erro(em_uso.value)
    pg.rollback()


# --- Passar do ficheiro local para o servidor -------------------------------------------------


def test_enviar_os_dados_locais_para_o_servidor(local, url_pg, pasta_da_app, cofre):
    ligacao, senha = partes(url_pg)
    situacao = servidor.verificar(ligacao, senha)  # também cria as tabelas no servidor
    assert situacao == servidor.Situacao(servidor_tem_dados=False, local_tem_dados=True)
    assert not config.usa_servidor()

    resultado = servidor.ligar(ligacao, senha, enviar_dados_locais=True)
    assert resultado.linhas == transferencia.contar(local)
    assert resultado.linhas["trabalhador"] == 24 and resultado.linhas["utilizador"] == 1

    # A partir daqui este PC usa o servidor; a palavra-passe não fica no ficheiro.
    assert config.usa_servidor() and config.ler_ligacao() == ligacao
    assert "password" not in (pasta_da_app / "ligacao.json").read_text().lower()
    assert senha not in (pasta_da_app / "ligacao.json").read_text() or senha == ""
    assert list(cofre) == [(config.NOME_COFRE, ligacao.chave)]
    assert ligacao.servidor in config.descricao_bd()

    fabrica = principal.preparar_bd(com_copia=True)
    assert backups.listar() == []  # com servidor não há cópia ao abrir
    with fabrica() as sessao:
        assert sessao.get_bind().dialect.name == "postgresql"
        # Os mesmos dados e as mesmas contas (o login continua a funcionar).
        assert contas.autenticar(sessao, "pedro", "segredo-123").perfil == PERFIL_ADMIN
        empresa = sessao.scalars(select(Empresa).order_by(Empresa.nome)).first()
        no_servidor = mapa.construir(sessao, empresa.id, ANO, MES).total
        # Os números automáticos continuam depois dos copiados.
        novo = Cliente(codigo="novo")
        sessao.add(novo)
        sessao.commit()
        assert novo.id > 7
    fabrica.kw["bind"].dispose()
    with db.criar_fabrica_sessoes(local)() as sessao:
        assert mapa.construir(sessao, empresa.id, ANO, MES).total == no_servidor

    # Um segundo PC com dados não os pode enviar por cima do servidor.
    with pytest.raises(transferencia.DestinoComDados):
        servidor.ligar(ligacao, senha, enviar_dados_locais=True)
    assert servidor.verificar(ligacao, senha).servidor_tem_dados

    config.remover_ligacao()
    assert not config.usa_servidor() and not cofre


def test_so_um_administrador_envia_os_dados(local, url_pg):
    ligacao, senha = partes(url_pg)
    with db.criar_fabrica_sessoes(local)() as sessao:
        contas.iniciar_sessao(contas.criar(sessao, "ana", "Ana Teste", "segredo-123"))
    with pytest.raises(contas.SemPermissao):
        servidor.ligar(ligacao, senha, enviar_dados_locais=True)
    assert not config.usa_servidor()


def test_ligacao_falhada_explica_se_em_portugues(url_pg, pasta_da_app):
    ligacao, senha = partes(url_pg)
    casos = [
        (
            config.Ligacao(ligacao.servidor, "nao_existe", ligacao.utilizador, ligacao.porta),
            "não existe",
        ),
        (
            config.Ligacao(ligacao.servidor, ligacao.base, ligacao.utilizador, 1),
            "chegar ao servidor",
        ),
    ]
    for errada, esperado in casos:
        with pytest.raises(servidor.ErroDeLigacao, match=esperado):
            servidor.verificar(errada, senha)
    assert not config.usa_servidor()  # nada ficou guardado


def test_dialogo_de_ligacao(app, local, url_pg):
    ligacao, senha = partes(url_pg)
    dialogo = DialogoLigacao()
    assert not dialogo.botao_guardar.isEnabled() and not dialogo.botao_local.isEnabled()
    assert not dialogo.testar() and "Falta preencher" in dialogo.mensagem.text()

    dialogo.campo_servidor.setText(ligacao.servidor)
    dialogo.campo_porta.setValue(ligacao.porta)
    dialogo.campo_base.setText(ligacao.base)
    dialogo.campo_utilizador.setText(ligacao.utilizador)
    dialogo.campo_senha.setText(senha)
    assert dialogo.testar()
    assert "servidor está vazio" in dialogo.mensagem.text()
    assert dialogo.visto_enviar.isChecked() and dialogo.botao_guardar.isEnabled()
    assert dialogo.guardar() and dialogo.mudou
    assert dialogo.resultado.linhas["trabalhador"] == 24
    assert config.usa_servidor()

    outro = DialogoLigacao()  # já vem preenchido e deixa voltar ao ficheiro local
    assert outro.campo_servidor.text() == ligacao.servidor and outro.botao_local.isEnabled()
    assert outro.testar() and "já tem dados" in outro.mensagem.text()
    outro.usar_local()
    assert outro.mudou and not config.usa_servidor()


def test_a_janela_abre_sobre_o_servidor(app, fabrica_pg):
    with fabrica_pg() as sessao:
        semear(sessao)
        sessao.commit()
    janela = JanelaPrincipal(fabrica_pg)
    janela.show()
    app.processEvents()
    for nome in janela.ecras:
        janela.mostrar(nome)
    assert janela.ecras["Presenças"].modelo.rowCount() > 20
    janela.close()
