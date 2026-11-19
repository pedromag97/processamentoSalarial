"""Fecho do mês, fotografia das rubricas, lançamentos com auditoria e exportação."""

import json
import re
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from pypdf import PdfReader
from PySide6.QtCore import Qt
from sqlalchemy import func, select

from lsc_presencas import backups, calculo, config, exportacao, fecho, mapa, presencas
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.exportar_excel import AVISO, LINHA_TITULOS, TITULO_A_PAGAR, TITULO_TOTAL
from lsc_presencas.exportar_pdf import euros
from lsc_presencas.modelos import (
    Auditoria,
    Empresa,
    FechoMes,
    FechoTrabalhador,
    LancamentoManual,
    Marcacao,
    ParametrosEmpresa,
    SalarioBase,
    Trabalhador,
)
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_fecho import EcraFecho
from lsc_presencas.ui.ecra_lancamentos import EcraLancamentos

ANO, MES = MES_DEMO
EDITAR = Qt.ItemDataRole.EditRole


@pytest.fixture
def bd(fabrica):
    """Dados de demonstração com os valores por dia preenchidos (valores de teste)."""
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        for p in sessao.scalars(select(ParametrosEmpresa)):
            p.subsidio_alimentacao_dia = Decimal("6")
            p.ajuda_custo_franca_dia = Decimal("50")
            p.prevencao_dia = Decimal("30")
            p.taxa_seguranca_social = Decimal("0.11")
        sessao.commit()
        yield sessao


@pytest.fixture
def empresa(bd):
    return bd.scalars(select(Empresa).order_by(Empresa.nome)).first()


def contar(sessao, classe, *filtros):
    return sessao.scalar(select(func.count()).select_from(classe).where(*filtros))


def total_no_pdf(caminho) -> list[Decimal]:
    """O «a pagar» escrito num PDF (um por folha de trabalhador)."""
    texto = "\n".join(p.extract_text() for p in PdfReader(caminho).pages)
    achados = re.findall(r"A pagar\s*(-?[\d.]+,\d\d)\s*€", texto)
    return [Decimal(a.replace(".", "").replace(",", ".")) for a in achados]


# --- Mapa -------------------------------------------------------------------------------------


def test_mapa_do_mes_tem_os_trabalhadores_da_empresa(bd, empresa):
    m = mapa.construir(bd, empresa.id, ANO, MES)
    esperados = bd.scalars(
        select(Trabalhador.numero).where(Trabalhador.empresa_id == empresa.id, Trabalhador.ativo)
    ).all()
    assert [t.numero for t in m.trabalhadores] == sorted(esperados)
    assert m.parametros["subsidio_alimentacao_dia"] == Decimal("6")
    assert [d for d, _ in m.feriados] == [date(ANO, 1, 1)]
    assert m.total == sum(t.total for t in m.trabalhadores)
    assert all(t.dias for t in m.trabalhadores)


def test_inativo_sem_marcacoes_fica_de_fora_mas_entra_se_tiver_marcacoes(bd):
    inativo = bd.scalars(select(Trabalhador).where(~Trabalhador.ativo)).one()
    m = mapa.construir(bd, inativo.empresa_id, ANO, MES)
    assert inativo.numero not in [t.numero for t in m.trabalhadores]

    codigo = presencas.codigos_ativos(bd)["P"]
    presencas.aplicar_alteracoes(
        bd, [presencas.Alteracao(inativo.id, date(ANO, MES, 5), (codigo, Decimal(0)))]
    )
    m = mapa.construir(bd, inativo.empresa_id, ANO, MES)
    linha = next(t for t in m.trabalhadores if t.numero == inativo.numero)
    assert "marcacao_fora_contrato" in linha.resultado.chaves_de_alerta()


def test_a_fotografia_em_json_devolve_o_mesmo_mapa(bd, empresa):
    m = mapa.construir(bd, empresa.id, ANO, MES)
    cabecalho = mapa.cabecalho_de_json(empresa.id, ANO, MES, mapa.cabecalho_para_json(m))
    assert (cabecalho.empresa, cabecalho.codigos, cabecalho.parametros, cabecalho.feriados) == (
        m.empresa,
        m.codigos,
        m.parametros,
        m.feriados,
    )
    for t in m.trabalhadores:
        lido = mapa.trabalhador_de_json(
            t.trabalhador_id, t.numero, t.nome, mapa.trabalhador_para_json(t)
        )
        assert lido == t


# --- Fechar e reabrir -------------------------------------------------------------------------


def test_nao_fecha_com_erros(fabrica):
    with fabrica() as sessao:
        semear(sessao)  # sem valores por dia: as rubricas ficam por calcular
        sessao.commit()
        empresa = sessao.scalars(select(Empresa)).first()
        with pytest.raises(fecho.FechoRecusado, match="erro"):
            fecho.fechar(sessao, empresa.id, ANO, MES, confirmado=True)
        assert not fecho.esta_fechado(sessao, empresa.id, ANO, MES)
        assert backups.listar() == []


def test_avisos_pedem_confirmacao(bd, empresa):
    lista = fecho.alertas(bd, fecho.mapa_do_mes(bd, empresa.id, ANO, MES))
    erros, avisos = fecho.contar_niveis(lista)
    assert erros == 0 and avisos > 0  # ex.: falta o limite de isenção
    with pytest.raises(fecho.FechoPorConfirmar):
        fecho.fechar(bd, empresa.id, ANO, MES)
    assert not fecho.esta_fechado(bd, empresa.id, ANO, MES)


def test_fechar_guarda_fotografia_backup_e_auditoria(bd, empresa):
    antes = mapa.construir(bd, empresa.id, ANO, MES)
    fechado = fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True, utilizador="teste")
    assert fechado.fechado and fechado.total == antes.total
    assert fechado.total_a_pagar == antes.total_a_pagar != 0
    assert fecho.esta_fechado(bd, empresa.id, ANO, MES)
    assert len(backups.listar()) == 1
    assert backups.listar()[0].parent == config.pasta_backups()
    assert contar(bd, FechoTrabalhador) == len(antes.trabalhadores)
    registo = bd.scalars(select(Auditoria).where(Auditoria.entidade == "fecho_mes")).one()
    assert (registo.acao, registo.utilizador) == ("fechar", "teste")

    guardado = fecho.mapa_do_mes(bd, empresa.id, ANO, MES)
    assert guardado.fechado and guardado.fechado_por == "teste"
    assert guardado.trabalhadores == antes.trabalhadores
    assert all(t.folha is not None for t in guardado.trabalhadores)
    assert '"a_pagar"' in registo.valor_novo
    with pytest.raises(fecho.FechoRecusado, match="já está fechado"):
        fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)


def test_mes_fechado_nao_muda_com_alteracoes_posteriores(bd, empresa):
    fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    t = bd.scalars(select(Trabalhador).where(Trabalhador.empresa_id == empresa.id)).first()
    total = next(
        x.total
        for x in fecho.mapa_do_mes(bd, empresa.id, ANO, MES).trabalhadores
        if x.numero == t.numero
    )
    # Um aumento com efeitos retroativos e um parâmetro novo não mexem no mês fechado.
    t.salarios.append(SalarioBase(inicio_vigencia=date(ANO, MES, 1), valor=Decimal("5000")))
    t.nome = "Nome Alterado"
    bd.scalars(select(ParametrosEmpresa)).first().ajuda_custo_franca_dia = Decimal("99")
    bd.commit()
    depois = next(
        x for x in fecho.mapa_do_mes(bd, empresa.id, ANO, MES).trabalhadores if x.numero == t.numero
    )
    assert depois.total == total and depois.nome != "Nome Alterado"
    assert depois.folha.vencimento_base != Decimal("5000")
    assert mapa.construir(bd, empresa.id, ANO, MES).trabalhadores[0].folha.vencimento_base == 5000
    assert (
        mapa.construir(bd, empresa.id, ANO, MES).total
        != fecho.mapa_do_mes(bd, empresa.id, ANO, MES).total
    )


def test_mes_fechado_bloqueia_marcacoes_so_dessa_empresa(bd, empresa):
    fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    codigo = presencas.codigos_ativos(bd)["FE"]
    da_empresa = bd.scalars(
        select(Trabalhador).where(Trabalhador.empresa_id == empresa.id, Trabalhador.ativo)
    ).first()
    de_outra = bd.scalars(
        select(Trabalhador).where(Trabalhador.empresa_id != empresa.id, Trabalhador.ativo)
    ).first()
    dia = date(ANO, MES, 15)
    with pytest.raises(presencas.MesFechado):
        presencas.aplicar_alteracoes(
            bd, [presencas.Alteracao(da_empresa.id, dia, (codigo, Decimal(0)))]
        )
    assert presencas.aplicar_alteracoes(
        bd, [presencas.Alteracao(de_outra.id, dia, (codigo, Decimal(0)))]
    )


def test_reabrir_obriga_a_motivo_e_fica_registado(bd, empresa):
    fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    with pytest.raises(fecho.FechoRecusado, match="motivo"):
        fecho.reabrir(bd, empresa.id, ANO, MES, "   ")
    assert fecho.esta_fechado(bd, empresa.id, ANO, MES)

    fecho.reabrir(bd, empresa.id, ANO, MES, "Faltava uma baixa", utilizador="teste")
    assert not fecho.esta_fechado(bd, empresa.id, ANO, MES)
    assert contar(bd, FechoTrabalhador) == 0
    registo = bd.scalars(select(Auditoria).where(Auditoria.acao == "reabrir")).one()
    assert registo.motivo == "Faltava uma baixa" and registo.utilizador == "teste"
    assert bd.scalars(select(FechoMes)).one().nota == "Faltava uma baixa"
    assert len(backups.listar()) == 2  # um antes de fechar, outro antes de reabrir

    with pytest.raises(fecho.FechoRecusado, match="não está fechado"):
        fecho.reabrir(bd, empresa.id, ANO, MES, "outra vez")
    # Depois de reaberto, volta a aceitar marcações e pode fechar-se outra vez.
    t = bd.scalars(select(Trabalhador).where(Trabalhador.empresa_id == empresa.id)).first()
    codigo = presencas.codigos_ativos(bd)["FE"]
    presencas.aplicar_alteracoes(
        bd, [presencas.Alteracao(t.id, date(ANO, MES, 15), (codigo, Decimal(0)))]
    )
    assert fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True).fechado


def test_empresa_sem_parametros_ou_sem_trabalhadores_da_erro(bd):
    nova = Empresa(nome="Empresa Vazia")
    bd.add(nova)
    bd.commit()
    lista = fecho.alertas(bd, fecho.mapa_do_mes(bd, nova.id, ANO, MES))
    assert fecho.contar_niveis(lista)[0] == 2
    with pytest.raises(fecho.FechoRecusado):
        fecho.fechar(bd, nova.id, ANO, MES, confirmado=True)


def test_trabalhadores_sem_empresa_dao_aviso(bd, empresa):
    bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first().empresa_id = None
    bd.commit()
    lista = fecho.alertas(bd, fecho.mapa_do_mes(bd, empresa.id, ANO, MES))
    assert any("sem empresa" in a.mensagem and a.numero is None for a in lista)


def test_backups_guardam_so_os_ultimos_30(bd, tmp_path):
    pasta = tmp_path / "copias"
    for _ in range(33):
        backups.fazer_backup(bd.get_bind(), "teste", pasta)
    assert len(backups.listar(pasta)) == 30
    copia = backups.listar(pasta)[-1]
    assert copia.stat().st_size > 0


# --- Exportação -------------------------------------------------------------------------------


def test_exportacao_excel_e_pdf_batem_certo(bd, empresa, tmp_path):
    m = fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    feito = exportacao.exportar(m, tmp_path)

    inicio = f"{ANO}-{MES:02d}_{exportacao.nome_limpo(empresa.nome)}"
    assert feito.pasta == tmp_path / inicio
    assert feito.excel.name == f"{inicio}_resumo.xlsx"
    primeiro = m.trabalhadores[0]
    assert feito.pdfs[0].name == f"{inicio}_{primeiro.numero}_{primeiro.nome}.pdf"
    assert len(feito.pdfs) == len(m.trabalhadores)

    # Excel: a folha «Salários» bate com as folhas de salário do mapa.
    livro = openpyxl.load_workbook(feito.excel)
    assert livro.sheetnames == ["Salários", "Folhas", "Resumo", "Marcações", "Parâmetros"]
    salarios = livro["Salários"]
    titulos = [c.value for c in salarios[LINHA_TITULOS]]
    col_pagar = titulos.index(TITULO_A_PAGAR)
    linhas = list(salarios.iter_rows(min_row=LINHA_TITULOS + 1, values_only=True))
    por_trabalhador = [x for x in linhas if x[0] is not None]
    assert [x[0] for x in por_trabalhador] == [t.numero for t in m.trabalhadores]
    a_pagar_excel = sum(Decimal(str(x[col_pagar])) for x in por_trabalhador)
    assert a_pagar_excel == m.total_a_pagar
    assert Decimal(str(linhas[-1][col_pagar])) == m.total_a_pagar  # linha TOTAL
    assert AVISO in salarios["A2"].value
    # «Folhas»: linha a linha; o «A pagar» de cada trabalhador é o mesmo.
    detalhe = list(livro["Folhas"].iter_rows(min_row=LINHA_TITULOS + 1, values_only=True))
    a_pagar = {x[0]: Decimal(str(x[8])) for x in detalhe if x[3] == "A pagar"}
    assert a_pagar == {t.numero: t.a_pagar for t in m.trabalhadores}
    assert any(x[2] == "RC" and x[3] == "Presenças" and x[9] for x in detalhe)

    # A folha «Resumo» (rubricas do pré-processamento) continua lá.
    resumo = livro["Resumo"]
    titulos = [c.value for c in resumo[LINHA_TITULOS]]
    col_total = titulos.index(TITULO_TOTAL)
    linhas = list(resumo.iter_rows(min_row=LINHA_TITULOS + 1, values_only=True))
    por_trabalhador = [x for x in linhas if x[0] is not None]
    assert len(por_trabalhador) == len(m.trabalhadores)
    soma_excel = sum(Decimal(str(x[col_total])) for x in por_trabalhador)
    assert soma_excel == m.total
    assert Decimal(str(linhas[-1][col_total])) == m.total  # linha TOTAL
    assert AVISO in resumo["A2"].value
    assert livro["Marcações"].max_row - LINHA_TITULOS == sum(len(t.dias) for t in m.trabalhadores)
    parametros = {x[0]: x[1] for x in livro["Parâmetros"].iter_rows(values_only=True)}
    assert parametros[mapa.ROTULOS_PARAMETROS["ajuda_custo_franca_dia"]] == 50
    assert parametros[mapa.ROTULOS_PARAMETROS["limite_isencao_subsidio_dia"]] == "(por preencher)"

    # PDF: a soma dos «a pagar» individuais = conjunto = Excel.
    individuais = [total_no_pdf(p) for p in feito.pdfs]
    assert all(len(x) == 1 for x in individuais)
    assert [x[0] for x in individuais] == [t.a_pagar for t in m.trabalhadores]
    assert sum(total_no_pdf(feito.conjunto)) == a_pagar_excel
    assert len(PdfReader(feito.conjunto).pages) >= len(m.trabalhadores)

    texto = PdfReader(feito.pdfs[0]).pages[0].extract_text()
    assert "não substitui o recibo de vencimento" in texto
    assert primeiro.nome in texto and empresa.nome in texto
    assert "Tomei conhecimento" in texto
    assert "PROVISÓRIO" not in texto
    for esperado in ("Folha de salário", "Presenças", "Vencimento RC", "Líquido", "IRS"):
        assert esperado in texto
    assert "ilíquido estimado" not in texto


def test_exportacao_de_mes_aberto_fica_marcada_como_provisoria(bd, empresa, tmp_path):
    m = fecho.mapa_do_mes(bd, empresa.id, ANO, MES)
    feito = exportacao.exportar(m, tmp_path)
    assert "provisório" in feito.pasta.name
    assert "PROVISÓRIO" in PdfReader(feito.pdfs[0]).pages[0].extract_text()
    livro = openpyxl.load_workbook(feito.excel)
    assert "PROVISÓRIO" in livro["Resumo"]["A2"].value
    assert "PROVISÓRIO" in livro["Salários"]["A2"].value


def test_pdf_mostra_rubricas_por_calcular(fabrica, tmp_path):
    with fabrica() as sessao:
        semear(sessao)  # sem valores por dia
        sessao.commit()
        empresa = sessao.scalars(select(Empresa)).first()
        m = fecho.mapa_do_mes(sessao, empresa.id, ANO, MES)
        feito = exportacao.exportar(m, tmp_path)
        texto = PdfReader(feito.pdfs[0]).pages[0].extract_text()
        assert "por calcular" in texto
        livro = openpyxl.load_workbook(feito.excel)
        assert any("INCOMPLETO" in str(c.value) for c in livro["Resumo"][LINHA_TITULOS + 1])
        assert any("INCOMPLETA" in str(c.value) for c in livro["Salários"][LINHA_TITULOS + 1])


def test_mes_fechado_numa_versao_antiga_sai_sem_folha_de_salario(bd, empresa, tmp_path):
    fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    for linha in bd.scalars(select(FechoTrabalhador)):  # fotografia como era antes da folha
        dados = json.loads(linha.dados)
        del dados["folha"]
        linha.dados = json.dumps(dados, ensure_ascii=False)
    bd.commit()
    m = fecho.mapa_do_mes(bd, empresa.id, ANO, MES)
    assert m.sem_folhas and m.total_a_pagar == 0
    assert calculo.NIVEL_ERRO not in {a.nivel for a in fecho.alertas(bd, m)}
    feito = exportacao.exportar(m, tmp_path)
    assert openpyxl.load_workbook(feito.excel).sheetnames == ["Resumo", "Marcações", "Parâmetros"]
    texto = PdfReader(feito.pdfs[0]).pages[0].extract_text()
    assert "Total ilíquido estimado" in texto and "Mapa de pré-processamento salarial" in texto


def test_alertas_do_fecho_incluem_os_da_folha_de_salario(bd, empresa):
    lista = fecho.alertas(bd, fecho.mapa_do_mes(bd, empresa.id, ANO, MES))
    assert any("IRS: falta escrever" in a.mensagem for a in lista)
    for p in bd.scalars(select(ParametrosEmpresa)):
        p.taxa_seguranca_social = None
    bd.commit()
    lista = fecho.alertas(bd, fecho.mapa_do_mes(bd, empresa.id, ANO, MES))
    erros = [a for a in lista if a.nivel == calculo.NIVEL_ERRO]
    assert erros and all("Segurança Social" in a.mensagem for a in erros)
    with pytest.raises(fecho.FechoRecusado, match="erro"):
        fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)


def test_formatos_e_nomes_de_ficheiro():
    assert euros(Decimal("1234.5")) == "1.234,50 €"
    assert euros(Decimal("-100")) == "-100,00 €"
    assert euros(None) == ""
    assert exportacao.nome_limpo('A/B: "C" <D>|?* ') == "AB C D"
    assert exportacao.nome_limpo("+INNOVATION") == "+INNOVATION"


# --- Lançamentos manuais ----------------------------------------------------------------------


def coluna(modelo, campo):
    return next(n for n, c in enumerate(modelo.colunas) if c.campo == campo)


def escrever(modelo, linha, campo, valor):
    return modelo.setData(modelo.index(linha, coluna(modelo, campo)), valor, EDITAR)


def test_lancamentos_criar_alterar_e_apagar_com_auditoria(app, bd):
    ecra = EcraLancamentos(bd)
    ecra.seletor.definir(ANO, MES)
    modelo = ecra.modelo
    assert modelo.rowCount() == 1  # o adiantamento do seed
    t = bd.scalars(select(Trabalhador).where(Trabalhador.ativo)).first()

    linha = modelo.novo()
    assert escrever(modelo, linha, "trabalhador_id", t.id)
    assert escrever(modelo, linha, "descricao", "Prémio de obra")
    assert contar(bd, LancamentoManual) == 1  # ainda falta o valor
    assert escrever(modelo, linha, "tipo", "premio")
    assert escrever(modelo, linha, "valor", "150")
    assert contar(bd, LancamentoManual) == 2
    novo = modelo.linhas[linha]
    assert (novo.ano, novo.mes, novo.valor) == (ANO, MES, Decimal("150"))
    assert "2 lançamento(s)" in ecra.total.text()

    assert escrever(modelo, linha, "valor", "175,50")
    modelo.apagar(linha)
    acoes = bd.scalars(
        select(Auditoria.acao)
        .where(Auditoria.entidade == "lancamento_manual")
        .order_by(Auditoria.id)
    ).all()
    assert acoes == ["criar", "alterar", "apagar"]
    alteracao = bd.scalars(select(Auditoria).where(Auditoria.acao == "alterar")).one()
    assert '"valor": "150"' in alteracao.valor_antigo
    assert '"valor": "175.50"' in alteracao.valor_novo
    assert contar(bd, LancamentoManual) == 1

    # O resultado do trabalhador inclui o lançamento com o tipo.
    seed = bd.scalars(select(LancamentoManual)).one()
    m = mapa.construir(bd, seed.trabalhador.empresa_id, ANO, MES)
    linha_mapa = next(x for x in m.trabalhadores if x.trabalhador_id == seed.trabalhador_id)
    assert linha_mapa.lancamentos("adiantamento") == Decimal("-100")


def test_lancamentos_avisam_do_sinal_trocado(app, bd):
    ecra = EcraLancamentos(bd)
    ecra.seletor.definir(ANO, MES)
    assert not ecra.aviso.text()
    assert escrever(ecra.modelo, 0, "valor", "100")  # adiantamento positivo
    assert "valor positivo" in ecra.aviso.text()


def test_lancamentos_de_mes_fechado_nao_se_alteram(app, bd):
    seed = bd.scalars(select(LancamentoManual)).one()
    empresa_id = seed.trabalhador.empresa_id
    fecho.fechar(bd, empresa_id, ANO, MES, confirmado=True)
    ecra = EcraLancamentos(bd)
    ecra.seletor.definir(ANO, MES)
    erros = []
    ecra.modelo.erro.connect(erros.append)
    assert "Mês fechado para" in ecra.aviso.text()

    assert not escrever(ecra.modelo, 0, "valor", "-999")
    assert "fechado" in erros[-1]
    assert bd.scalars(select(LancamentoManual)).one().valor == Decimal("-100")
    assert not ecra.modelo.apagar(0)
    assert contar(bd, LancamentoManual) == 1

    # Criar para um trabalhador da empresa fechada também é recusado; de outra empresa, não.
    outro = bd.scalars(
        select(Trabalhador).where(Trabalhador.empresa_id != empresa_id, Trabalhador.ativo)
    ).first()
    for trabalhador_id, aceite in ((seed.trabalhador_id, False), (outro.id, True)):
        linha = ecra.modelo.novo()
        escrever(ecra.modelo, linha, "trabalhador_id", trabalhador_id)
        escrever(ecra.modelo, linha, "descricao", "Teste")
        assert escrever(ecra.modelo, linha, "valor", "-10") is aceite
    assert contar(bd, LancamentoManual) == 2


# --- Ecrã de fecho ----------------------------------------------------------------------------


def test_ecra_de_fecho_fechar_exportar_e_reabrir(app, bd, empresa, pasta_da_app):
    ecra = EcraFecho(bd)
    ecra.escolher(empresa.id, ANO, MES)
    assert ecra.rotulo_estado.text() == "ABERTO"
    assert ecra.tabela_previa.rowCount() == len(ecra.mapa.trabalhadores) + 1
    assert ecra.tabela_alertas.rowCount() == len(ecra.alertas) > 0
    assert ecra.botao_fechar.isEnabled()

    assert not ecra.fechar()  # falta confirmar os avisos
    assert "Confirme" in ecra.mensagem.text()
    ecra.visto_avisos.setChecked(True)
    assert ecra.fechar()
    assert ecra.rotulo_estado.text().startswith("FECHADO")
    assert "Mês fechado" in ecra.mensagem.text()
    feito = ecra.ultima_exportacao
    assert feito.excel.is_file() and feito.conjunto.is_file()
    assert pasta_da_app in feito.pasta.parents  # nada fora da pasta de dados (de teste)
    assert sum(total_no_pdf(feito.conjunto)) == ecra.mapa.total_a_pagar
    titulos = [
        ecra.tabela_previa.horizontalHeaderItem(n).text()
        for n in range(ecra.tabela_previa.columnCount())
    ]
    assert titulos[-6:] == [
        "Vencimento RC",
        "GER",
        "Líquido",
        "Adiantamentos e acertos",
        "A pagar",
        "Estado",
    ]
    assert euros(ecra.mapa.total_a_pagar) in ecra.titulo_previa.text()
    ultima = ecra.tabela_previa.rowCount() - 1
    assert ecra.tabela_previa.item(ultima, len(titulos) - 2).text() == euros(
        ecra.mapa.total_a_pagar
    )

    assert not ecra.reabrir()  # sem motivo
    assert "motivo" in ecra.mensagem.text()
    ecra.campo_motivo.setText("Corrigir férias")
    assert ecra.reabrir()
    assert ecra.rotulo_estado.text() == "ABERTO"


def test_ecra_de_fecho_com_erros_nao_deixa_fechar(app, fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        sessao.commit()
        empresa = sessao.scalars(select(Empresa)).first()
        ecra = EcraFecho(sessao)
        ecra.escolher(empresa.id, ANO, MES)
        assert not ecra.botao_fechar.isEnabled()
        assert "erro(s)" in ecra.titulo_alertas.text()
        estados = [
            ecra.tabela_previa.item(n, ecra.tabela_previa.columnCount() - 1).text()
            for n in range(len(ecra.mapa.trabalhadores))
        ]
        assert set(estados) == {"incompleto"}
        assert not ecra.fechar()


def test_ecra_de_fecho_sem_empresas(app, fabrica):
    with fabrica(expire_on_commit=True) as sessao:
        ecra = EcraFecho(sessao)
        assert ecra.mapa is None
        assert not ecra.fechar() and not ecra.exportar()


def test_janela_tem_os_ecras_novos(app, fabrica):
    with fabrica() as sessao:
        semear(sessao)
        sessao.commit()
    janela = JanelaPrincipal(fabrica)
    assert isinstance(janela.mostrar("Fecho do mês"), EcraFecho)
    assert isinstance(janela.mostrar("Lançamentos"), EcraLancamentos)
    janela.close()


def test_grelha_de_presencas_recusa_mes_fechado(bd, empresa):
    fecho.fechar(bd, empresa.id, ANO, MES, confirmado=True)
    assert (empresa.id, ANO, MES) in presencas.meses_fechados(bd)
    assert contar(bd, Marcacao) > 0
    assert calculo.NIVEL_ERRO not in {
        a.nivel for a in fecho.alertas(bd, fecho.mapa_do_mes(bd, empresa.id, ANO, MES))
    }
