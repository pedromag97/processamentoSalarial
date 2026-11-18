"""Lançamentos manuais: auditoria e bloqueio dos meses fechados.

`registar` é chamado pela tabela do ecrã antes de gravar cada alteração (criar, alterar ou
apagar). Levanta ValueError para recusar; quem chama desfaz a transação.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import bloqueios, concorrencia
from .modelos import Auditoria, LancamentoManual, Trabalhador
from .presencas import meses_fechados, utilizador_atual

CAMPOS = ("trabalhador_id", "ano", "mes", "tipo", "descricao", "valor")


def _descrever(sessao: Session, valores: dict) -> str:
    numero = sessao.scalar(
        select(Trabalhador.numero).where(Trabalhador.id == valores["trabalhador_id"])
    )
    return json.dumps(
        {
            "trabalhador": numero,
            "mes": f"{valores['ano']}-{valores['mes']:02d}",
            "tipo": valores["tipo"],
            "descricao": valores["descricao"],
            "valor": str(valores["valor"]),
        },
        ensure_ascii=False,
    )


def _recusar_se_fechado(sessao: Session, valores: dict) -> None:
    concorrencia.alterar_marcacoes(sessao)  # espera por um fecho que esteja a decorrer
    bloqueios.exigir_livres(sessao, [valores["trabalhador_id"]])
    empresa_id = sessao.scalar(
        select(Trabalhador.empresa_id).where(Trabalhador.id == valores["trabalhador_id"])
    )
    if (empresa_id, valores["ano"], valores["mes"]) in meses_fechados(sessao):
        raise ValueError(
            f"O mês {valores['mes']:02d}/{valores['ano']} está fechado para a empresa deste "
            "trabalhador. Reabra o mês para alterar os lançamentos."
        )


def registar(
    sessao: Session, lancamento: LancamentoManual, acao: str, utilizador: str | None = None
) -> None:
    """Valida e regista na auditoria uma alteração a um lançamento (antes do commit).

    `acao` é «criar», «alterar» ou «apagar».
    """
    with sessao.no_autoflush:
        novo = {campo: getattr(lancamento, campo) for campo in CAMPOS}
        antigo = None
        if acao != "criar":
            # O que está gravado (a alteração ainda não foi enviada para a base de dados).
            linha = sessao.execute(
                select(*(getattr(LancamentoManual, c) for c in CAMPOS)).where(
                    LancamentoManual.id == lancamento.id
                )
            ).first()
            antigo = dict(zip(CAMPOS, linha, strict=True)) if linha else None

        if antigo is not None:
            _recusar_se_fechado(sessao, antigo)
        if acao != "apagar":
            _recusar_se_fechado(sessao, novo)
        if acao == "alterar" and antigo == novo:
            return

        sessao.add(
            Auditoria(
                utilizador=utilizador or utilizador_atual(),
                entidade="lancamento_manual",
                entidade_id=lancamento.id,
                acao=acao,
                valor_antigo=_descrever(sessao, antigo) if antigo else None,
                valor_novo=_descrever(sessao, novo) if acao != "apagar" else None,
            )
        )
