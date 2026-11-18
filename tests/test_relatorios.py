"""Relatórios, auditoria (ecrã e histórico da ficha) e cópias de segurança ao abrir."""

from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from PySide6.QtCore import Qt
from sqlalchemy import func, select

from lsc_presencas import __main__ as principal
from lsc_presencas import auditoria, backups, config, presencas, relatorios
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import Auditoria, CodigoPresenca, Empresa, Marcacao, Trabalhador
from lsc_presencas.ui.app import EcraInicio
from lsc_presencas.ui.ecra_auditoria import EcraAuditoria
from lsc_presencas.ui.ecra_relatorios import RELATORIOS, EcraRelatorios
from lsc_presencas.ui.ecra_trabalhadores import FichaTrabalhador

ANO, MES = MES_DEMO
EDITAR = Qt.ItemDataRole.EditRole


@pytest.fixture
def bd(fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        sessao.commit()
        yield sessao


def coluna(relatorio, titulo):
    return relatorio.colunas.index(titulo)


def linha_de(relatorio, numero):
    return next(x for x in relatorio.linhas if x[0] == numero)


# --- Relatórios -------------------------------------------------------------------------------


def test_periodos_juntam_dias_seguidos_e_saltam_o_fim_de_semana():
    dias = [date(2027, 1, n) for n in (4, 5, 6, 7, 8, 11, 15)]
    assert relatorios.periodos(dias) == "04/01–11/01, 15/01"
    assert relatorios.periodos([date(2027, 3, 1)]) == "01/03"
    assert relatorios.periodos([]) == ""


def test_mapa_anual_de_ferias(bd):
    r = relatorios.ferias_anual(bd, ANO)
    ativos = bd.scalar(select(func.count()).select_from(Trabalhador).where(Trabalhador.ativo))
    assert len(r.linhas) == ativos  # todos os ativos, mesmo sem férias marcadas
    sete = linha_de(r, 7)  # no seed, os nº múltiplos de 7 têm férias de 18 a 22 de janeiro
    assert sete[coluna(r, "Jan")] == 5 and sete[coluna(r, "Total")] == 5
    assert sete[coluna(r, "Fev")] is None
    assert sete[coluna(r, "Dias")] == "18/01–22/01"
    assert linha_de(r, 1)[coluna(r, "Total")] == 0
    assert r.totais[coluna(r, "Total")] == 15  # nº 7, 14 e 21
    assert relatorios.ferias_anual(bd, ANO + 1).totais[coluna(r, "Total")] == 0

    empresa = bd.scalars(select(Empresa)).first()
    so_uma = relatorios.ferias_anual(bd, ANO, empresa.id)
    assert 0 < len(so_uma.linhas) < len(r.linhas)
    assert so_uma.subtitulo == empresa.nome
    assert {x[coluna(r, "Empresa")] for x in so_uma.linhas} == {empresa.nome}


def test_mapa_de_prevencao_so_tem_quem_fez_prevencao(bd):
    r = relatorios.prevencao_anual(bd, ANO)
    assert [x[0] for x in r.linhas] == sorted(x[0] for x in r.linhas if x[0] in (8, 16))
    assert len(r.linhas) == 2 and r.totais[coluna(r, "Total")] == 2
    assert {x[coluna(r, "Dias")] for x in r.linhas} == {"27/01"}


def test_dias_por_cliente_e_por_viatura(bd):
    trabalhados = bd.scalar(
        select(func.count())
        .select_from(Marcacao)
        .join(CodigoPresenca)
        .where(CodigoPresenca.conta_trabalhado)
    )
    por_cliente = relatorios.dias_por_cliente(bd, ANO, MES)
    dias = coluna(por_cliente, "Dias de trabalho (pessoa × dia)")
    assert sum(x[dias] for x in por_cliente.linhas) == trabalhados == por_cliente.totais[dias]
    for x in por_cliente.linhas:  # os dias por código somam o total da linha
        codigos = [v or 0 for t, v in zip(por_cliente.colunas, x, strict=True) if t[:5] == "Dias "]
        assert sum(codigos[1:-1]) == x[dias]
        assert x[coluna(por_cliente, "Dias com atividade")] <= 31

    por_viatura = relatorios.dias_por_viatura(bd, ANO, MES)
    assert sum(x[dias] for x in por_viatura.linhas) == trabalhados
    assert por_viatura.linhas[-1][0] == "(sem viatura)"  # no seed, 1 em cada 3 não tem viatura

    empresas = bd.scalars(select(Empresa.id)).all()
    partes = [relatorios.dias_por_cliente(bd, ANO, MES, e).totais[dias] for e in empresas]
    assert sum(partes) == trabalhados
    assert relatorios.dias_por_cliente(bd, ANO, MES + 1).linhas == []


def test_relatorio_para_excel(bd, tmp_path):
    r = relatorios.ferias_anual(bd, ANO)
    folha = openpyxl.load_workbook(relatorios.para_excel(r, tmp_path / "ferias.xlsx")).active
    assert folha["A1"].value == r.titulo
    assert [c.value for c in folha[4]] == r.colunas
    assert folha.max_row == 4 + len(r.linhas) + 1
    assert folha.cell(folha.max_row, 2).value == "TOTAL"


def test_ecra_de_relatorios_mostra_e_exporta(app, bd, pasta_da_app):
    ecra = EcraRelatorios(bd)
    for posicao, (_, _, anual) in enumerate(RELATORIOS):
        ecra.escolher(posicao, ANO, MES)
        assert ecra.tabela.rowCount() == len(ecra.relatorio.linhas) + 1
        assert ecra.seletor.caixa_mes.isEnabled() is not anual
        assert ecra.exportar()
        assert ecra.ultimo_ficheiro.is_file() and pasta_da_app in ecra.ultimo_ficheiro.parents
    ecra.escolher(2, ANO, MES + 1)  # mês sem marcações
    assert ecra.tabela.rowCount() == 0 and not ecra.botao_exportar.isEnabled()
    assert not ecra.exportar()


# --- Auditoria --------------------------------------------------------------------------------


def test_descrever_registo():
    assert (
        auditoria.descrever('{"trabalhador": 3, "horas_extra": "2", "nota": null, "ativo": true}')
        == "trabalhador: 3 · horas extra: 2 · nota: (vazio) · ativo: sim"
    )
    assert auditoria.descrever(None) == ""
    assert auditoria.descrever("texto solto") == "valor: texto solto"


def test_listar_auditoria_com_filtros(bd):
    codigos = presencas.codigos_ativos(bd)
    um, dois = bd.scalars(select(Trabalhador).where(Trabalhador.ativo).limit(2)).all()
    dia = date(ANO, MES, 14)
    presencas.aplicar_alteracoes(
        bd,
        [
            presencas.Alteracao(um.id, dia, (codigos["FE"], Decimal(0))),
            presencas.Alteracao(dois.id, dia, (codigos["B"], Decimal(0))),
        ],
        utilizador="ana",
    )
    todos = auditoria.listar(bd)
    assert len(todos) == 2 and {r.utilizador for r in todos} == {"ana"}
    assert todos[0].entidade == "Marcação" and todos[0].acao == "Alterou"
    do_primeiro = auditoria.listar(bd, numero_trabalhador=um.numero)
    assert len(do_primeiro) == 1 and "FE" in do_primeiro[0].depois
    assert len(auditoria.listar(bd, texto="codigo: b")) == 1
    assert auditoria.listar(bd, entidade="lancamento_manual") == []
    assert len(auditoria.listar(bd, limite=1)) == 1


def test_ficha_regista_alteracoes_e_mostra_o_historico(app, bd):
    t = bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first()
    numero = t.numero
    ficha = FichaTrabalhador(bd, t)
    assert ficha.historico.tabela.rowCount() == 0

    ficha.dados.campos["nome"].setText("Nome Corrigido")
    ficha.excecoes.campos["exc_prevencao"].setText("35")
    assert ficha.guardar()
    registo = bd.scalars(select(Auditoria).where(Auditoria.entidade == "trabalhador")).one()
    assert '"Nome": "Nome Corrigido"' in registo.valor_novo
    assert '"Prevenção / dia (€)": "35"' in registo.valor_novo
    assert "Nome Corrigido" not in registo.valor_antigo
    assert "Empresa" not in registo.valor_novo  # só o que mudou

    # Guardar sem mudar nada não cria registos.
    outra = FichaTrabalhador(bd, t)
    assert outra.guardar()
    assert bd.scalar(select(func.count()).select_from(Auditoria)) == 1

    # Salário base: criar e alterar ficam no histórico.
    modelo = outra.modelo_salarios
    linha = modelo.novo()
    for campo, valor in (("inicio_vigencia", "01/02/2027"), ("valor", "1100")):
        n = next(i for i, c in enumerate(modelo.colunas) if c.campo == campo)
        assert modelo.setData(modelo.index(linha, n), valor, EDITAR)
    n = next(i for i, c in enumerate(modelo.colunas) if c.campo == "valor")
    assert modelo.setData(modelo.index(linha, n), "1150", EDITAR)
    acoes = bd.scalars(
        select(Auditoria.acao).where(Auditoria.entidade == "salario_base").order_by(Auditoria.id)
    ).all()
    assert acoes == ["criar", "alterar"]

    outra.historico.recarregar()
    assert outra.historico.tabela.rowCount() == 3
    assert auditoria.listar(bd, numero_trabalhador=numero + 1) == []


def test_ecra_de_auditoria_filtra(app, bd):
    codigos = presencas.codigos_ativos(bd)
    t = bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first()
    presencas.aplicar_alteracoes(
        bd, [presencas.Alteracao(t.id, date(ANO, MES, 14), (codigos["FE"], Decimal(0)))]
    )
    ecra = EcraAuditoria(bd)
    assert ecra.tabela.rowCount() == 1 and ecra.contagem.text() == "1 registo(s)"
    ecra.pesquisa.setText("não existe")
    assert ecra.tabela.rowCount() == 0
    ecra.pesquisa.setText("")
    ecra.caixa_entidade.setCurrentIndex(ecra.caixa_entidade.findData("fecho_mes"))
    assert ecra.tabela.rowCount() == 0


# --- Cópias de segurança ----------------------------------------------------------------------


def test_copia_de_seguranca_ao_abrir(pasta_da_app):
    principal.copia_ao_abrir()  # ainda não há base de dados: não faz nada
    assert backups.listar() == []
    fabrica = principal.preparar_bd(com_copia=True)
    assert backups.listar() == []  # primeira abertura: a base de dados foi criada agora
    fabrica.kw["bind"].dispose()

    fabrica = principal.preparar_bd(com_copia=True)
    fabrica.kw["bind"].dispose()
    copias = backups.listar()
    assert len(copias) == 1 and copias[0].name.endswith("_abertura.db")
    assert copias[0].parent == config.pasta_backups() and pasta_da_app in copias[0].parents


def test_botao_de_copia_de_seguranca(app, bd):
    ecra = EcraInicio(bd)
    assert "Cópias de segurança: 0" in ecra.texto.text()
    assert ecra.fazer_backup()
    assert "Cópias de segurança: 1" in ecra.texto.text()
    assert backups.listar()[0].name.endswith("_manual.db")
