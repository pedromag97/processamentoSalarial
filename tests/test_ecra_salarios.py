"""Ecrã «Salários» e os campos novos da ficha e das tabelas."""

from datetime import date
from decimal import Decimal as D

import pytest
from PySide6.QtCore import Qt
from sqlalchemy import select

from lsc_presencas import salarios
from lsc_presencas.modelos import (
    FECHO_FECHADO,
    GER_QUANTIDADE_PREVENCAO,
    CodigoPresenca,
    Empresa,
    FechoMes,
    FolhaMes,
    LinhaGer,
    Marcacao,
    ParametrosEmpresa,
    QuantidadeGer,
    SalarioBase,
    Trabalhador,
)
from lsc_presencas.ui import definicoes as d
from lsc_presencas.ui.ecra_salarios import PAPEL_CAMPO, EcraSalarios
from lsc_presencas.ui.tabela import ModeloTabela

ANO, MES = 2026, 11
EDITAVEL = Qt.ItemFlag.ItemIsEditable


@pytest.fixture
def bd(app, fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        empresa = Empresa(nome="Empresa de Teste, Lda")
        sessao.add(empresa)
        sessao.flush()
        sessao.add(
            ParametrosEmpresa(
                empresa_id=empresa.id,
                inicio_vigencia=date(2026, 1, 1),
                subsidio_alimentacao_dia=D("8.50"),
                taxa_seguranca_social=D("0.11"),
            )
        )
        codigos = {c.codigo: c.id for c in sessao.scalars(select(CodigoPresenca))}
        for numero, nome in ((1, "Ana Exemplo"), (2, "Rui Exemplo")):
            t = Trabalhador(numero=numero, nome=nome, empresa_id=empresa.id)
            sessao.add(t)
            sessao.flush()
            sessao.add(
                SalarioBase(trabalhador_id=t.id, inicio_vigencia=date(2026, 1, 1), valor=D("920"))
            )
            for dia in (2, 3, 4, 5, 6):
                sessao.add(
                    Marcacao(trabalhador_id=t.id, data=date(ANO, MES, dia), codigo_id=codigos["P"])
                )
        ana = sessao.scalars(select(Trabalhador).where(Trabalhador.numero == 1)).one()
        sessao.add_all(
            [
                LinhaGer(
                    trabalhador_id=ana.id,
                    ordem=1,
                    nome="Banco de horas",
                    unidade="hora",
                    valor=D("8.125"),
                ),
                LinhaGer(
                    trabalhador_id=ana.id,
                    ordem=2,
                    nome="Prevenção",
                    unidade="dia",
                    valor=D("14"),
                    quantidade_de=GER_QUANTIDADE_PREVENCAO,
                ),
            ]
        )
        sessao.commit()
        yield sessao


def ecra_em(bd) -> EcraSalarios:
    ecra = EcraSalarios(bd)
    ecra.seletor.definir(ANO, MES)
    return ecra


def celulas(ecra) -> dict[str, list[str]]:
    t = ecra.tabela
    return {
        t.item(n, 1).text(): [t.item(n, c).text() for c in range(t.columnCount())]
        for n in range(t.rowCount())
    }


def celula_editavel(ecra, campo):
    t = ecra.tabela
    for n in range(t.rowCount()):
        for c in range(t.columnCount()):
            if t.item(n, c).data(PAPEL_CAMPO) == campo:
                return t.item(n, c)
    raise AssertionError(f"não há célula para {campo}")


def test_lista_e_folha_do_primeiro_trabalhador(bd):
    ecra = ecra_em(bd)
    assert ecra.lista.rowCount() == 2
    assert ecra.lista.item(0, 1).text() == "Ana Exemplo"
    assert ecra.selecionada.numero == 1
    linhas = celulas(ecra)
    assert linhas["Vencimento base (mês com 21 dias de trabalho)"][2] == "920,00 €"
    assert linhas["Presenças"][4:] == ["5", "219,05 €"]
    assert linhas["Subsídio de alimentação"][5] == "42,50 €"
    assert linhas["Banco de horas"][3] == "8,13 € / hora"
    assert "Vencimento RC" in linhas and "Total GER" in linhas and "A pagar" in linhas
    assert "IRS: falta escrever o valor do mês." in ecra.alertas.text()
    assert "2 trabalhador(es)" in ecra.resumo.text()


def test_so_o_irs_e_as_quantidades_manuais_se_escrevem(bd):
    ecra = ecra_em(bd)
    t = ecra.tabela
    editaveis = {
        t.item(n, c).data(PAPEL_CAMPO)[0]
        for n in range(t.rowCount())
        for c in range(t.columnCount())
        if t.item(n, c).flags() & EDITAVEL
    }
    assert editaveis == {"irs", "ger"}
    ids = [
        t.item(n, 4).data(PAPEL_CAMPO)
        for n in range(t.rowCount())
        if t.item(n, 4).flags() & EDITAVEL
    ]
    assert len(ids) == 1  # a prevenção conta-se da grelha, não se escreve


def test_escrever_o_irs_grava_e_recalcula(app, bd):
    ecra = ecra_em(bd)
    celula_editavel(ecra, ("irs",)).setText("35,5")
    app.processEvents()
    assert bd.scalars(select(FolhaMes)).one().irs == D("35.5")
    assert celulas(ecra)["IRS"][5] == "-35,50 €"
    assert "IRS: falta" not in ecra.alertas.text()
    assert ecra.mensagem.text() == ""


def test_escrever_uma_quantidade_grava_e_recalcula(app, bd):
    ecra = ecra_em(bd)
    linha_id = bd.scalars(select(LinhaGer.id).where(LinhaGer.nome == "Banco de horas")).one()
    celula_editavel(ecra, ("ger", linha_id)).setText("8")
    app.processEvents()
    assert bd.scalars(select(QuantidadeGer)).one().quantidade == D("8")
    assert celulas(ecra)["Banco de horas"][4:] == ["8", "65,00 €"]
    assert celulas(ecra)["Total GER"][5] == "65,00 €"
    assert ecra.lista.item(0, 3).text() == "65,00 €"


def test_valor_invalido_mostra_o_erro_e_nao_grava(app, bd):
    ecra = ecra_em(bd)
    celula_editavel(ecra, ("irs",)).setText("abc")
    app.processEvents()
    assert "não é um número válido" in ecra.mensagem.text()
    assert bd.scalars(select(FolhaMes)).first() is None
    assert celulas(ecra)["IRS"][2] == ""


def test_mudar_de_trabalhador_mostra_a_folha_dele(bd):
    ecra = ecra_em(bd)
    ecra.lista.selectRow(1)
    assert ecra.selecionada.numero == 2
    assert "Rui Exemplo" in ecra.titulo_folha.text()
    assert "Banco de horas" not in celulas(ecra)


def test_mes_fechado_fica_so_para_consulta(bd):
    empresa = bd.scalars(select(Empresa)).one()
    bd.add(FechoMes(empresa_id=empresa.id, ano=ANO, mes=MES, estado=FECHO_FECHADO))
    bd.commit()
    ecra = ecra_em(bd)
    t = ecra.tabela
    assert not any(
        t.item(n, c).flags() & EDITAVEL for n in range(t.rowCount()) for c in range(t.columnCount())
    )
    assert "fechado" in ecra.aviso.text()


def test_mes_sem_ninguem_nao_rebenta(bd):
    for t in bd.scalars(select(Trabalhador)):
        t.ativo = False
    bd.commit()
    ecra = EcraSalarios(bd)
    ecra.seletor.definir(2025, 1)
    assert ecra.lista.rowCount() == 0
    assert ecra.selecionada is None
    assert "Sem trabalhadores" in ecra.titulo_folha.text()


def test_folha_calculada_no_ecra_e_a_do_servico(bd):
    ecra = ecra_em(bd)
    ana = bd.scalars(select(Trabalhador).where(Trabalhador.numero == 1)).one()
    esperado = salarios.folha_do_trabalhador(bd, ana, ANO, MES).folha
    assert ecra.selecionada.folha.a_pagar == esperado.a_pagar


def test_tabelas_tem_os_campos_novos(bd):
    def chaves(colunas):
        return [c.campo for c in colunas]

    assert {"duodecimo_ferias", "duodecimo_natal"} <= set(chaves(d.COLUNAS_SALARIO))
    assert "taxa_seguranca_social" in chaves(d.COLUNAS_PARAMETROS)
    assert "conta_folha" in chaves(d.COLUNAS_CODIGO)
    modelo = ModeloTabela(bd, LinhaGer, d.COLUNAS_LINHA_GER)
    assert modelo.rowCount() == 2
