"""Dados base carregados em qualquer instalação: códigos de presença e feriados nacionais.

O carregamento é idempotente: só acrescenta o que falta e nunca altera o que o utilizador editou.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos import (
    AJUDA_CUSTO_NAO,
    AJUDA_CUSTO_SIM,
    AJUDA_CUSTO_ZONA,
    FERIADO_NACIONAL,
    PAIS_PORTUGAL,
    CodigoPresenca,
    Feriado,
)

# (código, descrição, cor, trabalhado, subsídio alimentação, ajuda custo França,
#  desconta salário, soma prevenção)
# PF não acumula subsídio de alimentação por defeito e FJ não desconta por defeito:
# ambos são atributos editáveis, a confirmar com o contabilista.
CODIGOS_BASE = [
    ("P", "Presente em Portugal", "#C6EFCE", True, True, AJUDA_CUSTO_NAO, False, False),
    ("PF", "Presente em França", "#BDD7EE", True, False, AJUDA_CUSTO_SIM, False, False),
    (
        "DF",
        "Deslocado em França sem trabalhar",
        "#DDEBF7",
        False,
        False,
        AJUDA_CUSTO_SIM,
        False,
        False,
    ),
    ("FE", "Férias", "#FFF2CC", False, False, AJUDA_CUSTO_NAO, False, False),
    ("FER", "Feriado", "#E2E2E2", False, False, AJUDA_CUSTO_NAO, False, False),
    ("FJ", "Falta justificada", "#FCE4D6", False, False, AJUDA_CUSTO_NAO, False, False),
    ("FI", "Falta injustificada", "#F8CBAD", False, False, AJUDA_CUSTO_NAO, True, False),
    ("B", "Baixa por doença", "#E4DFEC", False, False, AJUDA_CUSTO_NAO, True, False),
    ("AT", "Acidente de trabalho", "#D9B3FF", False, False, AJUDA_CUSTO_NAO, True, False),
    ("PR", "Prevenção", "#FFD966", True, True, AJUDA_CUSTO_ZONA, False, True),
]

# Como cada código base conta na folha de salário (os que não estão aqui não contam).
# FJ (falta justificada) e DF ficam de fora por omissão: muda-se na tabela de códigos.
FOLHA_POR_CODIGO = {
    "P": "trabalho",
    "PF": "trabalho",
    "PR": "trabalho",
    "FE": "ferias",
    "FI": "falta",
    "B": "baixa",
    "AT": "baixa",
}

ANOS_FERIADOS = (2026, 2027)


def domingo_de_pascoa(ano: int) -> date:
    """Data da Páscoa (algoritmo gregoriano anónimo)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_nacionais(ano: int) -> list[tuple[date, str]]:
    """Feriados nacionais obrigatórios de Portugal para um ano."""
    pascoa = domingo_de_pascoa(ano)
    return sorted(
        [
            (date(ano, 1, 1), "Ano Novo"),
            (pascoa - timedelta(days=2), "Sexta-feira Santa"),
            (pascoa, "Domingo de Páscoa"),
            (date(ano, 4, 25), "Dia da Liberdade"),
            (date(ano, 5, 1), "Dia do Trabalhador"),
            (pascoa + timedelta(days=60), "Corpo de Deus"),
            (date(ano, 6, 10), "Dia de Portugal"),
            (date(ano, 8, 15), "Assunção de Nossa Senhora"),
            (date(ano, 10, 5), "Implantação da República"),
            (date(ano, 11, 1), "Todos os Santos"),
            (date(ano, 12, 1), "Restauração da Independência"),
            (date(ano, 12, 8), "Imaculada Conceição"),
            (date(ano, 12, 25), "Natal"),
        ]
    )


def carregar_dados_base(sessao: Session, anos=ANOS_FERIADOS) -> None:
    existentes = set(sessao.scalars(select(CodigoPresenca.codigo)))
    for ordem, (codigo, descricao, cor, trab, sub, ajuda, desconta, prev) in enumerate(
        CODIGOS_BASE, start=1
    ):
        if codigo not in existentes:
            sessao.add(
                CodigoPresenca(
                    codigo=codigo,
                    descricao=descricao,
                    cor=cor,
                    ordem=ordem,
                    conta_trabalhado=trab,
                    subsidio_alimentacao=sub,
                    ajuda_custo_franca=ajuda,
                    desconta_salario=desconta,
                    soma_prevencao=prev,
                    conta_folha=FOLHA_POR_CODIGO.get(codigo, ""),
                )
            )

    datas = set(sessao.scalars(select(Feriado.data).where(Feriado.pais == PAIS_PORTUGAL)))
    for ano in anos:
        for dia, nome in feriados_nacionais(ano):
            if dia not in datas:
                sessao.add(Feriado(data=dia, nome=nome, tipo=FERIADO_NACIONAL, pais=PAIS_PORTUGAL))
    sessao.flush()
