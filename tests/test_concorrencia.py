"""Várias pessoas ao mesmo tempo sobre o mesmo servidor (testes em PostgreSQL)."""

import threading
import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from lsc_presencas import concorrencia, db, fecho, lancamentos, presencas
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import (
    Empresa,
    LancamentoManual,
    Marcacao,
    ParametrosEmpresa,
    Trabalhador,
)
from lsc_presencas.presencas import Alteracao
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_presencas import EcraPresencas
from lsc_presencas.ui.grelha import TRABALHADOR, Filtros, ModeloGrelha

ANO, MES = MES_DEMO
JAN = (date(ANO, MES, 1), date(ANO, MES, 31))
DIA = date(ANO, MES, 14)
ZERO = Decimal(0)


@pytest.fixture
def servidor(fabrica_pg):
    with fabrica_pg() as sessao:
        semear(sessao)
        for p in sessao.scalars(select(ParametrosEmpresa)):
            p.subsidio_alimentacao_dia = Decimal("6")
            p.ajuda_custo_franca_dia = Decimal("50")
            p.prevencao_dia = Decimal("30")
        sessao.commit()
    return fabrica_pg


@pytest.fixture
def duas(servidor):
    """Duas pessoas ligadas ao mesmo servidor, cada uma com a sua sessão."""
    with servidor(expire_on_commit=True) as ana, servidor(expire_on_commit=True) as rui:
        yield ana, rui


def um_trabalhador(sessao, empresa_id=None):
    consulta = select(Trabalhador).where(Trabalhador.ativo).order_by(Trabalhador.numero)
    if empresa_id is not None:
        consulta = consulta.where(Trabalhador.empresa_id == empresa_id)
    return sessao.scalars(consulta).first()


def estado(sessao, trabalhador_id, dia):
    sessao.expire_all()
    m = sessao.scalars(
        select(Marcacao).where(Marcacao.trabalhador_id == trabalhador_id, Marcacao.data == dia)
    ).one_or_none()
    return (m.codigo_id, m.horas_extra) if m else None


def grelha(sessao) -> ModeloGrelha:
    modelo = ModeloGrelha(sessao)
    modelo.configurar(*JAN, Filtros())
    return modelo


def indice(modelo, trabalhador_id, dia):
    linha = next(
        n
        for n, x in enumerate(modelo.linhas)
        if x.tipo == TRABALHADOR and x.trab.id == trabalhador_id
    )
    return modelo.index(linha, modelo.coluna_do_dia(dia))


# --- Conflitos na mesma célula ----------------------------------------------------------------


def test_quem_grava_por_cima_de_outra_pessoa_e_avisado(duas):
    ana, rui = duas
    codigos = presencas.codigos_ativos(ana)
    t = um_trabalhador(ana)
    visto = estado(ana, t.id, DIA)  # o que os dois estão a ver

    presencas.aplicar_alteracoes(
        ana, [Alteracao(t.id, DIA, (codigos["FE"], ZERO))], esperados={(t.id, DIA): visto}
    )
    with pytest.raises(presencas.Conflito):  # o Rui ainda tinha o valor antigo no ecrã
        presencas.aplicar_alteracoes(
            rui, [Alteracao(t.id, DIA, (codigos["B"], ZERO))], esperados={(t.id, DIA): visto}
        )
    assert estado(rui, t.id, DIA) == (codigos["FE"], ZERO)  # ficou o da Ana; nada se perdeu

    # Depois de ver o valor novo, já pode alterar.
    presencas.aplicar_alteracoes(
        rui,
        [Alteracao(t.id, DIA, (codigos["B"], ZERO))],
        esperados={(t.id, DIA): (codigos["FE"], ZERO)},
    )
    assert estado(ana, t.id, DIA) == (codigos["B"], ZERO)


def test_conflito_nao_grava_nenhuma_das_celulas_do_pedido(duas):
    ana, rui = duas
    codigos = presencas.codigos_ativos(ana)
    t = um_trabalhador(ana)
    outro_dia = date(ANO, MES, 15)
    vistos = {(t.id, DIA): estado(rui, t.id, DIA), (t.id, outro_dia): estado(rui, t.id, outro_dia)}
    presencas.aplicar_alteracoes(ana, [Alteracao(t.id, DIA, (codigos["FE"], ZERO))])

    with pytest.raises(presencas.Conflito) as conflito:
        presencas.aplicar_alteracoes(
            rui,
            [Alteracao(t.id, d, (codigos["B"], ZERO)) for d in (DIA, outro_dia)],
            esperados=vistos,
        )
    assert conflito.value.celulas == 1
    assert estado(rui, t.id, outro_dia) == vistos[(t.id, outro_dia)]  # tudo ou nada


def test_duas_pessoas_a_criar_a_mesma_celula_ao_mesmo_tempo(duas):
    ana, rui = duas
    codigos = presencas.codigos_ativos(ana)
    t = um_trabalhador(ana)
    vazio = date(ANO, MES + 1, 3)  # fevereiro não tem marcações
    resultados = {}

    def marcar(nome, sessao, codigo):
        try:
            presencas.aplicar_alteracoes(sessao, [Alteracao(t.id, vazio, (codigos[codigo], ZERO))])
            resultados[nome] = "gravou"
        except presencas.Conflito:
            resultados[nome] = "conflito"

    # A Ana fica com a transação aberta (bloqueio partilhado) para as duas coincidirem.
    concorrencia.alterar_marcacoes(ana)
    ana.add(Marcacao(trabalhador_id=t.id, data=vazio, codigo_id=codigos["P"]))
    ana.flush()
    fio = threading.Thread(target=marcar, args=("rui", rui, "PF"))
    fio.start()
    time.sleep(0.5)
    assert fio.is_alive()  # o Rui está à espera da linha da Ana
    ana.commit()
    fio.join(timeout=10)
    assert resultados == {"rui": "conflito"}
    assert estado(rui, t.id, vazio) == (codigos["P"], ZERO)


def test_a_grelha_avisa_e_mostra_o_valor_da_outra_pessoa(app, duas):
    ana, rui = duas
    codigos = presencas.codigos_ativos(ana)
    t = um_trabalhador(ana)
    da_ana, do_rui = grelha(ana), grelha(rui)
    erros = []
    do_rui.erro.connect(erros.append)

    assert da_ana.aplicar_texto([indice(da_ana, t.id, DIA)], "FE")
    assert not do_rui.aplicar_texto([indice(do_rui, t.id, DIA)], "B")
    assert "outra pessoa" in erros[-1]
    assert do_rui.data(indice(do_rui, t.id, DIA)) == "FE"  # a grelha do Rui foi atualizada
    assert not do_rui.pode_desfazer()
    assert do_rui.aplicar_texto([indice(do_rui, t.id, DIA)], "B")  # à segunda, já a ver o FE
    assert estado(ana, t.id, DIA) == (codigos["B"], ZERO)


def test_a_grelha_vai_buscar_o_que_os_outros_gravaram(app, duas):
    ana, rui = duas
    t = um_trabalhador(ana)
    da_ana = grelha(ana)
    ecra_do_rui = EcraPresencas(rui)
    ecra_do_rui.ir_para(DIA)
    assert ecra_do_rui.temporizador.isActive()  # com servidor, atualiza-se sozinha
    modelo = ecra_do_rui.modelo
    assert not ecra_do_rui.atualizar(manual=True)
    assert "sem alterações" in ecra_do_rui.estado.text()

    # Com uma célula selecionada, a atualização não mexe na seleção.
    celula = indice(modelo, t.id, DIA)
    coluna_horas = modelo.columnCount() - 1
    horas_antes = modelo.data(modelo.index(celula.row(), coluna_horas))
    ecra_do_rui.dias.setCurrentIndex(celula)
    assert da_ana.aplicar_texto([indice(da_ana, t.id, DIA)], "FE+3")
    assert modelo.data(celula) != "FE"
    assert ecra_do_rui.atualizar(manual=True)
    assert modelo.data(celula) == "FE"
    assert "outra pessoa" in ecra_do_rui.estado.text()
    assert ecra_do_rui.dias.currentIndex() == celula
    # Os totais da linha foram recalculados.
    assert modelo.data(modelo.index(celula.row(), coluna_horas)) != horas_antes


# --- Fecho com outras pessoas ligadas ---------------------------------------------------------


def test_marcacao_gravada_durante_o_fecho_espera_e_e_recusada(duas):
    admin, rui = duas
    empresa = admin.scalars(select(Empresa).order_by(Empresa.nome)).first()
    t = um_trabalhador(admin, empresa.id)
    codigos = presencas.codigos_ativos(admin)
    resultados = {}

    def marcar():
        try:
            presencas.aplicar_alteracoes(rui, [Alteracao(t.id, DIA, (codigos["B"], ZERO))])
            resultados["rui"] = "gravou"
        except presencas.MesFechado:
            resultados["rui"] = "fechado"

    # O administrador está a meio do fecho (com o bloqueio exclusivo).
    concorrencia.fechar_ou_reabrir(admin)
    fio = threading.Thread(target=marcar)
    fio.start()
    time.sleep(0.5)
    assert fio.is_alive() and not resultados  # o Rui espera
    admin.rollback()
    fecho.fechar(admin, empresa.id, ANO, MES, confirmado=True, com_backup=False)
    fio.join(timeout=10)
    # Ou gravou antes do fecho (e está na fotografia) ou foi recusado: nunca fica de fora.
    guardado = fecho.mapa_do_mes(admin, empresa.id, ANO, MES)
    linha = next(x for x in guardado.trabalhadores if x.numero == t.numero)
    na_fotografia = {d.data: d.codigo for d in linha.dias}.get(DIA)
    gravou = resultados["rui"] == "gravou"
    assert (na_fotografia == "B") == gravou
    assert (estado(rui, t.id, DIA) == (codigos["B"], ZERO)) == gravou


def test_o_fecho_inclui_o_que_outra_pessoa_gravou_no_ultimo_instante(duas):
    admin, rui = duas
    empresa = admin.scalars(select(Empresa).order_by(Empresa.nome)).first()
    t = um_trabalhador(admin, empresa.id)
    codigos = presencas.codigos_ativos(admin)
    fecho.mapa_do_mes(admin, empresa.id, ANO, MES)  # o administrador já tem o mês em memória

    presencas.aplicar_alteracoes(rui, [Alteracao(t.id, DIA, (codigos["B"], ZERO))])
    fechado = fecho.fechar(admin, empresa.id, ANO, MES, confirmado=True, com_backup=False)
    linha = next(x for x in fechado.trabalhadores if x.numero == t.numero)
    assert {d.data: d.codigo for d in linha.dias}[DIA] == "B"

    # Depois de fechado, o Rui (que ainda via o mês aberto) já não consegue gravar.
    with pytest.raises(presencas.MesFechado):
        presencas.aplicar_alteracoes(rui, [Alteracao(t.id, DIA, (codigos["FE"], ZERO))])
    lanc = LancamentoManual(
        trabalhador_id=t.id, ano=ANO, mes=MES, tipo="premio", descricao="x", valor=Decimal(10)
    )
    rui.add(lanc)
    rui.flush()
    with pytest.raises(ValueError, match="fechado"):
        lancamentos.registar(rui, lanc, "criar")
    rui.rollback()

    # Dois administradores a fechar: o segundo é recusado.
    with pytest.raises(fecho.FechoRecusado, match="já está fechado"):
        fecho.fechar(rui, empresa.id, ANO, MES, confirmado=True, com_backup=False)
    fecho.reabrir(admin, empresa.id, ANO, MES, "teste", com_backup=False)
    with pytest.raises(fecho.FechoRecusado, match="não está fechado"):
        fecho.reabrir(rui, empresa.id, ANO, MES, "teste", com_backup=False)


def test_a_grelha_descobre_que_o_mes_foi_fechado(app, duas):
    admin, rui = duas
    empresa = admin.scalars(select(Empresa).order_by(Empresa.nome)).first()
    t = um_trabalhador(admin, empresa.id)
    do_rui = grelha(rui)
    erros = []
    do_rui.erro.connect(erros.append)
    celula = indice(do_rui, t.id, DIA)
    assert do_rui.flags(celula) & do_rui.flags(celula).ItemIsEditable

    fecho.fechar(admin, empresa.id, ANO, MES, confirmado=True, com_backup=False)
    assert not do_rui.aplicar_texto([celula], "B")
    assert "fechado" in erros[-1]
    assert not (do_rui.flags(celula) & do_rui.flags(celula).ItemIsEditable)  # ficou só de leitura


# --- Ligação e migrações ----------------------------------------------------------------------


def transacoes_abertas(sessao_de_fora) -> int:
    return sessao_de_fora.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND state = 'idle in transaction' AND pid <> pg_backend_pid()"
        )
    )


def test_a_interface_nao_fica_com_uma_transacao_aberta(app, servidor):
    janela = JanelaPrincipal(servidor)
    assert janela.temporizador.isActive()
    for nome in janela.ecras:
        janela.mostrar(nome)
    janela.sessao.scalars(select(Trabalhador)).first()  # uma leitura qualquer
    with servidor() as de_fora:
        assert transacoes_abertas(de_fora) == 1  # a sessão da janela, depois de ler
        de_fora.rollback()
        janela._libertar_ligacao()  # o que o temporizador faz de 2 em 2 segundos
        assert transacoes_abertas(de_fora) == 0
    # O que estava carregado continua lá, sem novas consultas por objeto.
    modelo = janela.ecras["Trabalhadores"].modelo
    assert modelo.linhas[0].nome
    janela.close()


def test_libertar_nao_mexe_em_alteracoes_por_gravar(duas):
    ana, _ = duas
    t = um_trabalhador(ana)
    t.nome = "Por gravar"
    concorrencia.libertar_leitura(ana)
    assert ana.dirty and t.nome == "Por gravar"
    ana.rollback()


def test_mudar_de_ecra_mostra_o_que_mudou_noutro_pc(app, servidor):
    janela = JanelaPrincipal(servidor)
    modelo = janela.mostrar("Trabalhadores").modelo
    numero = modelo.linhas[0].numero
    with servidor() as outra_pessoa:
        t = outra_pessoa.scalars(select(Trabalhador).where(Trabalhador.numero == numero)).one()
        t.nome = "Mudado Noutro PC"
        outra_pessoa.commit()
    janela.mostrar("Tabelas")
    janela.mostrar("Trabalhadores")
    assert modelo.linhas[0].nome == "Mudado Noutro PC"
    janela.close()


def test_varios_pcs_a_abrir_ao_mesmo_tempo_correm_as_migracoes_um_de_cada_vez(url_pg):
    erros = []

    def abrir():
        try:
            db.migrar(url_pg)
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)

    fios = [threading.Thread(target=abrir) for _ in range(4)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=60)
    assert erros == []
    engine = db.criar_engine(url_pg)
    with engine.connect() as ligacao:
        assert ligacao.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
        assert ligacao.scalar(select(func.count()).select_from(Trabalhador)) == 0
    engine.dispose()
