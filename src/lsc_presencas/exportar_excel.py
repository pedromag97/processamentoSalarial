"""Excel-resumo mensal por empresa: resumo por trabalhador, marcações diárias e parâmetros."""

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import calculo
from .mapa import ROTULOS_PARAMETROS, MapaMes, MapaTrabalhador

AVISO = "Mapa de pré-processamento — não substitui o recibo de vencimento"
TITULO_TOTAL = "Total ilíquido estimado (€)"
DIAS_SEMANA = ["2.ª", "3.ª", "4.ª", "5.ª", "6.ª", "sáb", "dom"]

FORMATO_EUROS = "#,##0.00"
FORMATO_HORAS = "0.##"
NEGRITO = Font(bold=True)
FUNDO_TITULO = PatternFill("solid", fgColor="DDE6F0")
LINHA_TITULOS = 4


def estado_do_mapa(mapa: MapaMes) -> str:
    if not mapa.fechado:
        return "PROVISÓRIO — mês ainda não fechado"
    quando = f" em {mapa.fechado_em:%d/%m/%Y %H:%M}" if mapa.fechado_em else ""
    quem = f" por {mapa.fechado_por}" if mapa.fechado_por else ""
    return f"Mês fechado{quando}{quem}"


def _rubrica(t: MapaTrabalhador, chave: str, campo: str):
    r = t.resultado.rubrica(chave)
    return None if r is None else getattr(r, campo)


def colunas_do_resumo(mapa: MapaMes) -> list[tuple[str, str, object]]:
    """(título, formato, função que dá o valor de um trabalhador). Formato «» = texto/inteiro."""
    c = calculo
    colunas: list[tuple[str, str, object]] = [
        ("Nº", "", lambda t: t.numero),
        ("Nome", "", lambda t: t.nome),
        ("Cliente", "", lambda t: t.cliente),
        ("Zona", "", lambda t: t.zona),
        ("Dias de contrato", "", lambda t: t.resultado.dias_contrato),
    ]
    for codigo, _ in mapa.codigos:
        colunas.append(
            (f"Dias {codigo}", "", lambda t, k=codigo: t.resultado.contagens.get(k, 0) or None)
        )
    e, h = FORMATO_EUROS, FORMATO_HORAS
    colunas += [
        ("Salário base do período (€)", e, lambda t: _rubrica(t, c.SALARIO_BASE, "total")),
        ("Desconto por faltas e baixas (€)", e, lambda t: _rubrica(t, c.DESCONTO_SALARIO, "total")),
        ("Base processada (€)", e, lambda t: t.base_processada),
        ("Subsídio alim. (dias)", h, lambda t: _rubrica(t, c.SUBSIDIO_ALIMENTACAO, "quantidade")),
        ("Subsídio alim. isento (€)", e, lambda t: _rubrica(t, c.SUBSIDIO_ALIMENTACAO, "isento")),
        ("Subsídio alim. sujeito (€)", e, lambda t: _rubrica(t, c.SUBSIDIO_ALIMENTACAO, "sujeito")),
        ("Subsídio alim. total (€)", e, lambda t: _rubrica(t, c.SUBSIDIO_ALIMENTACAO, "total")),
        ("Ajuda de custo (dias)", h, lambda t: _rubrica(t, c.AJUDA_CUSTO_FRANCA, "quantidade")),
        ("Ajuda de custo isenta (€)", e, lambda t: _rubrica(t, c.AJUDA_CUSTO_FRANCA, "isento")),
        ("Ajuda de custo sujeita (€)", e, lambda t: _rubrica(t, c.AJUDA_CUSTO_FRANCA, "sujeito")),
        ("Ajuda de custo total (€)", e, lambda t: _rubrica(t, c.AJUDA_CUSTO_FRANCA, "total")),
        ("Prevenção (dias)", h, lambda t: _rubrica(t, c.PREVENCAO, "quantidade")),
        ("Prevenção (€)", e, lambda t: _rubrica(t, c.PREVENCAO, "total")),
        ("HE dia útil 1.ª hora (h)", h, lambda t: _rubrica(t, c.HE_PRIMEIRA_HORA, "quantidade")),
        ("HE dia útil 1.ª hora (€)", e, lambda t: _rubrica(t, c.HE_PRIMEIRA_HORA, "total")),
        ("HE dia útil seguintes (h)", h, lambda t: _rubrica(t, c.HE_HORAS_SEGUINTES, "quantidade")),
        ("HE dia útil seguintes (€)", e, lambda t: _rubrica(t, c.HE_HORAS_SEGUINTES, "total")),
        (
            "HE descanso/feriado (h)",
            h,
            lambda t: _rubrica(t, c.HE_DESCANSO_FERIADO, "quantidade"),
        ),
        ("HE descanso/feriado (€)", e, lambda t: _rubrica(t, c.HE_DESCANSO_FERIADO, "total")),
        ("Adiantamentos (€)", e, lambda t: t.lancamentos("adiantamento") or None),
        ("Descontos (€)", e, lambda t: t.lancamentos("desconto") or None),
        ("Prémios (€)", e, lambda t: t.lancamentos("premio") or None),
        ("Outros lançamentos (€)", e, lambda t: t.lancamentos("outro") or None),
        (TITULO_TOTAL, e, lambda t: t.total),
        ("Observações", "", observacoes),
    ]
    return colunas


def observacoes(t: MapaTrabalhador) -> str | None:
    notas = []
    if t.resultado.incompleto:
        notas.append("INCOMPLETO: há rubricas por calcular (valores em falta)")
    notas += [a.mensagem for a in t.resultado.alertas]
    return "; ".join(notas) or None


def _cabecalho(folha, mapa: MapaMes, subtitulo: str) -> None:
    folha["A1"] = f"{mapa.empresa} — {subtitulo} — {mapa.titulo_mes}"
    folha["A1"].font = Font(bold=True, size=13)
    folha["A2"] = f"{AVISO}. Total ilíquido estimado, antes de IRS e TSU. {estado_do_mapa(mapa)}."


def _titulos(folha, titulos: list[str]) -> None:
    for n, titulo in enumerate(titulos, start=1):
        celula = folha.cell(LINHA_TITULOS, n, titulo)
        celula.font = NEGRITO
        celula.fill = FUNDO_TITULO
        celula.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    folha.row_dimensions[LINHA_TITULOS].height = 45


def _folha_resumo(folha, mapa: MapaMes) -> None:
    folha.title = "Resumo"
    _cabecalho(folha, mapa, "resumo mensal")
    colunas = colunas_do_resumo(mapa)
    _titulos(folha, [titulo for titulo, _, _ in colunas])

    totais: dict[int, Decimal] = {}
    linha = LINHA_TITULOS
    for t in mapa.trabalhadores:
        linha += 1
        for n, (_, formato, obter) in enumerate(colunas, start=1):
            valor = obter(t)
            if valor is None:
                continue
            celula = folha.cell(linha, n, valor)
            if formato:
                celula.number_format = formato
            if n > 4 and isinstance(valor, int | Decimal):
                totais[n] = totais.get(n, Decimal(0)) + Decimal(valor)
    linha += 1
    folha.cell(linha, 2, "TOTAL").font = NEGRITO
    for n, total in totais.items():
        celula = folha.cell(linha, n, total)
        celula.font = NEGRITO
        if colunas[n - 1][1]:
            celula.number_format = colunas[n - 1][1]

    folha.freeze_panes = folha.cell(LINHA_TITULOS + 1, 3)
    for n, (titulo, _, _) in enumerate(colunas, start=1):
        largura = {"Nome": 30, "Observações": 60, "Nº": 6}.get(titulo, 13)
        folha.column_dimensions[get_column_letter(n)].width = largura


def _folha_marcacoes(folha, mapa: MapaMes) -> None:
    _cabecalho(folha, mapa, "marcações diárias")
    titulos = [
        "Nº",
        "Nome",
        "Data",
        "Dia",
        "Código",
        "Horas extra",
        "Cliente",
        "Viatura",
        "Zona",
        "Nota",
    ]
    _titulos(folha, titulos)
    linha = LINHA_TITULOS
    for t in mapa.trabalhadores:
        for d in t.dias:
            linha += 1
            valores = [
                t.numero,
                t.nome,
                d.data,
                DIAS_SEMANA[d.data.weekday()],
                d.codigo,
                d.horas_extra or None,
                d.cliente,
                d.viatura,
                d.zona,
                d.nota,
            ]
            for n, valor in enumerate(valores, start=1):
                if valor is not None:
                    folha.cell(linha, n, valor)
            folha.cell(linha, 3).number_format = "DD/MM/YYYY"
    folha.freeze_panes = folha.cell(LINHA_TITULOS + 1, 3)
    for n, largura in enumerate([6, 30, 12, 6, 8, 8, 10, 10, 16, 40], start=1):
        folha.column_dimensions[get_column_letter(n)].width = largura


def _folha_parametros(folha, mapa: MapaMes) -> None:
    _cabecalho(folha, mapa, "parâmetros usados")
    _titulos(folha, ["Parâmetro", "Valor"])
    linha = LINHA_TITULOS
    if mapa.parametros is None:
        linha += 1
        folha.cell(linha, 1, "Não há parâmetros da empresa em vigor neste mês.")
    else:
        for campo, rotulo in ROTULOS_PARAMETROS.items():
            linha += 1
            folha.cell(linha, 1, rotulo)
            valor = mapa.parametros.get(campo)
            folha.cell(linha, 2, "(por preencher)" if valor is None else valor)

    linha += 2
    folha.cell(linha, 1, "Feriados do mês (Portugal)").font = NEGRITO
    for data, nome in mapa.feriados:
        linha += 1
        folha.cell(linha, 1, nome)
        folha.cell(linha, 2, data).number_format = "DD/MM/YYYY"
    if not mapa.feriados:
        linha += 1
        folha.cell(linha, 1, "(nenhum)")

    linha += 2
    folha.cell(linha, 1, "Códigos de presença").font = NEGRITO
    for codigo, significado in mapa.codigos:
        linha += 1
        folha.cell(linha, 1, codigo)
        folha.cell(linha, 2, significado)
    folha.column_dimensions["A"].width = 58
    folha.column_dimensions["B"].width = 40


def gerar_excel(mapa: MapaMes, destino: Path) -> Path:
    livro = Workbook()
    _folha_resumo(livro.active, mapa)
    _folha_marcacoes(livro.create_sheet("Marcações"), mapa)
    _folha_parametros(livro.create_sheet("Parâmetros"), mapa)
    destino.parent.mkdir(parents=True, exist_ok=True)
    livro.save(destino)
    return destino
