"""Gera `s27_ficticio.xlsx`: um Excel com a mesma estrutura da folha «s-27» real, mas com
nomes inventados. Serve para testar a importação sem dados pessoais.

    uv run python tests/fixtures/gerar_s27_ficticio.py

Reproduz as particularidades do ficheiro real: dois blocos, títulos de zona nas colunas dos
dias, linhas só com viatura, nomes duplicados entre blocos, uma linha só com número, erros na
linha do dia do mês e códigos antigos (incluindo «s» e um valor desconhecido).
"""

from datetime import date, timedelta
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string as col

DESTINO = Path(__file__).with_name("s27_ficticio.xlsx")
K, NQ = col("K"), col("NQ")
INICIO = date(2026, 12, 28)
DIAS_SEMANA = ["2ª", "3ª", "4ª", "5ª", "6ª", "sab", "dom"]


def coluna_de(dia: date) -> int:
    return K + (dia - INICIO).days


def cabecalhos(folha, linha_ano: int) -> None:
    """Ano, mês, semana, dia do mês e dia da semana, a partir de `linha_ano`."""
    for c in range(K, NQ + 1):
        dia = INICIO + timedelta(days=c - K)
        if dia.weekday() == 0:
            folha.cell(linha_ano, c, 2027)
            folha.cell(linha_ano + 2, c, "semana")
        folha.cell(linha_ano + 3, c, dia.day)
        folha.cell(linha_ano + 4, c, DIAS_SEMANA[dia.weekday()])


def gerar(destino: Path = DESTINO) -> Path:
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = "s-27"
    folha["B2"] = "Ponto semanal v2027"
    cabecalhos(folha, 2)
    cabecalhos(folha, 50)
    # Erros no dia do mês, como no ficheiro real.
    folha["EJ5"], folha["EM5"], folha["ET5"] = 5, 2, 2
    folha["X53"], folha["AE53"] = 3, 3

    def trabalhador(linha, numero, cliente, viatura, nome, marcas=None):
        folha.cell(linha, 1, numero)
        folha.cell(linha, 3, cliente)
        folha.cell(linha, 4, viatura)
        folha.cell(linha, 5, nome)
        for dia, valor in (marcas or {}).items():
            folha.cell(linha, coluna_de(dia), valor)

    def semana(segunda: date, valor="x") -> dict:
        return {segunda + timedelta(days=n): valor for n in range(5)}

    seg1, seg2 = date(2027, 1, 4), date(2027, 1, 11)

    # --- Bloco 1 (linhas 7 a 46) ---
    trabalhador(7, 1, None, None, "Ana Fixture", {**semana(seg1), **semana(seg2)})
    trabalhador(8, 2, "drp++", "ZC", "Bento Ensaio", {**semana(seg1), date(2027, 1, 11): "ferias"})
    trabalhador(
        9, 3, "drp+", None, "Célia Prova", {**semana(seg1, " X "), date(2027, 1, 12): "falta"}
    )
    trabalhador(10, 4, "drp+", "BR", "Telmo Simulado", semana(seg1))
    trabalhador(11, 5, "GG", "TS", "Pedro Inventado", {**semana(seg1), date(2027, 1, 13): "baixa"})
    trabalhador(12, None, "GG", None, "Dinis Teste", {date(2027, 1, 4): "b", date(2027, 1, 5): "s"})
    trabalhador(
        13,
        7,
        "FD",
        "AD 81",
        "Helder Postiço",
        {date(2027, 1, 4): "form", date(2027, 1, 5): "Férias"},
    )
    trabalhador(14, 8, "FD", None, "Paulo Amostra", {date(2027, 1, 4): "pf+2", date(2027, 1, 9): 8})

    # --- Bloco 2 (linhas 55 a 78), sem cliente ---
    folha["B48"] = "v2026 Folha de Ponto semanal"
    trabalhador(55, 2, None, None, "Íris Modelo", semana(seg1))
    trabalhador(56, 3, None, "AA", "Joel Exemplar")
    folha.cell(61, 1, 7)  # linha só com número
    trabalhador(62, 8, None, None, "Lia Fictícia")
    for linha, zona in ((65, "45 Orleans"), (68, "64 Biarritz")):
        for c in range(K, NQ + 1, 7):  # o título repete-se uma vez por semana
            folha.cell(linha, c, zona)
    trabalhador(66, 11, None, "AL 12", "Mário Suposto", semana(seg1))
    trabalhador(67, 12, None, None, "Nuno Hipotético")
    # Duplicados dos nomes do bloco 1 (maiúsculas e acentos diferentes).
    trabalhador(
        69, None, None, "BR", "TELMO SIMULADO", {date(2027, 1, 18): "x", date(2027, 1, 4): "falta"}
    )
    folha.cell(70, 1, 14)
    folha.cell(70, 4, "AL 55")  # só viatura
    trabalhador(71, 15, None, None, "Olga Imaginada")
    trabalhador(72, 16, None, "GG", "Helder postico", semana(seg2))
    trabalhador(74, 18, None, "BD", "Pedro Inventado")
    folha.cell(77, 4, "AH")  # só viatura
    folha.cell(78, 4, "AF")  # só viatura

    fm = livro.create_sheet("FM")
    fm["AF4"], fm["AG4"] = "Lousa", "Lusoc"
    fm["AF5"], fm["AG5"] = 0, 0

    livro.save(destino)
    return destino


if __name__ == "__main__":
    print(gerar())
