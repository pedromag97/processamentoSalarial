"""Marcações de presença: ler, interpretar o que se escreve numa célula e gravar com auditoria.

Sem interface. A grelha (ui/grelha.py) só usa as funções daqui para alterar marcações, para que
o bloqueio de meses fechados e o registo de auditoria nunca sejam contornados.
"""

import getpass
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos import (
    FECHO_FECHADO,
    Auditoria,
    CodigoPresenca,
    FechoMes,
    Marcacao,
    Trabalhador,
)
from .ui.formatos import ler_decimal, texto_decimal

MAX_HORAS_EXTRA = Decimal("24")

# Estado de uma célula: None (sem marcação) ou (id do código, horas extra).
Estado = tuple[int, Decimal] | None


@dataclass(frozen=True)
class Celula:
    codigo_id: int
    horas_extra: Decimal
    cliente_id: int | None


@dataclass(frozen=True)
class Alteracao:
    trabalhador_id: int
    data: date
    estado: Estado


class MesFechado(Exception):
    """Tentativa de alterar marcações de um mês fechado."""


def utilizador_atual() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - sem utilizador do sistema, regista-se na mesma
        return "desconhecido"


def semana_de(dia: date) -> tuple[date, date]:
    """Segunda-feira e domingo da semana de um dia."""
    segunda = dia - timedelta(days=dia.weekday())
    return segunda, segunda + timedelta(days=6)


# --- Texto das células ------------------------------------------------------------------------


def texto_celula(codigo: str, horas_extra: Decimal) -> str:
    """«PF» ou «PF+1,5»."""
    return f"{codigo}+{texto_decimal(horas_extra.normalize())}" if horas_extra else codigo


def interpretar_celula(texto: str, codigos: dict[str, int]) -> Estado:
    """Converte «P», «pf+2» ou «PF+1,5» em (id do código, horas). Texto vazio = sem marcação.

    `codigos` é o dicionário {CÓDIGO EM MAIÚSCULAS: id} dos códigos ativos.
    """
    limpo = (texto or "").strip()
    if not limpo:
        return None
    nome, _, horas_texto = limpo.partition("+")
    nome = nome.strip().upper()
    if nome not in codigos:
        raise ValueError(f"«{nome}» não é um código de presença.")
    horas = Decimal("0")
    if horas_texto.strip():
        horas = ler_decimal(horas_texto)
        if horas < 0 or horas > MAX_HORAS_EXTRA:
            raise ValueError(f"Horas extra inválidas em «{limpo}».")
    elif "+" in limpo:
        raise ValueError(f"Faltam as horas extra em «{limpo}».")
    return codigos[nome], horas


def codigos_ativos(sessao: Session) -> dict[str, int]:
    return {
        codigo.upper(): id_
        for id_, codigo in sessao.execute(
            select(CodigoPresenca.id, CodigoPresenca.codigo).where(CodigoPresenca.ativo)
        )
    }


# --- Leitura ----------------------------------------------------------------------------------


def carregar_marcacoes(sessao: Session, inicio: date, fim: date) -> dict[tuple[int, date], Celula]:
    """Todas as marcações do período, por (id do trabalhador, dia)."""
    linhas = sessao.execute(
        select(
            Marcacao.trabalhador_id,
            Marcacao.data,
            Marcacao.codigo_id,
            Marcacao.horas_extra,
            Marcacao.cliente_id,
        ).where(Marcacao.data.between(inicio, fim))
    )
    return {(t, d): Celula(c, h, cli) for t, d, c, h, cli in linhas}


def meses_fechados(sessao: Session) -> set[tuple[int, int, int]]:
    """Conjunto de (id da empresa, ano, mês) fechados."""
    return {
        (empresa_id, ano, mes)
        for empresa_id, ano, mes in sessao.execute(
            select(FechoMes.empresa_id, FechoMes.ano, FechoMes.mes).where(
                FechoMes.estado == FECHO_FECHADO
            )
        )
    }


# --- Escrita ----------------------------------------------------------------------------------


def _descrever(numero: int, dia: date, codigo: str | None, horas: Decimal | None) -> str | None:
    if codigo is None:
        return None
    return json.dumps(
        {
            "trabalhador": numero,
            "data": dia.isoformat(),
            "codigo": codigo,
            "horas_extra": str(horas),
        },
        ensure_ascii=False,
    )


def aplicar_alteracoes(
    sessao: Session, alteracoes: Iterable[Alteracao], utilizador: str | None = None
) -> list[Alteracao]:
    """Grava um conjunto de alterações de uma vez (tudo ou nada) e regista-as na auditoria.

    Devolve o estado anterior das células que mudaram de facto, para se poder desfazer.
    Levanta `MesFechado` (sem gravar nada) se alguma célula for de um mês fechado.
    """
    pedidas = {(a.trabalhador_id, a.data): a.estado for a in alteracoes}
    if not pedidas:
        return []
    utilizador = utilizador or utilizador_atual()
    try:
        ids = {t for t, _ in pedidas}
        trabalhadores = {
            t.id: t for t in sessao.scalars(select(Trabalhador).where(Trabalhador.id.in_(ids)))
        }
        fechados = meses_fechados(sessao)
        for tid, dia in pedidas:
            if (trabalhadores[tid].empresa_id, dia.year, dia.month) in fechados:
                raise MesFechado(
                    f"O mês {dia.month:02d}/{dia.year} está fechado para a empresa de "
                    f"{trabalhadores[tid].nome}. Reabra o mês para o alterar."
                )

        datas = [d for _, d in pedidas]
        existentes = {
            (m.trabalhador_id, m.data): m
            for m in sessao.scalars(
                select(Marcacao).where(
                    Marcacao.trabalhador_id.in_(ids),
                    Marcacao.data.between(min(datas), max(datas)),
                )
            )
        }
        nomes = {
            id_: codigo
            for id_, codigo in sessao.execute(select(CodigoPresenca.id, CodigoPresenca.codigo))
        }

        anteriores: list[Alteracao] = []
        for (tid, dia), estado in pedidas.items():
            marcacao = existentes.get((tid, dia))
            antes: Estado = (marcacao.codigo_id, marcacao.horas_extra) if marcacao else None
            if antes == estado:
                continue
            trabalhador = trabalhadores[tid]
            antigo = _descrever(trabalhador.numero, dia, *(_nome(nomes, antes)))
            novo = _descrever(trabalhador.numero, dia, *(_nome(nomes, estado)))
            if estado is None:
                sessao.delete(marcacao)
                acao = "apagar"
            elif marcacao is None:
                marcacao = Marcacao(
                    trabalhador_id=tid,
                    data=dia,
                    codigo_id=estado[0],
                    horas_extra=estado[1],
                    cliente_id=trabalhador.cliente_id,
                    viatura_id=trabalhador.viatura_id,
                    zona_id=trabalhador.zona_id,
                )
                sessao.add(marcacao)
                acao = "criar"
            else:
                marcacao.codigo_id, marcacao.horas_extra = estado
                acao = "alterar"
            sessao.flush()
            sessao.add(
                Auditoria(
                    utilizador=utilizador,
                    entidade="marcacao",
                    entidade_id=marcacao.id,
                    acao=acao,
                    valor_antigo=antigo,
                    valor_novo=novo,
                )
            )
            anteriores.append(Alteracao(tid, dia, antes))
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    return anteriores


def _nome(nomes: dict[int, str], estado: Estado) -> tuple[str | None, Decimal | None]:
    return (None, None) if estado is None else (nomes[estado[0]], estado[1])


def alteracoes_copiar_semana(
    sessao: Session, trabalhador_ids: Iterable[int], dia_destino: date
) -> list[Alteracao]:
    """Alterações que copiam a semana anterior para a semana de `dia_destino`.

    Só copia os dias que têm marcação na semana anterior; os outros ficam como estão.
    """
    segunda, _ = semana_de(dia_destino)
    origem_inicio = segunda - timedelta(days=7)
    linhas = sessao.execute(
        select(
            Marcacao.trabalhador_id, Marcacao.data, Marcacao.codigo_id, Marcacao.horas_extra
        ).where(
            Marcacao.trabalhador_id.in_(set(trabalhador_ids)),
            Marcacao.data.between(origem_inicio, segunda - timedelta(days=1)),
        )
    )
    return [Alteracao(t, d + timedelta(days=7), (c, h)) for t, d, c, h in linhas]
