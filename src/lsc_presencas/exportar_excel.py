"""Excel mensal por empresa: salários (uma linha por trabalhador), folhas de salário linha a
linha, resumo das rubricas do pré-processamento, marcações diárias e parâmetros."""

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import calculo
from . import folha_salario as fs
from .mapa import ROTULOS_PARAMETROS, MapaMes, MapaTrabalhador

AVISO = "Documento interno de apuramento — não substitui o recibo de vencimento"
TITULO_TOTAL = "Total ilíquido estimado (€)"
TITULO_A_PAGAR = "A pagar (€)"
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


def _da_folha(t: MapaTrabalhador, chave: str, campo: str = "total"):
    linha = None if t.folha is None else t.folha.linha(chave)
    return None if linha is None else getattr(linha, campo)


def _total_da_folha(nome: str):
    return lambda t: None if t.folha is None else getattr(t.folha, nome)


def observacoes_da_folha(t: MapaTrabalhador) -> str | None:
    if t.folha is None:
        return "Sem folha de salário: mês fechado numa versão anterior do programa"
    notas = ["INCOMPLETA: há linhas por calcular (valores em falta)"] if t.folha.incompleta else []
    notas += [a.mensagem for a in t.folha.alertas]
    return "; ".join(notas) or None


def colunas_dos_salarios() -> list[tuple[str, str, object]]:
    """Folha «Salários»: uma linha por trabalhador, do vencimento ao a pagar."""
    e, h = FORMATO_EUROS, FORMATO_HORAS
    colunas: list[tuple[str, str, object]] = [
        ("Nº", "", lambda t: t.numero),
        ("Nome", "", lambda t: t.nome),
        ("Vencimento base (€)", e, lambda t: None if t.folha is None else t.folha.vencimento_base),
        ("Dias trabalhados", h, lambda t: _da_folha(t, fs.PRESENCAS, "quantidade")),
        ("Dias de férias", h, lambda t: _da_folha(t, fs.FERIAS, "quantidade")),
        ("Dias de baixa", h, lambda t: _da_folha(t, fs.BAIXA, "quantidade")),
        ("Dias de faltas", h, lambda t: _da_folha(t, fs.FALTAS, "quantidade")),
    ]
    for titulo, chave in (
        ("Presenças (€)", fs.PRESENCAS),
        ("Subsídio de alimentação (€)", fs.SUBSIDIO_ALIMENTACAO),
        ("Subsídio de férias (€)", fs.SUBSIDIO_FERIAS),
        ("Subsídio de Natal (€)", fs.SUBSIDIO_NATAL),
        ("Férias (€)", fs.FERIAS),
        ("Baixa (€)", fs.BAIXA),
        ("Faltas (€)", fs.FALTAS),
        ("IRS (€)", fs.IRS),
        ("Segurança Social (€)", fs.SEGURANCA_SOCIAL),
    ):
        colunas.append((titulo, e, lambda t, k=chave: _da_folha(t, k)))
    colunas += [
        ("Vencimento RC (€)", e, _total_da_folha("vencimento_rc")),
        ("Total GER (€)", e, _total_da_folha("total_ger")),
        ("Líquido (€)", e, _total_da_folha("liquido")),
        ("Adiantamentos e acertos (€)", e, _total_da_folha("total_movimentos")),
        (TITULO_A_PAGAR, e, _total_da_folha("a_pagar")),
        ("Observações", "", observacoes_da_folha),
    ]
    return colunas


def _folha_salarios(folha, mapa: MapaMes) -> None:
    folha.title = "Salários"
    folha["A1"] = f"{mapa.empresa} — folhas de salário — {mapa.titulo_mes}"
    folha["A1"].font = Font(bold=True, size=13)
    folha["A2"] = f"{AVISO}. {estado_do_mapa(mapa)}."
    colunas = colunas_dos_salarios()
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
            if n > 3 and isinstance(valor, int | Decimal):
                totais[n] = totais.get(n, Decimal(0)) + Decimal(valor)
    linha += 1
    folha.cell(linha, 2, "TOTAL").font = NEGRITO
    for n, total in totais.items():
        celula = folha.cell(linha, n, total)
        celula.font = NEGRITO
        celula.number_format = colunas[n - 1][1]
    folha.freeze_panes = folha.cell(LINHA_TITULOS + 1, 3)
    for n, (titulo, _, _) in enumerate(colunas, start=1):
        largura = {"Nome": 30, "Observações": 60, "Nº": 6}.get(titulo, 13)
        folha.column_dimensions[get_column_letter(n)].width = largura


def _folha_detalhe(folha, mapa: MapaMes) -> None:
    """Folha «Folhas»: todas as linhas de todas as folhas de salário, com a conta de cada uma."""
    folha["A1"] = f"{mapa.empresa} — folhas de salário, linha a linha — {mapa.titulo_mes}"
    folha["A1"].font = Font(bold=True, size=13)
    folha["A2"] = f"{AVISO}. {estado_do_mapa(mapa)}."
    _titulos(
        folha,
        [
            "Nº",
            "Nome",
            "Bloco",
            "Descrição",
            "Valor do mês (€)",
            "Valor unitário (€)",
            "Unidade",
            "Quantidade",
            "Total (€)",
            "Como se calcula",
        ],
    )
    n = LINHA_TITULOS

    def escrever(t: MapaTrabalhador, valores: list, negrito: bool = False) -> None:
        nonlocal n
        n += 1
        for coluna, valor in enumerate([t.numero, t.nome, *valores], start=1):
            if valor is None:
                continue
            celula = folha.cell(n, coluna, valor)
            if negrito:
                celula.font = NEGRITO
            if coluna in (5, 6, 9):
                celula.number_format = FORMATO_EUROS if coluna != 6 else "#,##0.0000"
            elif coluna == 8:
                celula.number_format = FORMATO_HORAS

    def total(t: MapaTrabalhador, titulo: str, valor: Decimal) -> None:
        escrever(t, ["", titulo, None, None, None, None, valor, None], negrito=True)

    for t in mapa.trabalhadores:
        f = t.folha
        if f is None:
            continue
        base = f"Vencimento base (mês com {f.dias_trabalho_mes} dias de trabalho)"
        escrever(t, ["RC", base, f.vencimento_base, None, None, None, None, None])
        for bloco, linhas in (("RC", f.linhas_rc), ("GER", f.linhas_ger)):
            for x in linhas:
                escrever(
                    t,
                    [
                        bloco,
                        x.descricao,
                        x.valor_mes,
                        x.valor_unitario,
                        x.unidade if x.valor_unitario is not None else None,
                        x.quantidade,
                        x.total if x.total is not None else "por calcular",
                        x.formula,
                    ],
                )
            if bloco == "RC":
                total(t, "Vencimento RC", f.vencimento_rc)
            elif linhas:
                total(t, "Total GER", f.total_ger)
        total(t, "Líquido", f.liquido)
        for m in f.movimentos:
            escrever(t, ["", m.descricao, None, None, None, None, m.valor, None])
        total(t, TITULO_A_PAGAR.replace(" (€)", ""), f.a_pagar)
    folha.freeze_panes = folha.cell(LINHA_TITULOS + 1, 3)
    for coluna, largura in enumerate([6, 30, 7, 44, 14, 14, 9, 11, 14, 70], start=1):
        folha.column_dimensions[get_column_letter(coluna)].width = largura


def gerar_excel(mapa: MapaMes, destino: Path) -> Path:
    livro = Workbook()
    if not mapa.sem_folhas:
        _folha_salarios(livro.active, mapa)
        _folha_detalhe(livro.create_sheet("Folhas"), mapa)
        livro.create_sheet("Resumo")
    _folha_resumo(livro["Resumo"] if "Resumo" in livro.sheetnames else livro.active, mapa)
    _folha_marcacoes(livro.create_sheet("Marcações"), mapa)
    _folha_parametros(livro.create_sheet("Parâmetros"), mapa)
    destino.parent.mkdir(parents=True, exist_ok=True)
    livro.save(destino)
    return destino
