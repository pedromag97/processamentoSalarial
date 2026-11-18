"""Importação da folha «s-27», sobre o Excel fictício de tests/fixtures."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import func, select

from lsc_presencas import importacao, presencas
from lsc_presencas.modelos import (
    PAIS_FRANCA,
    Auditoria,
    Cliente,
    Empresa,
    Marcacao,
    Trabalhador,
    Viatura,
    Zona,
)
from lsc_presencas.ui.ecra_importacao import AssistenteImportacao

FICTICIO = Path(__file__).parent / "fixtures" / "s27_ficticio.xlsx"
MARCACOES_ESPERADAS = 53


@pytest.fixture(scope="module")
def leitura():
    return importacao.ler_s27(FICTICIO)


@pytest.fixture
def mapeamento(leitura, sessao):
    proposto = importacao.mapeamento_inicial(leitura, presencas.codigos_ativos(sessao))
    return {**proposto, "s": importacao.IGNORAR, "form": "FJ", "8": importacao.IGNORAR}


def contar(sessao, classe):
    return sessao.scalar(select(func.count()).select_from(classe))


def trabalhador(sessao, nome):
    return sessao.scalars(select(Trabalhador).where(Trabalhador.nome == nome)).one()


def codigo_em(sessao, nome, dia):
    m = sessao.scalars(
        select(Marcacao).join(Trabalhador).where(Trabalhador.nome == nome, Marcacao.data == dia)
    ).one_or_none()
    return None if m is None else presencas.texto_celula(m.codigo.codigo, m.horas_extra)


def todos_iguais(leitura, decisao: bool):
    return {chave: decisao for chave in importacao.grupos_duplicados(leitura)}


# --- Leitura ----------------------------------------------------------------------------------


def test_o_excel_ficticio_existe_e_nao_e_o_real():
    assert FICTICIO.exists(), "corra: uv run python tests/fixtures/gerar_s27_ficticio.py"


def test_leitura_dos_dois_blocos(leitura):
    assert len(leitura.linhas) == 17
    assert [x.linha for x in leitura.linhas if x.bloco == 1] == list(range(7, 15))
    assert [x.linha for x in leitura.linhas if x.bloco == 2] == [55, 56, 62, 66, 67, 69, 71, 72, 74]
    assert leitura.clientes == ["drp++", "drp+", "GG", "FD"]
    assert (leitura.primeiro_dia, leitura.ultimo_dia) == (date(2026, 12, 28), date(2028, 1, 2))


def test_a_data_vem_da_posicao_da_coluna(leitura):
    ana = leitura.linhas[0]
    assert min(ana.valores) == date(2027, 1, 4) and max(ana.valores) == date(2027, 1, 15)
    assert len(ana.valores) == 10
    estrutura = importacao.Estrutura()
    assert estrutura.data_da_coluna(11) == date(2026, 12, 28)  # K
    assert estrutura.data_da_coluna(381) == date(2028, 1, 2)  # NQ


def test_discrepancias_do_dia_do_mes(leitura):
    assert len(leitura.discrepancias) == 5
    celulas = [d.split(":")[0] for d in leitura.discrepancias]
    assert celulas == ["EJ5", "EM5", "ET5", "X53", "AE53"]
    assert "06/05/2027" in leitura.discrepancias[0]


def test_titulos_de_zona_e_linhas_sem_nome(leitura):
    zonas = {x.linha: x.zona for x in leitura.linhas}
    assert zonas[55] is None and zonas[62] is None
    assert zonas[66] == zonas[67] == "45 Orleans"
    assert zonas[69] == zonas[74] == "64 Biarritz"
    assert all(x.zona is None for x in leitura.linhas if x.bloco == 1)
    assert leitura.zonas == ["45 Orleans", "64 Biarritz"]
    # Linhas só com viatura: a viatura entra, o trabalhador não.
    assert {"AL 55", "AH", "AF"} <= set(leitura.viaturas)
    notas = "\n".join(leitura.notas)
    for linha in (70, 77, 78):
        assert f"Linha {linha}: sem nome; importei só a viatura" in notas
    assert "Linha 61: sem nome nem viatura; ignorada." in notas


def test_valores_encontrados_e_mapeamento_proposto(leitura, sessao):
    assert dict(leitura.valores) == {
        "x": 46, "ferias": 2, "falta": 2, "baixa": 1, "b": 1, "s": 1, "form": 1, "pf+2": 1, "8": 1
    }  # fmt: skip
    proposto = importacao.mapeamento_inicial(leitura, presencas.codigos_ativos(sessao))
    assert proposto == {
        "x": "P", "ferias": "FE", "falta": "FI", "baixa": "B", "b": "B",
        "s": None, "form": None, "8": None, "pf+2": "PF+2",
    }  # fmt: skip


def test_nomes_duplicados_sem_maiusculas_nem_acentos(leitura):
    grupos = importacao.grupos_duplicados(leitura)
    assert {chave: [x.linha for x in linhas] for chave, linhas in grupos.items()} == {
        "telmo simulado": [10, 69],
        "pedro inventado": [11, 74],
        "helder postico": [13, 72],
    }


def test_ficheiro_sem_a_folha_s27(tmp_path):
    caminho = tmp_path / "outro.xlsx"
    openpyxl.Workbook().save(caminho)
    with pytest.raises(ValueError, match="s-27"):
        importacao.ler_s27(caminho)


# --- Plano ------------------------------------------------------------------------------------


def test_plano_exige_decisao_sobre_os_duplicados(leitura):
    with pytest.raises(ValueError, match="Falta decidir 3"):
        importacao.construir_plano(leitura, {})


def test_plano_com_a_mesma_pessoa_junta_as_linhas(leitura):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    assert len(pessoas) == 14
    telmo = next(p for p in pessoas if p.nome == "Telmo Simulado")
    assert telmo.linhas == [10, 69]
    assert (telmo.cliente, telmo.viatura, telmo.zona) == ("drp+", "BR", "64 Biarritz")
    assert telmo.valores[date(2027, 1, 18)] == "x"
    # No dia 4 as duas linhas discordam: fica a primeira e regista-se.
    assert telmo.valores[date(2027, 1, 4)] == "x"
    assert any("04/01/2027" in nota for nota in telmo.notas)
    pedro = next(p for p in pessoas if p.nome == "Pedro Inventado")
    assert pedro.viatura == "TS" and any("viatura diferente" in nota for nota in pedro.notas)


def test_plano_com_pessoas_diferentes_mantem_uma_por_linha(leitura):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, False))
    assert len(pessoas) == 17
    assert [p.linhas for p in pessoas if "elmo" in p.nome.lower()] == [[10], [69]]


# --- Gravação ---------------------------------------------------------------------------------


def test_gravar_cria_tabelas_trabalhadores_e_marcacoes(leitura, mapeamento, sessao):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    pessoas[0].empresa = "+INNOVATION"
    relatorio = importacao.gravar(sessao, leitura, pessoas, mapeamento)

    assert (relatorio.trabalhadores_criados, relatorio.trabalhadores_existentes) == (14, 0)
    assert relatorio.marcacoes == MARCACOES_ESPERADAS == contar(sessao, Marcacao)
    assert contar(sessao, Cliente) == 4
    assert contar(sessao, Viatura) == 11
    assert {z.pais for z in sessao.scalars(select(Zona))} == {PAIS_FRANCA}
    assert [e.nome for e in sessao.scalars(select(Empresa))] == ["+INNOVATION"]

    # O nº interno é atribuído pela app, em sequência (o nº do Excel repete-se).
    assert sorted(sessao.scalars(select(Trabalhador.numero))) == list(range(1, 15))
    ana, telmo = trabalhador(sessao, "Ana Fixture"), trabalhador(sessao, "Telmo Simulado")
    assert ana.empresa.nome == "+INNOVATION" and ana.cliente is None
    assert telmo.empresa is None
    assert (telmo.cliente.codigo, telmo.viatura.codigo, telmo.zona.nome) == (
        "drp+",
        "BR",
        "64 Biarritz",
    )

    assert codigo_em(sessao, "Ana Fixture", date(2027, 1, 4)) == "P"
    assert codigo_em(sessao, "Bento Ensaio", date(2027, 1, 11)) == "FE"
    assert codigo_em(sessao, "Célia Prova", date(2027, 1, 4)) == "P"  # « X » com espaços
    assert codigo_em(sessao, "Célia Prova", date(2027, 1, 12)) == "FI"
    assert codigo_em(sessao, "Pedro Inventado", date(2027, 1, 13)) == "B"
    assert codigo_em(sessao, "Dinis Teste", date(2027, 1, 4)) == "B"
    assert codigo_em(sessao, "Dinis Teste", date(2027, 1, 5)) is None  # «s» ignorado
    assert codigo_em(sessao, "Helder Postiço", date(2027, 1, 4)) == "FJ"  # «form» mapeado
    assert codigo_em(sessao, "Helder Postiço", date(2027, 1, 5)) == "FE"  # «Férias» com acento
    assert codigo_em(sessao, "Helder Postiço", date(2027, 1, 11)) == "P"  # da linha duplicada
    assert codigo_em(sessao, "Paulo Amostra", date(2027, 1, 4)) == "PF+2"

    # A marcação copia o cliente e a zona da ficha.
    m = sessao.scalars(select(Marcacao).where(Marcacao.trabalhador_id == telmo.id)).first()
    assert (m.cliente_id, m.zona_id) == (telmo.cliente_id, telmo.zona_id)
    assert m.horas_extra == Decimal("0")
    utilizadores = set(sessao.scalars(select(Auditoria.utilizador)))
    assert utilizadores == {"importação s-27"}
    assert contar(sessao, Auditoria) == MARCACOES_ESPERADAS


def test_relatorio_da_importacao(leitura, mapeamento, sessao):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    texto = importacao.gravar(sessao, leitura, pessoas, mapeamento).texto()
    for esperado in (
        "s27_ficticio.xlsx",
        "EJ5: tem 5",
        "DISCREPÂNCIAS NO DIA DO MÊS (5)",
        "Linha 70: sem nome; importei só a viatura «AL 55».",
        "Linha 65: título de zona «45 Orleans».",
        "«s» (1 ocorrências): ignorado",
        "«x» (46 ocorrências): → P",
        "nº 4 Telmo Simulado (linha 10, 69) — sem empresa",
        "Resumo: 14 trabalhadores criados, 0 já existiam, 53 marcações.",
    ):
        assert esperado in texto


def test_sem_decidir_todos_os_codigos_nao_grava_nada(leitura, sessao):
    proposto = importacao.mapeamento_inicial(leitura, presencas.codigos_ativos(sessao))
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    with pytest.raises(ValueError, match="«s»"):
        importacao.gravar(sessao, leitura, pessoas, proposto)
    assert contar(sessao, Trabalhador) == contar(sessao, Cliente) == 0


def test_destino_invalido_nao_grava_nada(leitura, mapeamento, sessao):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    with pytest.raises(ValueError):
        importacao.gravar(sessao, leitura, pessoas, {**mapeamento, "x": "NAOEXISTE"})
    assert contar(sessao, Trabalhador) == contar(sessao, Viatura) == contar(sessao, Marcacao) == 0


def test_importar_duas_vezes_nao_duplica(leitura, mapeamento, sessao):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, True))
    importacao.gravar(sessao, leitura, pessoas, mapeamento)
    segunda = importacao.gravar(sessao, leitura, pessoas, mapeamento)
    assert (segunda.trabalhadores_criados, segunda.trabalhadores_existentes) == (0, 14)
    assert segunda.marcacoes == 0
    assert contar(sessao, Trabalhador) == 14 and contar(sessao, Marcacao) == MARCACOES_ESPERADAS


def test_pessoas_diferentes_com_o_mesmo_nome_sao_criadas_em_separado(leitura, mapeamento, sessao):
    pessoas = importacao.construir_plano(leitura, todos_iguais(leitura, False))
    relatorio = importacao.gravar(sessao, leitura, pessoas, mapeamento)
    assert relatorio.trabalhadores_criados == 17
    nomes = [n.lower() for n in sessao.scalars(select(Trabalhador.nome))]
    assert nomes.count("telmo simulado") == 2


# --- Sugestão de empresa ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome, folha, esperado",
    [
        ("Bruno Miguel Ramos", "brunor", True),
        ("Manuel Teixeira", "mteix", True),
        ("João Moreira", "jmoreira", True),
        ("Ângelo Sousa", "angelo", True),
        ("Bruno Silva", "brunor", False),
        ("Rui Costa", "ruic", True),
        ("Rui Costa", "ruis", False),
        ("Mário Brito", "mteix", False),
    ],
)
def test_nome_corresponde_a_folha_do_mapa_de_ferias(nome, folha, esperado):
    assert importacao.nome_corresponde(nome, folha) is esperado


def test_sugestao_de_empresa_pelos_mapas_de_ferias(tmp_path):
    for ficheiro, folhas in (
        ("2027-LOUSA --Mapa de Ferias PT.xlsx", ["FERIAS", "AnaF", "M.Suposto"]),
        ("2027-LUSOC --Mapa de Ferias PT.xlsx", ["FERIAS", "BentoE", "AnaF"]),
    ):
        livro = openpyxl.Workbook()
        livro.active.title = folhas[0]
        for nome in folhas[1:]:
            livro.create_sheet(nome)
        livro.save(tmp_path / ficheiro)

    folhas = importacao.folhas_dos_mapas_de_ferias(tmp_path)
    assert folhas["LOUSA"] == {"ferias", "anaf", "msuposto"}
    empresas = importacao.EMPRESAS_BASE
    assert (
        importacao.sugerir_empresa("Mário Suposto", folhas, empresas) == "LOUSACABO CONSTRUÇÕES LDA"
    )
    assert importacao.sugerir_empresa("Bento Ensaio", folhas, empresas) == "+INNOVATION"
    assert importacao.sugerir_empresa("Ana Fixture", folhas, empresas) is None  # está nos dois
    assert importacao.sugerir_empresa("Olga Imaginada", folhas, empresas) is None
    assert importacao.folhas_dos_mapas_de_ferias(tmp_path / "nao_existe") == {}


# --- Assistente -------------------------------------------------------------------------------


def test_assistente_do_principio_ao_fim(fabrica, tmp_path, monkeypatch):
    monkeypatch.setenv("LSC_APP_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    with fabrica(expire_on_commit=True) as sessao:
        a = AssistenteImportacao(sessao)
        a.show()

        a.pagina_ficheiro.caminho.setText(str(tmp_path / "nao_existe.xlsx"))
        a.next()
        assert a.currentPage() is a.pagina_ficheiro
        assert "Não consegui ler" in a.pagina_ficheiro.aviso.text()
        a.pagina_ficheiro.caminho.setText(str(FICTICIO))
        a.next()

        # Códigos: «s», «form» e «8» têm de ser decididos.
        assert a.currentPage() is a.pagina_codigos
        assert a.pagina_codigos.tabela.rowCount() == 9
        assert a.pagina_codigos.escolhas["x"].currentData() == "P"
        assert a.pagina_codigos.escolhas["pf+2"].currentData() == "PF+2"
        assert a.pagina_codigos.escolhas["s"].currentData() is None
        a.next()
        assert a.currentPage() is a.pagina_codigos
        assert "«s»" in a.pagina_codigos.aviso.text()
        for valor, destino in (
            ("s", importacao.IGNORAR),
            ("form", "FJ"),
            ("8", importacao.IGNORAR),
        ):
            caixa = a.pagina_codigos.escolhas[valor]
            caixa.setCurrentIndex(caixa.findData(destino))
        a.next()

        # Duplicados: sem decisão não avança.
        assert a.currentPage() is a.pagina_duplicados
        assert a.pagina_duplicados.tabela.rowCount() == 3
        a.next()
        assert a.currentPage() is a.pagina_duplicados
        for caixa in a.pagina_duplicados.escolhas.values():
            caixa.setCurrentIndex(caixa.findData(True))
        a.next()

        # Empresas: atribuição em massa.
        assert a.currentPage() is a.pagina_empresas
        assert a.pagina_empresas.tabela.rowCount() == 14
        assert a.empresas == importacao.EMPRESAS_BASE  # a base de dados ainda não tem empresas
        assert "14 sem empresa" in a.pagina_empresas.resumo.text()
        a.pagina_empresas.atribuir(list(range(8)), "LOUSACABO CONSTRUÇÕES LDA")
        a.pagina_empresas.tabela.selectRow(9)
        a.pagina_empresas.escolha.setCurrentIndex(a.pagina_empresas.escolha.findData("+INNOVATION"))
        a.pagina_empresas.botao.click()
        assert "5 sem empresa" in a.pagina_empresas.resumo.text()
        a.next()

        # Resumo: ainda nada gravado.
        assert a.currentPage() is a.pagina_resumo
        assert "Marcações a importar: 53 (ignoradas: 2)" in a.pagina_resumo.texto.toPlainText()
        assert contar(sessao, Trabalhador) == 0
        a.next()

        assert a.currentPage() is a.pagina_relatorio
        assert contar(sessao, Trabalhador) == 14
        assert contar(sessao, Marcacao) == MARCACOES_ESPERADAS
        assert contar(sessao, Empresa) == 2
        assert trabalhador(sessao, "Ana Fixture").empresa.nome == "LOUSACABO CONSTRUÇÕES LDA"
        assert a.ficheiro_relatorio.parent == tmp_path / "saidas"
        assert "Resumo: 14 trabalhadores criados" in a.ficheiro_relatorio.read_text(
            encoding="utf-8"
        )
        assert "Resumo: 14" in a.pagina_relatorio.texto.toPlainText()
        a.close()
    app.processEvents()
