"""PDF do mapa de pré-processamento: um por trabalhador e um conjunto por empresa."""

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table

from . import calculo
from .exportar_excel import AVISO, estado_do_mapa
from .mapa import MapaMes, MapaTrabalhador
from .presencas import texto_celula

TITULO_TOTAL = "Total ilíquido estimado (antes de IRS e TSU)"
DIAS_SEMANA = ["2.ª", "3.ª", "4.ª", "5.ª", "6.ª", "sáb", "dom"]

CINZA = colors.HexColor("#E6E6E6")
CINZA_CLARO = colors.HexColor("#F3F3F3")
AZUL = colors.HexColor("#DDE6F0")
LARGURA = A4[0] - 30 * mm

_base = getSampleStyleSheet()
NORMAL = ParagraphStyle("normal", parent=_base["Normal"], fontSize=9, leading=11)
PEQUENO = ParagraphStyle("pequeno", parent=NORMAL, fontSize=7, leading=8.5, textColor=colors.grey)
DIREITA = ParagraphStyle("direita", parent=NORMAL, alignment=TA_RIGHT)
TITULO = ParagraphStyle("titulo", parent=NORMAL, fontSize=13, leading=16, fontName="Helvetica-Bold")
SUBTITULO = ParagraphStyle("subtitulo", parent=NORMAL, fontSize=10, fontName="Helvetica-Bold")
PROVISORIO = ParagraphStyle(
    "provisorio", parent=NORMAL, fontName="Helvetica-Bold", textColor=colors.HexColor("#B00020")
)
CELULA_DIA = ParagraphStyle("dia", parent=NORMAL, fontSize=8, leading=10, alignment=1)


def euros(valor: Decimal | None) -> str:
    """«1.234,56 €»; vazio se não houver valor."""
    if valor is None:
        return ""
    texto = f"{calculo.arredondar(Decimal(valor)):,.2f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".") + " €"


def numero(valor: Decimal | None) -> str:
    if valor is None:
        return ""
    texto = f"{Decimal(valor):f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _p(texto: str | None, estilo=NORMAL) -> Paragraph:
    return Paragraph(escape(texto or ""), estilo)


def _cabecalho(mapa: MapaMes) -> Table:
    empresa = [_p(mapa.empresa, TITULO)]
    if mapa.nipc:
        empresa.append(_p(f"NIPC {mapa.nipc}"))
    if mapa.morada:
        empresa.append(_p(mapa.morada))
    direita = [
        _p(
            "Mapa de pré-processamento salarial",
            ParagraphStyle("t", parent=DIREITA, fontSize=11, leading=14),
        ),
        _p(mapa.titulo_mes.capitalize(), DIREITA),
    ]
    colunas, larguras = [empresa, direita], [LARGURA * 0.6, LARGURA * 0.4]
    if mapa.logotipo and Path(mapa.logotipo).is_file():
        try:
            logotipo = Image(mapa.logotipo)
            escala = min(28 * mm / logotipo.imageWidth, 16 * mm / logotipo.imageHeight)
            logotipo.drawWidth = logotipo.imageWidth * escala
            logotipo.drawHeight = logotipo.imageHeight * escala
            colunas.insert(0, logotipo)
            larguras = [32 * mm, LARGURA * 0.6 - 32 * mm, LARGURA * 0.4]
        except Exception:  # noqa: BLE001 - um logótipo ilegível não impede o PDF
            pass
    tabela = Table([colunas], colWidths=larguras)
    tabela.setStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.8, colors.black),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
    )
    return tabela


def _calendario(mapa: MapaMes, t: MapaTrabalhador) -> Table:
    feriados = {d for d, _ in mapa.feriados}
    por_dia = {d.data: texto_celula(d.codigo, d.horas_extra) for d in t.dias}
    linhas = [[_p(nome, CELULA_DIA) for nome in DIAS_SEMANA]]
    estilos = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    semana = [""] * 7
    for n in range(1, monthrange(mapa.ano, mapa.mes)[1] + 1):
        dia = date(mapa.ano, mapa.mes, n)
        coluna = dia.weekday()
        codigo = escape(por_dia.get(dia, ""))
        semana[coluna] = Paragraph(
            f'<font size="6" color="grey">{n}</font><br/><b>{codigo or "&nbsp;"}</b>', CELULA_DIA
        )
        if coluna >= 5 or dia in feriados:
            estilos.append(("BACKGROUND", (coluna, len(linhas)), (coluna, len(linhas)), CINZA))
        if coluna == 6:
            linhas.append(semana)
            semana = [""] * 7
    if any(semana):
        linhas.append(semana)
    tabela = Table(linhas, colWidths=[LARGURA / 7] * 7)
    tabela.setStyle(estilos)
    return tabela


def _rubricas(t: MapaTrabalhador) -> Table:
    cab = ["Rubrica", "Quantidade", "Valor unitário", "Total", "Isento", "Sujeito"]
    linhas = [[_p(c, SUBTITULO if n == 0 else DIREITA) for n, c in enumerate(cab)]]
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    def linha(r: calculo.Rubrica) -> list:
        descricao = f"{escape(r.descricao)}<br/>" + (
            f'<font size="7" color="grey">{escape(r.formula)}</font>'
        )
        total = euros(r.total) if r.total is not None else "por calcular"
        return [
            Paragraph(descricao, NORMAL),
            _p(numero(r.quantidade), DIREITA),
            _p(euros(r.valor_unitario), DIREITA),
            _p(total, DIREITA),
            _p(euros(r.isento), DIREITA),
            _p(euros(r.sujeito), DIREITA),
        ]

    normais = [r for r in t.resultado.rubricas if r.chave != calculo.LANCAMENTO]
    manuais = [r for r in t.resultado.rubricas if r.chave == calculo.LANCAMENTO]
    linhas += [linha(r) for r in normais]
    if manuais:
        estilos.append(("BACKGROUND", (0, len(linhas)), (-1, len(linhas)), CINZA_CLARO))
        estilos.append(("SPAN", (0, len(linhas)), (-1, len(linhas))))
        linhas.append([_p("Lançamentos manuais", SUBTITULO), "", "", "", "", ""])
        linhas += [linha(r) for r in manuais]
    estilos += [
        ("LINEABOVE", (0, len(linhas)), (-1, len(linhas)), 0.8, colors.black),
        ("SPAN", (0, len(linhas)), (2, len(linhas))),
        ("BACKGROUND", (0, len(linhas)), (-1, len(linhas)), AZUL),
    ]
    negrito_direita = ParagraphStyle("nd", parent=DIREITA, fontName="Helvetica-Bold", fontSize=10)
    linhas.append(
        [_p(TITULO_TOTAL, SUBTITULO), "", "", _p(euros(t.total), negrito_direita), "", ""]
    )
    tabela = Table(
        linhas,
        colWidths=[LARGURA - 5 * 23 * mm - 2 * mm] + [21 * mm, 25 * mm, 25 * mm, 23 * mm, 23 * mm],
        repeatRows=1,
    )
    tabela.setStyle(estilos)
    return tabela


def _pagina_do_trabalhador(mapa: MapaMes, t: MapaTrabalhador) -> list:
    r = t.resultado
    contagens = " · ".join(
        f"{codigo}: {r.contagens[codigo]}" for codigo, _ in mapa.codigos if r.contagens.get(codigo)
    )
    outros = [c for c in r.contagens if c not in {codigo for codigo, _ in mapa.codigos}]
    contagens = " · ".join([contagens, *(f"{c}: {r.contagens[c]}" for c in outros)]).strip(" ·")

    historia = [_cabecalho(mapa), Spacer(1, 4 * mm)]
    if not mapa.fechado:
        historia += [_p(estado_do_mapa(mapa), PROVISORIO), Spacer(1, 2 * mm)]
    dados = Table(
        [
            [
                _p(f"N.º {t.numero} — {t.nome}", SUBTITULO),
                _p(f"Cliente: {t.cliente or '—'} · Zona: {t.zona or '—'}", DIREITA),
            ],
            [
                _p(f"Dias de contrato no mês: {r.dias_contrato}"),
                _p(f"Dias por código: {contagens or '—'}", DIREITA),
            ],
        ],
        colWidths=[LARGURA * 0.5, LARGURA * 0.5],
    )
    historia += [dados, Spacer(1, 3 * mm), _calendario(mapa, t), Spacer(1, 4 * mm), _rubricas(t)]
    if r.incompleto:
        historia += [
            Spacer(1, 2 * mm),
            _p(
                "Há rubricas por calcular (faltam valores nos parâmetros ou na ficha): o total "
                "não as inclui.",
                PROVISORIO,
            ),
        ]
    historia += [
        Spacer(1, 3 * mm),
        _p(
            "Os valores são estimados e ilíquidos: não incluem a retenção de IRS nem a "
            "Segurança Social. O recibo de vencimento é emitido pelo contabilista.",
            PEQUENO,
        ),
        Spacer(1, 16 * mm),
        Table(
            [
                [
                    _p("Tomei conhecimento (assinatura do trabalhador):"),
                    "",
                    _p("Data: ____ / ____ / ________", DIREITA),
                ]
            ],
            colWidths=[LARGURA * 0.38, LARGURA * 0.34, LARGURA * 0.28],
            style=[("LINEBELOW", (1, 0), (1, 0), 0.6, colors.black)],
        ),
    ]
    return historia


def gerar_pdf(mapa: MapaMes, trabalhadores: list[MapaTrabalhador], destino: Path) -> Path:
    """Um PDF com uma ou mais folhas (uma por trabalhador)."""
    emitido = datetime.now().strftime("%d/%m/%Y %H:%M")

    def rodape(tela, documento) -> None:
        tela.saveState()
        tela.setFont("Helvetica-Bold", 8)
        tela.drawString(15 * mm, 11 * mm, AVISO)
        tela.setFont("Helvetica", 7)
        tela.drawString(15 * mm, 7.5 * mm, f"{mapa.empresa} · {mapa.titulo_mes}")
        tela.drawRightString(
            A4[0] - 15 * mm, 7.5 * mm, f"Emitido em {emitido} · pág. {documento.page}"
        )
        tela.restoreState()

    historia: list = []
    for n, t in enumerate(trabalhadores):
        if n:
            historia.append(PageBreak())
        historia += _pagina_do_trabalhador(mapa, t)

    destino.parent.mkdir(parents=True, exist_ok=True)
    documento = SimpleDocTemplate(
        str(destino),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"Mapa de pré-processamento — {mapa.empresa} — {mapa.titulo_mes}",
        author=mapa.empresa,
    )
    documento.build(historia, onFirstPage=rodape, onLaterPages=rodape)
    return destino
