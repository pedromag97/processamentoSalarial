"""Testes dos ecrãs de tabelas e de trabalhadores (Qt em modo offscreen)."""

from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from sqlalchemy import func, select

from lsc_presencas.demo import semear
from lsc_presencas.modelos import (
    Cliente,
    CodigoPresenca,
    Empresa,
    ParametrosEmpresa,
    SalarioBase,
    Trabalhador,
)
from lsc_presencas.ui import definicoes as d
from lsc_presencas.ui.app import JanelaPrincipal
from lsc_presencas.ui.ecra_tabelas import EcraTabelas
from lsc_presencas.ui.ecra_trabalhadores import EcraTrabalhadores, FichaTrabalhador
from lsc_presencas.ui.formatos import ler_data, ler_decimal, sem_acentos, texto_data, texto_decimal
from lsc_presencas.ui.tabela import ModeloTabela

EDITAR = Qt.ItemDataRole.EditRole
MOSTRAR = Qt.ItemDataRole.DisplayRole
VISTO = Qt.ItemDataRole.CheckStateRole


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(app, fabrica):
    """Sessão como a da interface, com os dados de demonstração."""
    with fabrica(expire_on_commit=True) as sessao:
        semear(sessao)
        sessao.commit()
        yield sessao


def coluna(modelo, campo):
    return next(n for n, c in enumerate(modelo.colunas) if c.campo == campo)


def escrever(modelo, linha, campo, valor, papel=EDITAR):
    return modelo.setData(modelo.index(linha, coluna(modelo, campo)), valor, papel)


def ler(modelo, linha, campo, papel=MOSTRAR):
    return modelo.data(modelo.index(linha, coluna(modelo, campo)), papel)


def erros_de(modelo):
    erros = []
    modelo.erro.connect(erros.append)
    return erros


def contar(sessao, classe):
    return sessao.scalar(select(func.count()).select_from(classe))


# --- Formatos ---------------------------------------------------------------------------------


def test_ler_e_escrever_decimais():
    assert ler_decimal("7,50") == Decimal("7.50")
    assert ler_decimal(" 1 234.5 € ") == Decimal("1234.5")
    assert ler_decimal("") is None
    assert texto_decimal(Decimal("0.375")) == "0,375"
    assert texto_decimal(None) == ""
    for invalido in ("abc", "1,2,3", "NaN"):
        with pytest.raises(ValueError):
            ler_decimal(invalido)


def test_ler_e_escrever_datas():
    assert ler_data("15/01/2027") == date(2027, 1, 15)
    assert ler_data("2027-01-15") == date(2027, 1, 15)
    assert ler_data("  ") is None
    assert texto_data(date(2027, 1, 5)) == "05/01/2027"
    with pytest.raises(ValueError):
        ler_data("31/02/2027")


def test_sem_acentos():
    assert sem_acentos("Dália FICTÍCIO") == "dalia ficticio"


# --- Tabela genérica --------------------------------------------------------------------------


def test_linha_nova_so_e_gravada_com_os_campos_obrigatorios(ui):
    modelo = ModeloTabela(ui, Empresa, d.COLUNAS_EMPRESA)
    antes = contar(ui, Empresa)
    linha = modelo.novo()
    assert modelo.pendente(modelo.linhas[linha])
    assert escrever(modelo, linha, "nipc", "500000000")
    assert contar(ui, Empresa) == antes  # ainda falta o nome
    assert escrever(modelo, linha, "nome", "Empresa Nova")
    assert not modelo.pendente(modelo.linhas[linha])
    ui.expire_all()
    nova = ui.scalars(select(Empresa).where(Empresa.nome == "Empresa Nova")).one()
    assert nova.nipc == "500000000"


def test_valor_duplicado_e_recusado_com_mensagem(ui):
    modelo = ModeloTabela(ui, Cliente, d.COLUNAS_CLIENTE)
    erros = erros_de(modelo)
    linha = modelo.novo()
    assert not escrever(modelo, linha, "codigo", "GG")  # já existe
    assert erros == ["Já existe um registo com esse valor."]
    assert contar(ui, Cliente) == 7


def test_campo_obrigatorio_nao_pode_ficar_vazio(ui):
    modelo = ModeloTabela(ui, Empresa, d.COLUNAS_EMPRESA)
    erros = erros_de(modelo)
    nome = ler(modelo, 0, "nome")
    assert not escrever(modelo, 0, "nome", "  ")
    assert "obrigatório" in erros[0]
    assert ler(modelo, 0, "nome") == nome


def test_parametros_valores_por_preencher_e_edicao_de_decimais(ui):
    modelo = ModeloTabela(ui, ParametrosEmpresa, d.COLUNAS_PARAMETROS)
    assert modelo.n_avisos() == 12  # 2 empresas × 6 valores vazios
    assert ler(modelo, 0, "acrescimo_he_horas_seguintes") == "0,375"
    assert ler(modelo, 0, "subsidio_alimentacao_dia") == ""

    assert escrever(modelo, 0, "subsidio_alimentacao_dia", "6,5")
    assert modelo.n_avisos() == 11
    ui.expire_all()
    assert modelo.linhas[0].subsidio_alimentacao_dia == Decimal("6.5")

    erros = erros_de(modelo)
    assert not escrever(modelo, 0, "subsidio_alimentacao_dia", "seis")
    assert "não é um número válido" in erros[0]
    assert modelo.linhas[0].subsidio_alimentacao_dia == Decimal("6.5")

    assert escrever(modelo, 0, "subsidio_alimentacao_dia", "")  # volta a ficar por preencher
    assert modelo.linhas[0].subsidio_alimentacao_dia is None
    assert modelo.n_avisos() == 12


def test_parametros_novos_trazem_os_valores_da_especificacao(ui):
    modelo = ModeloTabela(ui, ParametrosEmpresa, d.COLUNAS_PARAMETROS)
    linha = modelo.novo()
    assert ler(modelo, linha, "horas_semanais") == "40"
    assert ler(modelo, linha, "acrescimo_he_primeira_hora") == "0,25"
    assert ler(modelo, linha, "subsidio_alimentacao_dia") == ""
    empresa = ui.scalars(select(Empresa)).first()
    assert escrever(modelo, linha, "empresa_id", empresa.id)
    assert escrever(modelo, linha, "inicio_vigencia", "01/07/2027")
    assert contar(ui, ParametrosEmpresa) == 3
    assert ler(modelo, linha, "empresa_id") == empresa.nome


def test_flags_dos_codigos_editam_se_com_um_visto(ui):
    modelo = ModeloTabela(
        ui, CodigoPresenca, d.COLUNAS_CODIGO, consulta=lambda: select(CodigoPresenca)
    )
    linha = next(n for n, c in enumerate(modelo.linhas) if c.codigo == "PF")
    assert ler(modelo, linha, "subsidio_alimentacao", VISTO) == Qt.CheckState.Unchecked
    assert escrever(modelo, linha, "subsidio_alimentacao", Qt.CheckState.Checked, VISTO)
    ui.expire_all()
    pf = ui.scalars(select(CodigoPresenca).where(CodigoPresenca.codigo == "PF")).one()
    assert pf.subsidio_alimentacao is True
    assert ler(modelo, linha, "ajuda_custo_franca") == "Sim"
    assert escrever(modelo, linha, "ajuda_custo_franca", "zona")
    assert ler(modelo, linha, "ajuda_custo_franca") == "Conforme a zona"


def test_cor_invalida_e_recusada(ui):
    modelo = ModeloTabela(ui, CodigoPresenca, d.COLUNAS_CODIGO)
    erros = erros_de(modelo)
    assert not escrever(modelo, 0, "cor", "azulado")
    assert "cor válida" in erros[0]
    assert escrever(modelo, 0, "cor", "#112233")


def test_apagar_registo_em_uso_e_recusado(ui):
    modelo = ModeloTabela(ui, Cliente, d.COLUNAS_CLIENTE)
    erros = erros_de(modelo)
    linha = next(n for n, c in enumerate(modelo.linhas) if c.codigo == "GG")
    assert not modelo.apagar(linha)
    assert "está a ser usado" in erros[0]
    assert contar(ui, Cliente) == 7

    nova = modelo.novo()
    assert escrever(modelo, nova, "codigo", "TEMP")
    assert contar(ui, Cliente) == 8
    assert modelo.apagar(nova)
    assert contar(ui, Cliente) == 7


# --- Ecrã de tabelas --------------------------------------------------------------------------


def test_ecra_de_tabelas_tem_as_sete_tabelas(ui):
    ecra = EcraTabelas(ui)
    titulos = [ecra.separadores.tabText(n) for n in range(ecra.separadores.count())]
    assert titulos == [
        "Empresas",
        "Clientes",
        "Viaturas",
        "Zonas",
        "Códigos de presença",
        "Feriados",
        "Parâmetros por empresa",
    ]
    parametros = ecra.vistas["Parâmetros por empresa"]
    assert not parametros.aviso.isHidden()
    assert "12 valor(es) por preencher" in parametros.aviso.text()
    assert ecra.vistas["Clientes"].aviso.isHidden()
    assert ecra.vistas["Feriados"].modelo.rowCount() == 26


def test_empresa_nova_aparece_nas_escolhas_dos_parametros(ui):
    ecra = EcraTabelas(ui)
    empresas = ecra.vistas["Empresas"].modelo
    linha = empresas.novo()
    assert escrever(empresas, linha, "nome", "Terceira Empresa")
    ecra.separadores.setCurrentWidget(ecra.vistas["Parâmetros por empresa"])
    parametros = ecra.vistas["Parâmetros por empresa"].modelo
    rotulos = [r for _v, r in parametros.opcoes[coluna(parametros, "empresa_id")]]
    assert "Terceira Empresa" in rotulos


# --- Trabalhadores ----------------------------------------------------------------------------


def test_lista_de_trabalhadores_filtra_por_nome_e_esconde_inativos(ui):
    ecra = EcraTrabalhadores(ui)
    assert ecra.modelo.rowCount() == 24
    assert ecra.filtro.rowCount() == 23  # um inativo
    ecra.mostrar_inativos.setChecked(True)
    assert ecra.filtro.rowCount() == 24
    ecra.pesquisa.setText("dalia FICT")  # sem acentos nem maiúsculas
    assert ecra.filtro.rowCount() == 1
    assert ecra.contagem.text() == "1 de 24"
    ecra.pesquisa.setText("")
    assert ecra.filtro.rowCount() == 24


def test_trabalhador_novo_recebe_o_numero_seguinte(ui):
    ecra = EcraTrabalhadores(ui)
    modelo = ecra.modelo
    linha = modelo.novo()
    assert ler(modelo, linha, "numero") == "25"
    assert ler(modelo, linha, "ativo", VISTO) == Qt.CheckState.Checked
    assert escrever(modelo, linha, "nome", "Novo Trabalhador")
    novo = ui.scalars(select(Trabalhador).where(Trabalhador.numero == 25)).one()
    assert novo.empresa_id is None
    # Sem empresa e sem salário: as duas células ficam assinaladas.
    assert ler(modelo, linha, "salario_atual") == ""
    assert modelo.n_avisos() >= 2


def test_editar_empresa_e_datas_na_lista(ui):
    modelo = EcraTrabalhadores(ui).modelo
    empresa = ui.scalars(select(Empresa).order_by(Empresa.nome)).first()
    assert escrever(modelo, 0, "empresa_id", empresa.id)
    assert ler(modelo, 0, "empresa_id") == empresa.nome
    assert escrever(modelo, 0, "data_saida", "31/03/2027")
    assert modelo.linhas[0].data_saida == date(2027, 3, 31)
    assert not escrever(modelo, 0, "salario_atual", "2000")  # só de leitura


def test_numero_de_trabalhador_repetido_e_recusado(ui):
    modelo = EcraTrabalhadores(ui).modelo
    erros = erros_de(modelo)
    assert not escrever(modelo, 0, "numero", "2")
    assert erros == ["Já existe um registo com esse valor."]
    assert ler(modelo, 0, "numero") == "1"


def test_ficha_guarda_excecoes_e_recusa_valores_invalidos(ui):
    trabalhador = ui.scalars(select(Trabalhador).where(Trabalhador.numero == 6)).one()
    ficha = FichaTrabalhador(ui, trabalhador)
    assert ficha.dados.campos["nome"].text() == trabalhador.nome
    assert ficha.excecoes.campos["exc_prevencao"].text() == ""

    ficha.excecoes.campos["exc_prevencao"].setText("quarenta")
    assert not ficha.guardar()
    assert "Prevenção" in ficha.erro.text()
    ui.expire_all()
    assert trabalhador.exc_prevencao is None

    ficha.excecoes.campos["exc_prevencao"].setText("40")
    ficha.excecoes.campos["exc_valor_hora_extra"].setText("9,75")
    ficha.dados.campos["nome"].setText("Nome Alterado")
    assert ficha.guardar()
    ui.expire_all()
    assert trabalhador.exc_prevencao == Decimal("40")
    assert trabalhador.exc_valor_hora_extra == Decimal("9.75")
    assert trabalhador.nome == "Nome Alterado"


def test_ficha_historico_de_salarios(ui):
    trabalhador = ui.scalars(select(Trabalhador).where(Trabalhador.numero == 6)).one()
    ficha = FichaTrabalhador(ui, trabalhador)
    modelo = ficha.modelo_salarios
    assert modelo.rowCount() == 1
    assert ficha.aviso_salario.isHidden()

    linha = modelo.novo()
    assert escrever(modelo, linha, "inicio_vigencia", "01/06/2027")
    assert escrever(modelo, linha, "valor", "1 250,00")
    salarios = ui.scalars(
        select(SalarioBase)
        .where(SalarioBase.trabalhador_id == trabalhador.id)
        .order_by(SalarioBase.inicio_vigencia)
    ).all()
    assert [s.valor for s in salarios] == [salarios[0].valor, Decimal("1250.00")]
    ui.expire_all()
    assert d.salario_atual(trabalhador) == Decimal("1250.00")

    assert modelo.apagar(1) and modelo.apagar(0)
    assert not ficha.aviso_salario.isHidden()


# --- Janela principal -------------------------------------------------------------------------


def test_navegacao_da_janela_principal(app, fabrica):
    with fabrica() as sessao:
        semear(sessao)
        sessao.commit()
    janela = JanelaPrincipal(fabrica)
    nomes = [janela.navegacao.item(n).text() for n in range(janela.navegacao.count())]
    assert nomes == [
        "Presenças",
        "Lançamentos",
        "Salários",
        "Fecho do mês",
        "Relatórios",
        "Trabalhadores",
        "Tabelas",
        "Contas",
        "Auditoria",
        "Base de dados",
    ]
    assert janela.pilha.currentWidget() is janela.ecras["Presenças"]
    ecra = janela.mostrar("Trabalhadores")
    assert janela.pilha.currentWidget() is ecra
    assert ecra.modelo.rowCount() == 24
    assert janela.mostrar("Tabelas") is janela.pilha.currentWidget()
    janela.close()
