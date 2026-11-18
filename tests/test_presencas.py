"""Marcações: interpretação das células, gravação com auditoria, grelha e dashboard."""

import json
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
from sqlalchemy import func, select

from lsc_presencas import presencas
from lsc_presencas.demo import semear
from lsc_presencas.modelos import (
    FECHO_FECHADO,
    Auditoria,
    CodigoPresenca,
    Empresa,
    FechoMes,
    Marcacao,
    Trabalhador,
)
from lsc_presencas.presencas import Alteracao, MesFechado
from lsc_presencas.ui.ecra_presencas import SEMANAL, EcraPresencas
from lsc_presencas.ui.grelha import (
    COR_FERIADO,
    COR_FIM_DE_SEMANA,
    EMPRESA,
    N_DIR,
    N_ESQ,
    PAPEL_HORAS,
    TRABALHADOR,
    Filtros,
    ModeloGrelha,
    ModeloTotaisDia,
)

EDITAR = Qt.ItemDataRole.EditRole
MOSTRAR = Qt.ItemDataRole.DisplayRole
FUNDO = Qt.ItemDataRole.BackgroundRole

JAN = (date(2027, 1, 1), date(2027, 1, 31))
FEV = (date(2027, 2, 1), date(2027, 2, 28))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(app, fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        sessao.commit()
        yield sessao


@pytest.fixture
def codigos(ui):
    return presencas.codigos_ativos(ui)


def trabalhador(sessao, numero):
    return sessao.scalars(select(Trabalhador).where(Trabalhador.numero == numero)).one()


def marcacao(sessao, numero, dia):
    return sessao.scalars(
        select(Marcacao).join(Trabalhador).where(Trabalhador.numero == numero, Marcacao.data == dia)
    ).one_or_none()


def auditorias(sessao):
    return sessao.scalars(select(Auditoria).order_by(Auditoria.id)).all()


def grelha(sessao, periodo=JAN, **filtros) -> ModeloGrelha:
    modelo = ModeloGrelha(sessao)
    modelo.configurar(*periodo, Filtros(**filtros))
    return modelo


def indice(modelo, numero, dia):
    linha = next(
        n
        for n, linha in enumerate(modelo.linhas)
        if linha.tipo == TRABALHADOR and linha.trab.numero == numero
    )
    return modelo.index(linha, modelo.coluna_do_dia(dia))


def erros_de(modelo):
    erros = []
    modelo.erro.connect(erros.append)
    return erros


# --- Texto das células ------------------------------------------------------------------------


def test_interpretar_celula(codigos):
    assert presencas.interpretar_celula("p", codigos) == (codigos["P"], Decimal("0"))
    assert presencas.interpretar_celula("PF+1,5", codigos) == (codigos["PF"], Decimal("1.5"))
    assert presencas.interpretar_celula(" pf + 2 ", codigos) == (codigos["PF"], Decimal("2"))
    assert presencas.interpretar_celula("", codigos) is None
    assert presencas.interpretar_celula("   ", codigos) is None


@pytest.mark.parametrize("texto", ["XX", "P+", "P+abc", "P+30", "P+-1", "x"])
def test_interpretar_celula_invalida(codigos, texto):
    with pytest.raises(ValueError):
        presencas.interpretar_celula(texto, codigos)


def test_codigo_inativo_nao_pode_ser_marcado(ui):
    ui.scalars(select(CodigoPresenca).where(CodigoPresenca.codigo == "AT")).one().ativo = False
    ui.commit()
    with pytest.raises(ValueError):
        presencas.interpretar_celula("AT", presencas.codigos_ativos(ui))


def test_texto_celula():
    assert presencas.texto_celula("PF", Decimal("0")) == "PF"
    assert presencas.texto_celula("PF", Decimal("2.0")) == "PF+2"
    assert presencas.texto_celula("P", Decimal("1.50")) == "P+1,5"


# --- Gravação e auditoria ---------------------------------------------------------------------


def test_criar_alterar_e_apagar_marcacao_com_auditoria(ui, codigos):
    t = trabalhador(ui, 2)
    dia = date(2027, 2, 1)

    antes = presencas.aplicar_alteracoes(ui, [Alteracao(t.id, dia, (codigos["P"], Decimal("0")))])
    assert antes == [Alteracao(t.id, dia, None)]
    m = marcacao(ui, 2, dia)
    # Cliente, viatura e zona são copiados da ficha no momento da marcação.
    assert (m.cliente_id, m.viatura_id, m.zona_id) == (t.cliente_id, t.viatura_id, t.zona_id)

    antes = presencas.aplicar_alteracoes(
        ui, [Alteracao(t.id, dia, (codigos["PF"], Decimal("2")))], utilizador="maria"
    )
    assert antes == [Alteracao(t.id, dia, (codigos["P"], Decimal("0")))]

    # Repetir o mesmo valor não muda nada nem fica na auditoria.
    assert (
        presencas.aplicar_alteracoes(ui, [Alteracao(t.id, dia, (codigos["PF"], Decimal("2")))])
        == []
    )

    presencas.aplicar_alteracoes(ui, [Alteracao(t.id, dia, None)])
    assert marcacao(ui, 2, dia) is None

    registos = auditorias(ui)
    assert [r.acao for r in registos] == ["criar", "alterar", "apagar"]
    assert registos[1].utilizador == "maria"
    assert registos[0].valor_antigo is None
    assert json.loads(registos[1].valor_antigo)["codigo"] == "P"
    assert json.loads(registos[1].valor_novo) == {
        "trabalhador": 2,
        "data": "2027-02-01",
        "codigo": "PF",
        "horas_extra": "2",
    }
    assert registos[2].valor_novo is None
    assert all(r.entidade == "marcacao" and r.quando for r in registos)


def test_mes_fechado_nao_pode_ser_alterado(ui, codigos):
    a, b = trabalhador(ui, 2), trabalhador(ui, 3)  # empresas diferentes
    assert a.empresa_id != b.empresa_id
    ui.add(FechoMes(empresa_id=a.empresa_id, ano=2027, mes=2, estado=FECHO_FECHADO))
    ui.commit()
    estado = (codigos["P"], Decimal("0"))
    dia = date(2027, 2, 1)

    with pytest.raises(MesFechado):
        presencas.aplicar_alteracoes(
            ui, [Alteracao(b.id, dia, estado), Alteracao(a.id, dia, estado)]
        )
    assert marcacao(ui, 2, dia) is None and marcacao(ui, 3, dia) is None  # tudo ou nada
    assert auditorias(ui) == []

    # A outra empresa e os outros meses continuam abertos.
    presencas.aplicar_alteracoes(ui, [Alteracao(b.id, dia, estado)])
    presencas.aplicar_alteracoes(ui, [Alteracao(a.id, date(2027, 3, 1), estado)])
    assert marcacao(ui, 3, dia) is not None


def test_copiar_semana_anterior(ui):
    t = trabalhador(ui, 4)
    alteracoes = presencas.alteracoes_copiar_semana(ui, [t.id], date(2027, 2, 3))
    origem = {
        m.data: (m.codigo_id, m.horas_extra)
        for m in t.marcacoes
        if date(2027, 1, 25) <= m.data <= date(2027, 1, 31)
    }
    assert origem
    assert {a.data: a.estado for a in alteracoes} == {
        dia + timedelta(days=7): estado for dia, estado in origem.items()
    }
    assert presencas.semana_de(date(2027, 2, 3)) == (date(2027, 2, 1), date(2027, 2, 7))


# --- Grelha -----------------------------------------------------------------------------------


def test_estrutura_da_grelha(ui):
    modelo = grelha(ui)
    assert modelo.columnCount() == N_ESQ + 31 + N_DIR
    tipos = [linha.tipo for linha in modelo.linhas]
    assert tipos[0] == EMPRESA and tipos[1] == "cliente" and tipos[2] == TRABALHADOR
    assert tipos.count(EMPRESA) == 2
    assert tipos.count(TRABALHADOR) == 23  # o inativo não aparece
    assert "(12)" in modelo.linhas[0].texto or "(11)" in modelo.linhas[0].texto
    cabecalho = modelo.headerData(modelo.coluna_do_dia(date(2027, 1, 4)), Qt.Orientation.Horizontal)
    assert cabecalho == "2ª\n4"
    # Dentro de cada cliente, por nº.
    grupos, atual = [], []
    for linha in modelo.linhas:
        if linha.tipo == TRABALHADOR:
            atual.append(linha.trab.numero)
        else:
            grupos.append(atual)
            atual = []
    grupos.append(atual)
    assert all(g == sorted(g) for g in grupos)
    assert max(len(g) for g in grupos) >= 2


def test_recolher_e_expandir_grupos(ui):
    modelo = grelha(ui)
    total = modelo.rowCount()
    modelo.alternar_grupo(0)  # recolhe a primeira empresa
    assert modelo.rowCount() < total
    assert modelo.linhas[0].texto.startswith("▸")
    assert modelo.linhas[1].tipo == EMPRESA
    modelo.alternar_grupo(0)
    assert modelo.rowCount() == total

    modelo.alternar_grupo(1)  # recolhe um cliente
    assert modelo.linhas[2].tipo == "cliente"
    modelo.alternar_grupo(2)  # numa linha de trabalhador ou cliente seguinte não rebenta
    assert len(modelo.trabalhadores) == 23  # os totais continuam a contar todos


def test_filtros_da_grelha(ui):
    empresa = ui.scalars(select(Empresa).order_by(Empresa.nome)).first()
    modelo = grelha(ui, empresa_id=empresa.id)
    assert [linha.tipo for linha in modelo.linhas].count(EMPRESA) == 1
    assert all(t.empresa_id == empresa.id for t in modelo.trabalhadores)

    assert len(grelha(ui, texto="DALIA").trabalhadores) == 3
    assert len(grelha(ui, mostrar_inativos=True).trabalhadores) == 24
    t = trabalhador(ui, 5)
    so_viatura = grelha(ui, viatura_id=t.viatura_id).trabalhadores
    assert so_viatura and all(x.viatura == t.viatura.codigo for x in so_viatura)
    so_zona = grelha(ui, zona_id=t.zona_id, cliente_id=t.cliente_id).trabalhadores
    assert 5 in [x.numero for x in so_zona]


def test_escrever_numa_celula(ui):
    modelo = grelha(ui, FEV)
    celula = indice(modelo, 2, date(2027, 2, 1))
    assert modelo.data(celula, MOSTRAR) == ""
    assert modelo.setData(celula, "pf+2", EDITAR)
    assert modelo.data(celula, MOSTRAR) == "PF"
    assert modelo.data(celula, PAPEL_HORAS) == "2"
    assert modelo.data(celula, EDITAR) == "PF+2"
    m = marcacao(ui, 2, date(2027, 2, 1))
    assert m.codigo.codigo == "PF" and m.horas_extra == Decimal("2")

    # Totais à direita: PF é a 2.ª coluna de totais, horas extra a última.
    fim = N_ESQ + 28
    assert modelo.data(modelo.index(celula.row(), fim + 1), MOSTRAR) == "1"
    assert modelo.data(modelo.index(celula.row(), fim + 6), MOSTRAR) == "2"

    assert modelo.setData(celula, "", EDITAR)  # limpar
    assert marcacao(ui, 2, date(2027, 2, 1)) is None


def test_codigo_desconhecido_e_recusado(ui):
    modelo = grelha(ui)
    erros = erros_de(modelo)
    celula = indice(modelo, 2, date(2027, 1, 4))
    antes = modelo.data(celula, EDITAR)
    assert not modelo.setData(celula, "ZZ", EDITAR)
    assert "não é um código de presença" in erros[0]
    assert modelo.data(celula, EDITAR) == antes
    # As colunas fixas e as linhas de grupo não são editáveis.
    assert not modelo.setData(modelo.index(celula.row(), 1), "X", EDITAR)
    assert not modelo.flags(modelo.index(0, celula.column())) & Qt.ItemFlag.ItemIsEditable


def test_aplicar_um_codigo_a_varias_celulas_e_desfazer(ui):
    modelo = grelha(ui, FEV)
    semana = [date(2027, 2, n) for n in range(1, 6)]
    celulas = [indice(modelo, n, dia) for n in (2, 3) for dia in semana]
    assert modelo.aplicar_texto(celulas, "PF")
    assert all(modelo.data(c, MOSTRAR) == "PF" for c in celulas)
    assert (
        ui.scalar(select(func.count()).select_from(Marcacao).where(Marcacao.data >= FEV[0])) == 10
    )

    assert modelo.pode_desfazer()
    assert modelo.desfazer()
    assert all(modelo.data(c, MOSTRAR) == "" for c in celulas)
    assert ui.scalar(select(func.count()).select_from(Marcacao).where(Marcacao.data >= FEV[0])) == 0
    assert not modelo.pode_desfazer()
    assert not modelo.desfazer()


def test_desfazer_repoe_o_valor_anterior(ui):
    modelo = grelha(ui)
    celula = indice(modelo, 2, date(2027, 1, 4))
    antes = modelo.data(celula, EDITAR)
    assert antes
    modelo.setData(celula, "FE", EDITAR)
    modelo.setData(celula, "B", EDITAR)
    modelo.desfazer()
    assert modelo.data(celula, EDITAR) == "FE"
    modelo.desfazer()
    assert modelo.data(celula, EDITAR) == antes


def test_copiar_e_colar_um_intervalo(ui):
    modelo = grelha(ui)
    origem = [indice(modelo, 2, date(2027, 1, n)) for n in range(4, 9)]
    texto = modelo.texto_para_copiar(origem)
    assert texto.count("\t") == 4 and "\n" not in texto

    fev = grelha(ui, FEV)
    destino = indice(fev, 2, date(2027, 2, 1))
    matriz = [texto.split("\t"), ["PF+1,5", "", "fe"]]
    assert fev.colar(destino, matriz)
    assert fev.data(destino, EDITAR) == texto.split("\t")[0]
    # A segunda linha da matriz vai para o trabalhador seguinte na grelha.
    seguinte = fev.linhas_de_trabalhadores(destino.row() + 1)[0]
    lidos = [fev.data(fev.index(seguinte, destino.column() + n), EDITAR) for n in range(3)]
    assert lidos == ["PF+1,5", "", "FE"]
    fev.desfazer()  # um só Ctrl+Z desfaz a colagem inteira
    assert fev.data(destino, EDITAR) == ""


def test_colar_com_um_valor_invalido_nao_cola_nada(ui):
    modelo = grelha(ui, FEV)
    erros = erros_de(modelo)
    destino = indice(modelo, 2, date(2027, 2, 1))
    assert not modelo.colar(destino, [["P", "P", "QQ"]])
    assert "Não colei nada" in erros[0]
    assert modelo.data(destino, EDITAR) == ""


def test_colar_no_fim_do_mes_ignora_o_que_sai_da_grelha(ui):
    modelo = grelha(ui, FEV)
    destino = indice(modelo, 2, date(2027, 2, 27))
    assert modelo.colar(destino, [["P", "P", "P", "P"]])
    assert marcacao(ui, 2, date(2027, 2, 28)) is not None
    assert marcacao(ui, 2, date(2027, 3, 1)) is None


def test_mes_fechado_fica_so_de_leitura_na_grelha(ui):
    t = trabalhador(ui, 2)
    ui.add(FechoMes(empresa_id=t.empresa_id, ano=2027, mes=1, estado=FECHO_FECHADO))
    ui.commit()
    modelo = grelha(ui)
    erros = erros_de(modelo)
    fechada = indice(modelo, 2, date(2027, 1, 4))
    aberta = indice(modelo, 3, date(2027, 1, 4))
    assert not modelo.flags(fechada) & Qt.ItemFlag.ItemIsEditable
    assert modelo.flags(aberta) & Qt.ItemFlag.ItemIsEditable
    assert "Mês fechado" in modelo.data(fechada, Qt.ItemDataRole.ToolTipRole)
    antes = modelo.data(fechada, EDITAR)
    assert not modelo.aplicar_texto([fechada, aberta], "FE")
    assert "está fechado" in erros[0]
    assert modelo.data(fechada, EDITAR) == antes


def test_cores_de_fim_de_semana_feriado_e_codigo(ui):
    modelo = grelha(ui)
    # O nº 2 está em Portugal: sem marcação ao sábado.
    assert modelo.data(indice(modelo, 2, date(2027, 1, 9)), FUNDO) == COR_FIM_DE_SEMANA
    coluna_feriado = modelo.coluna_do_dia(date(2027, 1, 1))
    assert modelo.headerData(coluna_feriado, Qt.Orientation.Horizontal, FUNDO) == COR_FERIADO
    assert (
        modelo.headerData(coluna_feriado, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        == "Ano Novo"
    )
    cor_p = ui.scalars(select(CodigoPresenca).where(CodigoPresenca.codigo == "P")).one().cor
    assert modelo.data(indice(modelo, 2, date(2027, 1, 4)), FUNDO).name().upper() == cor_p.upper()


def test_vista_semanal(ui):
    modelo = grelha(ui, presencas.semana_de(date(2027, 1, 6)))
    assert modelo.columnCount() == N_ESQ + 7 + N_DIR
    assert modelo.headerData(N_ESQ, Qt.Orientation.Horizontal) == "2ª\n04/01"
    assert modelo.headerData(N_ESQ + 6, Qt.Orientation.Horizontal) == "dom\n10/01"


def test_totais_por_dia(ui):
    modelo = grelha(ui)
    totais = ModeloTotaisDia(modelo)
    dia = date(2027, 1, 4)
    coluna = modelo.coluna_do_dia(dia)
    esperado = ui.scalar(
        select(func.count())
        .select_from(Marcacao)
        .join(CodigoPresenca)
        .where(Marcacao.data == dia, CodigoPresenca.conta_trabalhado)
    )
    assert totais.data(totais.index(0, 1), MOSTRAR) == "Presentes (total)"
    assert totais.data(totais.index(0, coluna), MOSTRAR) == str(esperado)
    por_cliente = [
        int(totais.data(totais.index(n, coluna), MOSTRAR) or 0) for n in range(1, totais.rowCount())
    ]
    assert sum(por_cliente) == esperado
    assert totais.rowCount() == 1 + 7  # total + 7 clientes

    # Atualiza quando uma marcação muda.
    modelo.setData(indice(modelo, 2, dia), "FE", EDITAR)
    assert totais.data(totais.index(0, coluna), MOSTRAR) == str(esperado - 1)


def test_copiar_semana_anterior_na_grelha(ui):
    modelo = grelha(ui, FEV)
    copiadas = modelo.copiar_semana_anterior(date(2027, 2, 3))
    assert copiadas > 50
    assert modelo.data(indice(modelo, 4, date(2027, 2, 1)), EDITAR) == grelha(ui).data(
        indice(grelha(ui), 4, date(2027, 1, 25)), EDITAR
    )
    modelo.desfazer()
    assert marcacao(ui, 4, date(2027, 2, 1)) is None

    erros = erros_de(modelo)
    assert modelo.copiar_semana_anterior(date(2027, 2, 24)) == 0  # semana anterior vazia
    assert "não tem marcações" in erros[0]


def test_a_grelha_abre_em_menos_de_um_segundo_com_80_trabalhadores(ui):
    p = ui.scalars(select(CodigoPresenca).where(CodigoPresenca.codigo == "P")).one()
    empresa = ui.scalars(select(Empresa)).first()
    for n in range(100, 180):
        t = Trabalhador(numero=n, nome=f"Carga {n}", empresa=empresa)
        ui.add(t)
        ui.add_all(
            Marcacao(trabalhador=t, data=date(2027, 3, d), codigo=p, horas_extra=Decimal(d % 3))
            for d in range(1, 32)
        )
    ui.commit()

    inicio = time.perf_counter()
    modelo = grelha(ui, (date(2027, 3, 1), date(2027, 3, 31)), mostrar_inativos=True)
    totais = ModeloTotaisDia(modelo)
    papeis = (MOSTRAR, FUNDO, PAPEL_HORAS, Qt.ItemDataRole.TextAlignmentRole)
    for linha in range(modelo.rowCount()):
        for coluna in range(modelo.columnCount()):
            for papel in papeis:
                modelo.data(modelo.index(linha, coluna), papel)
    for linha in range(totais.rowCount()):
        for coluna in range(totais.columnCount()):
            totais.data(totais.index(linha, coluna), MOSTRAR)
    duracao = time.perf_counter() - inicio

    assert len(modelo.trabalhadores) == 104
    assert duracao < 1.0, f"a grelha demorou {duracao:.2f} s"


# --- Dashboard --------------------------------------------------------------------------------


def selecionar(ecra, celulas):
    selecao = QItemSelection()
    for celula in celulas:
        selecao.select(celula, celula)
    ecra.dias.selectionModel().select(selecao, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    ecra.dias.setCurrentIndex(celulas[0])
    ecra.dias.selectionModel().select(selecao, QItemSelectionModel.SelectionFlag.ClearAndSelect)


def test_navegacao_por_mes_e_por_semana(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 1, 15))
    assert ecra.titulo.text() == "Janeiro 2027"
    assert len(ecra.modelo.dias) == 31
    ecra.avancar(1)
    assert ecra.titulo.text() == "Fevereiro 2027"
    ecra.avancar(-2)
    assert ecra.titulo.text() == "Dezembro 2026"

    ecra.ir_para(date(2027, 1, 6))
    ecra.definir_vista(SEMANAL)
    assert ecra.titulo.text() == "Semana 1 — 04/01/2027 a 10/01/2027"
    assert len(ecra.modelo.dias) == 7
    ecra.avancar(1)
    assert ecra.modelo.dias[0] == date(2027, 1, 11)


def test_cada_tabela_mostra_so_as_suas_colunas(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 1, 15))
    g = ecra.grelha
    ultimo_dia = N_ESQ + 30
    assert not g.esq.isColumnHidden(0) and g.esq.isColumnHidden(N_ESQ)
    assert g.centro.isColumnHidden(0) and not g.centro.isColumnHidden(N_ESQ)
    assert not g.centro.isColumnHidden(ultimo_dia) and g.centro.isColumnHidden(ultimo_dia + 1)
    assert g.dir.isColumnHidden(ultimo_dia) and not g.dir.isColumnHidden(ultimo_dia + 1)
    assert ecra.rodape.centro.columnWidth(N_ESQ) == g.centro.columnWidth(N_ESQ)
    assert ecra.rodape.esq.width() == g.esq.width() and ecra.rodape.dir.width() == g.dir.width()


def test_filtros_do_dashboard(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 1, 15))
    assert ecra.filtro_empresa.count() == 3  # «todas» + 2
    ecra.filtro_empresa.setCurrentIndex(1)
    assert len({t.empresa_id for t in ecra.modelo.trabalhadores}) == 1
    ecra.filtro_empresa.setCurrentIndex(0)
    ecra.pesquisa.setText("helga")
    assert len(ecra.modelo.trabalhadores) == 2  # a terceira Helga está inativa
    ecra.mostrar_inativos.setChecked(True)
    assert len(ecra.modelo.trabalhadores) == 3
    ecra.pesquisa.setText("")
    assert len(ecra.modelo.trabalhadores) == 24


def test_botoes_de_codigo_aplicam_a_selecao(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 2, 1))
    assert list(ecra.botoes_codigo)[:3] == ["P", "PF", "DF"] and "" in ecra.botoes_codigo
    ecra.aplicar_codigo("PF")
    assert "Selecione primeiro" in ecra.estado.text()

    celulas = [indice(ecra.modelo, 2, date(2027, 2, n)) for n in range(1, 6)]
    selecionar(ecra, celulas)
    ecra.botoes_codigo["PF"].click()
    assert all(ecra.modelo.data(c, MOSTRAR) == "PF" for c in celulas)
    assert ecra.estado.text() == ""
    ecra.botoes_codigo[""].click()  # limpar
    assert marcacao(ui, 2, date(2027, 2, 1)) is None


def test_teclado_copiar_colar_apagar_e_desfazer(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 1, 15))
    origem = [indice(ecra.modelo, 2, date(2027, 1, n)) for n in range(4, 9)]
    valores = [ecra.modelo.data(c, EDITAR) for c in origem]
    selecionar(ecra, origem)
    QTest.keyClick(ecra.dias, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "\t".join(valores)

    destino = indice(ecra.modelo, 2, date(2027, 1, 11))
    selecionar(ecra, [destino])
    QTest.keyClick(ecra.dias, Qt.Key.Key_Delete)
    assert ecra.modelo.data(destino, EDITAR) == ""
    QTest.keyClick(ecra.dias, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    colados = [
        ecra.modelo.data(ecra.modelo.index(destino.row(), destino.column() + n), EDITAR)
        for n in range(5)
    ]
    assert colados == valores

    # Colar um só valor sobre uma seleção preenche a seleção toda.
    QApplication.clipboard().setText("FE")
    selecionar(ecra, origem)
    QTest.keyClick(ecra.dias, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert all(ecra.modelo.data(c, EDITAR) == "FE" for c in origem)
    QTest.keyClick(ecra.dias, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert [ecra.modelo.data(c, EDITAR) for c in origem] == valores


def test_escrever_o_codigo_e_enter_desce_para_a_linha_seguinte(ui):
    ecra = EcraPresencas(ui)
    ecra.resize(1300, 700)
    ecra.show()
    ecra.ir_para(date(2027, 2, 1))
    celula = indice(ecra.modelo, 2, date(2027, 2, 1))
    selecionar(ecra, [celula])
    ecra.dias.setFocus()
    QTest.keyClicks(ecra.dias, "p")
    editor = ecra.dias.findChild(QLineEdit)
    assert editor is not None, "escrever numa célula devia abrir o editor"
    QTest.keyClicks(editor, "f+2")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()  # o Qt fecha o editor de forma diferida
    assert ecra.modelo.data(celula, EDITAR) == "PF+2"
    seguinte = ecra.modelo.linhas_de_trabalhadores(celula.row() + 1)[0]
    assert ecra.dias.currentIndex().row() == seguinte
    assert ecra.dias.currentIndex().column() == celula.column()
    ecra.close()


def test_escrever_com_varias_celulas_selecionadas_aplica_a_todas(ui):
    ecra = EcraPresencas(ui)
    ecra.resize(1300, 700)
    ecra.show()
    ecra.ir_para(date(2027, 2, 1))
    celulas = [indice(ecra.modelo, 2, date(2027, 2, n)) for n in range(1, 6)]
    selecionar(ecra, celulas)
    ecra.dias.setFocus()
    QTest.keyClicks(ecra.dias, "d")
    editor = ecra.dias.findChild(QLineEdit)
    QTest.keyClicks(editor, "f")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert [ecra.modelo.data(c, EDITAR) for c in celulas] == ["DF"] * 5
    ecra.close()


def test_copiar_semana_anterior_no_dashboard(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 2, 1))
    ecra.copiar_semana_anterior()
    assert "Selecione primeiro" in ecra.estado.text()
    selecionar(ecra, [indice(ecra.modelo, 4, date(2027, 2, 3))])
    ecra.botao_copiar_semana.click()
    assert "Copiei" in ecra.estado.text() and "01/02 a 07/02" in ecra.estado.text()
    assert marcacao(ui, 4, date(2027, 2, 1)) is not None
    assert ecra.botao_desfazer.isEnabled()
    ecra.botao_desfazer.click()
    assert marcacao(ui, 4, date(2027, 2, 1)) is None


def test_clicar_num_grupo_recolhe_o(ui):
    ecra = EcraPresencas(ui)
    ecra.ir_para(date(2027, 1, 15))
    total = ecra.modelo.rowCount()
    ecra.grelha.esq.clicked.emit(ecra.modelo.index(0, 1))
    assert ecra.modelo.rowCount() < total
    assert not ecra.grelha.esq.isColumnHidden(1) and ecra.grelha.esq.isColumnHidden(N_ESQ)
