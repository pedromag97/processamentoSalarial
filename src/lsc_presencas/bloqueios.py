"""Cadeados: enquanto uma pessoa está a mexer num funcionário, os outros não o alteram.

Um funcionário fica com cadeado quando alguém tem a ficha dele aberta ou tem células dele
selecionadas na grelha de presenças. Os outros veem o cadeado e quem o tem, e as alterações
a esse funcionário são recusadas no próprio núcleo (marcações, lançamentos e ficha).

O cadeado é uma linha na tabela `bloqueio_trabalhador`. Cada programa aberto renova os seus
de 30 em 30 segundos; um cadeado sem renovação há 90 segundos considera-se abandonado (o
programa fechou mal ou a rede caiu) e deixa de contar. As horas são sempre as do servidor,
para não depender do relógio de cada PC.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import contas
from .modelos import BloqueioTrabalhador, Trabalhador
from .presencas import utilizador_atual

VALIDADE = timedelta(seconds=90)
INTERVALO_RENOVACAO_MS = 30_000

# Identifica este programa aberto (a mesma pessoa pode ter o programa aberto em dois PCs).
ID_PROGRAMA = uuid.uuid4().hex


class Bloqueado(ValueError):
    """O funcionário está a ser alterado por outra pessoa. Não foi gravado nada."""


@dataclass(frozen=True)
class Cadeado:
    trabalhador_id: int
    utilizador: str
    nome: str
    desde: datetime  # hora do servidor, em UTC

    @property
    def descricao(self) -> str:
        hora = self.desde.replace(tzinfo=UTC).astimezone().strftime("%H:%M")
        return f"Em uso por {self.nome} desde as {hora}"


def agora(sessao: Session) -> datetime:
    """A hora do servidor da base de dados, em UTC e sem fuso."""
    if sessao.get_bind().dialect.name == "postgresql":
        return sessao.scalar(text("SELECT now() AT TIME ZONE 'utc'"))
    return datetime.now(UTC).replace(tzinfo=None)


def _eu() -> tuple[str, str]:
    em_sessao = contas.atual()
    if em_sessao is not None:
        return em_sessao.nome_utilizador, em_sessao.nome
    nome = utilizador_atual()
    return nome, nome


def _gravar(sessao: Session) -> None:
    """Commit sem deitar fora o que a interface tem carregado (os cadeados mudam muitas
    vezes; não faz sentido reler as fichas todas de cada vez)."""
    expirar = sessao.expire_on_commit
    sessao.expire_on_commit = False
    try:
        sessao.commit()
    finally:
        sessao.expire_on_commit = expirar


def de_outros(
    sessao: Session, trabalhador_ids: Iterable[int] | None = None, programa: str = ID_PROGRAMA
) -> dict[int, Cadeado]:
    """Cadeados em vigor que pertencem a outras pessoas (ou a outro programa aberto)."""
    limite = agora(sessao) - VALIDADE
    consulta = select(BloqueioTrabalhador).where(
        BloqueioTrabalhador.programa != programa, BloqueioTrabalhador.renovado_em >= limite
    )
    if trabalhador_ids is not None:
        ids = set(trabalhador_ids)
        if not ids:
            return {}
        consulta = consulta.where(BloqueioTrabalhador.trabalhador_id.in_(ids))
    return {
        b.trabalhador_id: Cadeado(b.trabalhador_id, b.utilizador, b.nome, b.desde)
        for b in sessao.scalars(consulta.execution_options(populate_existing=True))
    }


def exigir_livres(sessao: Session, trabalhador_ids: Iterable[int]) -> None:
    """Levanta `Bloqueado` se algum destes funcionários tiver o cadeado de outra pessoa."""
    presos = de_outros(sessao, trabalhador_ids)
    if not presos:
        return
    nomes = dict(
        sessao.execute(
            select(Trabalhador.id, Trabalhador.nome).where(Trabalhador.id.in_(presos))
        ).all()
    )
    detalhe = "; ".join(
        f"{nomes.get(tid, '?')} ({c.nome})"
        for tid, c in sorted(presos.items(), key=lambda par: nomes.get(par[0], ""))[:5]
    )
    mais = f" e mais {len(presos) - 5}" if len(presos) > 5 else ""
    raise Bloqueado(
        f"{len(presos)} funcionário(s) estão a ser alterados por outra pessoa: {detalhe}{mais}. "
        "Não gravei nada."
    )


def definir(
    sessao: Session, trabalhador_ids: Iterable[int], programa: str = ID_PROGRAMA
) -> dict[int, Cadeado]:
    """Os cadeados deste programa passam a ser exatamente estes funcionários.

    Larga os que já não interessam, renova os que se mantêm e pede os novos. Devolve os que
    não foi possível obter, porque outra pessoa já os tem. Faz commit.
    """
    pedidos = set(trabalhador_ids)
    utilizador, nome = _eu()
    try:
        momento = agora(sessao)
        # Limpa os abandonados e os meus que já não interessam.
        sessao.execute(
            delete(BloqueioTrabalhador).where(BloqueioTrabalhador.renovado_em < momento - VALIDADE)
        )
        meus = delete(BloqueioTrabalhador).where(BloqueioTrabalhador.programa == programa)
        if pedidos:
            meus = meus.where(BloqueioTrabalhador.trabalhador_id.not_in(pedidos))
        sessao.execute(meus)
        if not pedidos:
            _gravar(sessao)
            return {}

        existentes = {
            b.trabalhador_id: b
            for b in sessao.scalars(
                select(BloqueioTrabalhador)
                .where(BloqueioTrabalhador.trabalhador_id.in_(pedidos))
                .execution_options(populate_existing=True)
            )
        }
        recusados = {
            tid: Cadeado(tid, b.utilizador, b.nome, b.desde)
            for tid, b in existentes.items()
            if b.programa != programa
        }
        sessao.execute(
            update(BloqueioTrabalhador)
            .where(BloqueioTrabalhador.programa == programa)
            .values(renovado_em=momento)
        )
        novos = sorted(pedidos - set(existentes))

        def linha(tid: int) -> dict:
            return {
                "trabalhador_id": tid,
                "utilizador": utilizador,
                "nome": nome,
                "programa": programa,
                "desde": momento,
                "renovado_em": momento,
            }

        try:
            if novos:  # todos de uma vez (selecionar a grelha inteira é uma só instrução)
                with sessao.begin_nested():
                    sessao.execute(insert(BloqueioTrabalhador), [linha(t) for t in novos])
        except IntegrityError:
            # Outra pessoa pediu algum destes neste instante: um a um, para ver quais.
            for tid in novos:
                try:
                    with sessao.begin_nested():
                        sessao.execute(insert(BloqueioTrabalhador), [linha(tid)])
                except IntegrityError:
                    b = sessao.scalars(
                        select(BloqueioTrabalhador).where(BloqueioTrabalhador.trabalhador_id == tid)
                    ).first()
                    if b is not None:
                        recusados[tid] = Cadeado(tid, b.utilizador, b.nome, b.desde)
        _gravar(sessao)
    except Exception:
        sessao.rollback()
        raise
    return recusados


def pedir(sessao: Session, trabalhador_id: int, programa: str = ID_PROGRAMA) -> Cadeado | None:
    """Pede o cadeado de um funcionário, mantendo os que este programa já tem.

    Devolve None se ficou com ele, ou o cadeado da outra pessoa se já estava tomado.
    """
    atuais = set(
        sessao.scalars(
            select(BloqueioTrabalhador.trabalhador_id).where(
                BloqueioTrabalhador.programa == programa
            )
        )
    )
    return definir(sessao, atuais | {trabalhador_id}, programa).get(trabalhador_id)


def largar(
    sessao: Session, trabalhador_ids: Iterable[int] | None = None, programa: str = ID_PROGRAMA
) -> None:
    """Larga os cadeados deste programa (todos, se não se disser quais). Faz commit."""
    consulta = delete(BloqueioTrabalhador).where(BloqueioTrabalhador.programa == programa)
    if trabalhador_ids is not None:
        consulta = consulta.where(BloqueioTrabalhador.trabalhador_id.in_(set(trabalhador_ids)))
    try:
        sessao.execute(consulta)
        _gravar(sessao)
    except Exception:
        sessao.rollback()
        raise


def renovar(sessao: Session, programa: str = ID_PROGRAMA) -> None:
    """Diz que este programa continua aberto (chamado de 30 em 30 segundos). Faz commit."""
    try:
        sessao.execute(
            update(BloqueioTrabalhador)
            .where(BloqueioTrabalhador.programa == programa)
            .values(renovado_em=agora(sessao))
        )
        _gravar(sessao)
    except Exception:
        sessao.rollback()
        raise
