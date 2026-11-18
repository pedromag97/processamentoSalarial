"""Registo e consulta da auditoria (quem alterou o quê, quando, valor antigo e novo)."""

import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos import Auditoria
from .presencas import utilizador_atual

NOMES_ENTIDADE = {
    "marcacao": "Marcação",
    "lancamento_manual": "Lançamento manual",
    "fecho_mes": "Fecho do mês",
    "trabalhador": "Ficha do trabalhador",
    "salario_base": "Salário base",
    "conta": "Conta de login",
}
NOMES_ACAO = {
    "criar": "Criou",
    "alterar": "Alterou",
    "apagar": "Apagou",
    "fechar": "Fechou",
    "reabrir": "Reabriu",
}


@dataclass(frozen=True)
class Registo:
    quando: datetime
    utilizador: str
    entidade: str
    acao: str
    antes: str
    depois: str
    motivo: str


def _json(valores: dict | None) -> str | None:
    if valores is None:
        return None
    return json.dumps(
        {
            k: (v.isoformat() if isinstance(v, date | datetime) else v if _simples(v) else str(v))
            for k, v in valores.items()
        },
        ensure_ascii=False,
    )


def _simples(valor) -> bool:
    return valor is None or isinstance(valor, bool | int | str)


def registar(
    sessao: Session,
    entidade: str,
    entidade_id: int | None,
    acao: str,
    antigo: dict | None = None,
    novo: dict | None = None,
    motivo: str | None = None,
    utilizador: str | None = None,
) -> None:
    """Acrescenta um registo de auditoria à sessão (quem chama faz o commit)."""
    sessao.add(
        Auditoria(
            utilizador=utilizador or utilizador_atual(),
            entidade=entidade,
            entidade_id=entidade_id,
            acao=acao,
            valor_antigo=_json(antigo),
            valor_novo=_json(novo),
            motivo=motivo,
        )
    )


def _dados(texto: str | None) -> dict:
    if not texto:
        return {}
    try:
        dados = json.loads(texto)
    except ValueError:
        return {"valor": texto}
    return dados if isinstance(dados, dict) else {"valor": dados}


def descrever(texto: str | None) -> str:
    """O JSON guardado, em texto legível: «trabalhador: 3 · data: 2027-01-05 · código: PF»."""
    partes = []
    for chave, valor in _dados(texto).items():
        if valor is None or valor == "":
            valor = "(vazio)"
        elif valor is True:
            valor = "sim"
        elif valor is False:
            valor = "não"
        partes.append(f"{chave.replace('_', ' ')}: {valor}")
    return " · ".join(partes)


def listar(
    sessao: Session,
    *,
    entidade: str | None = None,
    texto: str = "",
    numero_trabalhador: int | None = None,
    limite: int = 500,
) -> list[Registo]:
    """Registos de auditoria, do mais recente para o mais antigo.

    `numero_trabalhador` filtra pelo nº interno guardado no registo (histórico da ficha).
    """
    consulta = select(Auditoria).order_by(Auditoria.quando.desc(), Auditoria.id.desc())
    if entidade:
        consulta = consulta.where(Auditoria.entidade == entidade)
    procurado = texto.strip().casefold()
    registos: list[Registo] = []
    for a in sessao.scalars(consulta):
        if numero_trabalhador is not None and numero_trabalhador not in (
            _dados(a.valor_antigo).get("trabalhador"),
            _dados(a.valor_novo).get("trabalhador"),
        ):
            continue
        registo = Registo(
            quando=a.quando,
            utilizador=a.utilizador,
            entidade=NOMES_ENTIDADE.get(a.entidade, a.entidade),
            acao=NOMES_ACAO.get(a.acao, a.acao),
            antes=descrever(a.valor_antigo),
            depois=descrever(a.valor_novo),
            motivo=a.motivo or "",
        )
        if (
            procurado
            and procurado
            not in " ".join(
                (registo.utilizador, registo.entidade, registo.acao, registo.antes, registo.depois)
                + (registo.motivo,)
            ).casefold()
        ):
            continue
        registos.append(registo)
        if len(registos) >= limite:
            break
    return registos
