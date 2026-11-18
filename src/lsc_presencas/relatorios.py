"""Relatórios: mapa anual de férias, mapa anual de prevenção e dias por cliente e por viatura.

Sem interface. Cada relatório é uma tabela simples (`Relatorio`) que o ecrã mostra e que se
exporta para Excel tal como está.
"""

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from .mapa import MESES, nome_do_mes
from .modelos import Cliente, CodigoPresenca, Empresa, Marcacao, Trabalhador, Viatura

CODIGO_FERIAS = "FE"
MESES_CURTOS = [m[:3] for m in MESES]


@dataclass
class Relatorio:
    titulo: str
    subtitulo: str
    colunas: list[str]
    linhas: list[list] = field(default_factory=list)
    totais: list | None = None  # linha de totais (mesmo comprimento das colunas)
    nome_ficheiro: str = "relatorio"


def periodos(dias: list[date]) -> str:
    """Dias seguidos agrupados: «04/01–08/01, 15/01». Um fim de semana não quebra o período."""
    dias = sorted(set(dias))
    grupos: list[list[date]] = []
    for dia in dias:
        if grupos and _seguidos(grupos[-1][-1], dia):
            grupos[-1].append(dia)
        else:
            grupos.append([dia])
    return ", ".join(
        f"{g[0]:%d/%m}" if len(g) == 1 else f"{g[0]:%d/%m}–{g[-1]:%d/%m}" for g in grupos
    )


def _seguidos(anterior: date, seguinte: date) -> bool:
    if seguinte - anterior == timedelta(days=1):
        return True
    # sexta-feira seguida de segunda-feira
    return anterior.weekday() == 4 and seguinte - anterior == timedelta(days=3)


def _nome_empresa(sessao: Session, empresa_id: int | None) -> str:
    if empresa_id is None:
        return "Todas as empresas"
    return sessao.scalar(select(Empresa.nome).where(Empresa.id == empresa_id)) or "?"


def _marcacoes(sessao: Session, inicio: date, fim: date, empresa_id: int | None, *filtros):
    consulta = (
        select(Marcacao, Trabalhador, CodigoPresenca)
        .join(Trabalhador, Marcacao.trabalhador_id == Trabalhador.id)
        .join(CodigoPresenca, Marcacao.codigo_id == CodigoPresenca.id)
        .where(Marcacao.data.between(inicio, fim), *filtros)
    )
    if empresa_id is not None:
        consulta = consulta.where(Trabalhador.empresa_id == empresa_id)
    return sessao.execute(consulta).all()


# --- Mapas anuais por trabalhador -------------------------------------------------------------


def _mapa_anual(
    sessao: Session,
    ano: int,
    empresa_id: int | None,
    filtro,
    titulo: str,
    nome_ficheiro: str,
    *,
    todos_os_ativos: bool,
) -> Relatorio:
    por_trabalhador: dict[int, list[date]] = defaultdict(list)
    for marcacao, _t, _c in _marcacoes(
        sessao, date(ano, 1, 1), date(ano, 12, 31), empresa_id, filtro
    ):
        por_trabalhador[marcacao.trabalhador_id].append(marcacao.data)

    consulta = select(Trabalhador).order_by(Trabalhador.nome)
    if empresa_id is not None:
        consulta = consulta.where(Trabalhador.empresa_id == empresa_id)
    relatorio = Relatorio(
        titulo=f"{titulo} — {ano}",
        subtitulo=_nome_empresa(sessao, empresa_id),
        colunas=["Nº", "Nome", "Empresa", *[m.capitalize() for m in MESES_CURTOS], "Total", "Dias"],
        nome_ficheiro=f"{ano}_{nome_ficheiro}",
    )
    totais = [0] * 13
    for t in sessao.scalars(consulta):
        dias = por_trabalhador.get(t.id, [])
        if not dias and not (todos_os_ativos and t.ativo):
            continue
        por_mes = [sum(1 for d in dias if d.month == m) for m in range(1, 13)]
        for n, valor in enumerate([*por_mes, len(dias)]):
            totais[n] += valor
        relatorio.linhas.append(
            [
                t.numero,
                t.nome,
                t.empresa.nome if t.empresa else "",
                *[v or None for v in por_mes],
                len(dias),
                periodos(dias),
            ]
        )
    relatorio.totais = [None, "TOTAL", None, *totais, None]
    return relatorio


def ferias_anual(sessao: Session, ano: int, empresa_id: int | None = None) -> Relatorio:
    """Dias de férias (código FE) por trabalhador e por mês, com os períodos."""
    return _mapa_anual(
        sessao,
        ano,
        empresa_id,
        CodigoPresenca.codigo == CODIGO_FERIAS,
        "Mapa anual de férias",
        "ferias",
        todos_os_ativos=True,
    )


def prevencao_anual(sessao: Session, ano: int, empresa_id: int | None = None) -> Relatorio:
    """Dias de prevenção (códigos que somam prevenção) por trabalhador e por mês."""
    return _mapa_anual(
        sessao,
        ano,
        empresa_id,
        CodigoPresenca.soma_prevencao,
        "Mapa de prevenção",
        "prevencao",
        todos_os_ativos=False,
    )


# --- Dias por cliente e por viatura no mês ----------------------------------------------------


def _dias_por(
    sessao: Session, ano: int, mes: int, empresa_id: int | None, *, por_viatura: bool
) -> Relatorio:
    inicio, fim = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    classe, campo = (Viatura, "viatura_id") if por_viatura else (Cliente, "cliente_id")
    nomes = dict(sessao.execute(select(classe.id, classe.codigo)).all())
    codigos = [
        c
        for (c,) in sessao.execute(
            select(CodigoPresenca.codigo)
            .where(CodigoPresenca.conta_trabalhado)
            .order_by(CodigoPresenca.ordem, CodigoPresenca.codigo)
        )
    ]

    pessoas: dict[int | None, set[int]] = defaultdict(set)
    datas: dict[int | None, set[date]] = defaultdict(set)
    por_codigo: dict[int | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    horas: dict[int | None, object] = defaultdict(int)
    for marcacao, _t, codigo in _marcacoes(
        sessao, inicio, fim, empresa_id, CodigoPresenca.conta_trabalhado
    ):
        chave = getattr(marcacao, campo)
        pessoas[chave].add(marcacao.trabalhador_id)
        datas[chave].add(marcacao.data)
        por_codigo[chave][codigo.codigo] += 1
        horas[chave] += marcacao.horas_extra or 0

    oque = "viatura" if por_viatura else "cliente"
    relatorio = Relatorio(
        titulo=f"Dias trabalhados por {oque} — {nome_do_mes(ano, mes)}",
        subtitulo=_nome_empresa(sessao, empresa_id),
        colunas=[
            oque.capitalize(),
            "Trabalhadores",
            "Dias de trabalho (pessoa × dia)",
            *[f"Dias {c}" for c in codigos],
            "Dias com atividade",
            "Horas extra",
        ],
        nome_ficheiro=f"{ano}-{mes:02d}_dias_por_{oque}",
    )
    for chave in sorted(pessoas, key=lambda k: (k is None, nomes.get(k, ""))):
        relatorio.linhas.append(
            [
                nomes.get(chave, f"(sem {oque})"),
                len(pessoas[chave]),
                sum(por_codigo[chave].values()),
                *[por_codigo[chave].get(c) for c in codigos],
                len(datas[chave]),
                horas[chave] or None,
            ]
        )
    n = len(codigos)
    relatorio.totais = [
        "TOTAL",
        len(set().union(*pessoas.values())) if pessoas else 0,
        sum(linha[2] for linha in relatorio.linhas),
        *[sum(linha[3 + i] or 0 for linha in relatorio.linhas) for i in range(n)],
        None,
        sum((linha[4 + n] or 0 for linha in relatorio.linhas), 0) or None,
    ]
    return relatorio


def dias_por_cliente(
    sessao: Session, ano: int, mes: int, empresa_id: int | None = None
) -> Relatorio:
    """Dias trabalhados por cliente no mês (pelo cliente de cada marcação)."""
    return _dias_por(sessao, ano, mes, empresa_id, por_viatura=False)


def dias_por_viatura(
    sessao: Session, ano: int, mes: int, empresa_id: int | None = None
) -> Relatorio:
    """Dias trabalhados por viatura no mês; «dias com atividade» = dias em que a viatura saiu."""
    return _dias_por(sessao, ano, mes, empresa_id, por_viatura=True)


# --- Excel ------------------------------------------------------------------------------------


def para_excel(relatorio: Relatorio, destino: Path) -> Path:
    livro = Workbook()
    folha = livro.active
    folha.title = "Relatório"
    folha["A1"] = relatorio.titulo
    folha["A1"].font = Font(bold=True, size=13)
    folha["A2"] = relatorio.subtitulo
    negrito = Font(bold=True)
    for n, titulo in enumerate(relatorio.colunas, start=1):
        celula = folha.cell(4, n, titulo)
        celula.font = negrito
        celula.fill = PatternFill("solid", fgColor="DDE6F0")
        celula.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
    linhas = list(relatorio.linhas)
    if relatorio.totais:
        linhas.append(relatorio.totais)
    for numero, linha in enumerate(linhas, start=5):
        for n, valor in enumerate(linha, start=1):
            if valor is None or valor == "":
                continue
            celula = folha.cell(numero, n, valor)
            if relatorio.totais and linha is relatorio.totais:
                celula.font = negrito
    for n, titulo in enumerate(relatorio.colunas, start=1):
        maior = max([len(titulo), *(len(str(x[n - 1] or "")) for x in linhas)], default=8)
        folha.column_dimensions[get_column_letter(n)].width = min(max(maior + 2, 7), 60)
    folha.freeze_panes = "A5"
    destino.parent.mkdir(parents=True, exist_ok=True)
    livro.save(destino)
    return destino
