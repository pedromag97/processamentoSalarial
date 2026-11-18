"""Fecho do mês por empresa: alertas, fechar (com fotografia das rubricas) e reabrir.

Sem interface. Um mês fechado deixa de aceitar alterações às marcações e aos lançamentos
(ver presencas.py e lancamentos.py); o Excel e os PDF passam a sair da fotografia guardada.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import backups, calculo, contas, mapa
from .modelos import (
    FECHO_ABERTO,
    FECHO_FECHADO,
    Auditoria,
    FechoMes,
    FechoTrabalhador,
    Trabalhador,
)
from .presencas import utilizador_atual

ORDEM_NIVEL = {calculo.NIVEL_ERRO: 0, calculo.NIVEL_CONFIRMAR: 1, calculo.NIVEL_AVISO: 2}
NOME_NIVEL = {
    calculo.NIVEL_ERRO: "Erro",
    calculo.NIVEL_CONFIRMAR: "A confirmar",
    calculo.NIVEL_AVISO: "Aviso",
}


class FechoRecusado(ValueError):
    """O mês não pode ser fechado (ou reaberto) no estado em que está."""


class FechoPorConfirmar(FechoRecusado):
    """Há avisos que o utilizador tem de confirmar antes de fechar."""


@dataclass(frozen=True)
class AlertaFecho:
    numero: int | None  # None = alerta da empresa, não de um trabalhador
    nome: str
    nivel: str
    mensagem: str
    datas: tuple[date, ...] = ()


# --- Consultar --------------------------------------------------------------------------------


def registo(sessao: Session, empresa_id: int, ano: int, mes: int) -> FechoMes | None:
    return sessao.scalars(
        select(FechoMes).where(
            FechoMes.empresa_id == empresa_id, FechoMes.ano == ano, FechoMes.mes == mes
        )
    ).first()


def esta_fechado(sessao: Session, empresa_id: int, ano: int, mes: int) -> bool:
    fecho = registo(sessao, empresa_id, ano, mes)
    return fecho is not None and fecho.estado == FECHO_FECHADO


def mapa_do_mes(sessao: Session, empresa_id: int, ano: int, mes: int) -> mapa.MapaMes:
    """O mapa do mês: a fotografia guardada se estiver fechado; senão, calculado agora."""
    fecho = registo(sessao, empresa_id, ano, mes)
    if fecho is None or fecho.estado != FECHO_FECHADO or not fecho.fotografia:
        return mapa.construir(sessao, empresa_id, ano, mes)
    guardado = mapa.cabecalho_de_json(empresa_id, ano, mes, fecho.fotografia)
    guardado.fechado = True
    guardado.fechado_em = fecho.data
    guardado.fechado_por = fecho.utilizador
    guardado.trabalhadores = [
        mapa.trabalhador_de_json(x.trabalhador_id, x.numero, x.nome, x.dados) for x in fecho.linhas
    ]
    return guardado


def alertas(sessao: Session, do_mes: mapa.MapaMes) -> list[AlertaFecho]:
    """Alertas do mês, com os erros primeiro."""
    lista: list[AlertaFecho] = []
    if do_mes.parametros is None:
        lista.append(
            AlertaFecho(
                None,
                do_mes.empresa,
                calculo.NIVEL_ERRO,
                "Não há parâmetros da empresa em vigor neste mês (ecrã Tabelas).",
            )
        )
    if not do_mes.trabalhadores:
        lista.append(
            AlertaFecho(
                None,
                do_mes.empresa,
                calculo.NIVEL_ERRO,
                "Não há trabalhadores desta empresa com contrato neste mês.",
            )
        )
    if not do_mes.fechado:
        sem_empresa = sessao.scalar(
            select(func.count())
            .select_from(Trabalhador)
            .where(Trabalhador.empresa_id.is_(None), Trabalhador.ativo)
        )
        if sem_empresa:
            lista.append(
                AlertaFecho(
                    None,
                    "(sem empresa)",
                    calculo.NIVEL_AVISO,
                    f"Há {sem_empresa} trabalhador(es) ativo(s) sem empresa atribuída: não "
                    "entram no fecho de nenhuma empresa.",
                )
            )
    for t in do_mes.trabalhadores:
        for a in t.resultado.alertas:
            lista.append(AlertaFecho(t.numero, t.nome, a.nivel, a.mensagem, a.datas))
    lista.sort(key=lambda a: (ORDEM_NIVEL.get(a.nivel, 9), a.numero or 0))
    return lista


def contar_niveis(lista: list[AlertaFecho]) -> tuple[int, int]:
    """(erros, avisos e confirmações)."""
    erros = sum(1 for a in lista if a.nivel == calculo.NIVEL_ERRO)
    return erros, len(lista) - erros


# --- Fechar e reabrir -------------------------------------------------------------------------


def fechar(
    sessao: Session,
    empresa_id: int,
    ano: int,
    mes: int,
    *,
    confirmado: bool = False,
    utilizador: str | None = None,
    com_backup: bool = True,
) -> mapa.MapaMes:
    """Fecha o mês e guarda a fotografia das rubricas. Devolve o mapa fechado.

    Recusa (`FechoRecusado`) se houver erros; pede confirmação (`FechoPorConfirmar`) se houver
    avisos e `confirmado` for False. Faz uma cópia de segurança antes de gravar.
    """
    contas.exigir_admin("fechar o mês")
    utilizador = utilizador or utilizador_atual()
    try:
        fecho = registo(sessao, empresa_id, ano, mes)
        if fecho is not None and fecho.estado == FECHO_FECHADO:
            raise FechoRecusado("Este mês já está fechado.")
        do_mes = mapa.construir(sessao, empresa_id, ano, mes)
        erros, avisos = contar_niveis(alertas(sessao, do_mes))
        if erros:
            raise FechoRecusado(
                f"Há {erros} erro(s) por resolver. O mês só pode ser fechado sem erros."
            )
        if avisos and not confirmado:
            raise FechoPorConfirmar(f"Há {avisos} aviso(s). Confirme que os viu para fechar o mês.")
        if com_backup:
            sessao.commit()  # nada pendente: liberta a base de dados para a cópia
            backups.fazer_backup(sessao.get_bind(), f"fecho-{ano}-{mes:02d}")

        agora = datetime.now()
        if fecho is None:
            fecho = FechoMes(empresa_id=empresa_id, ano=ano, mes=mes)
            sessao.add(fecho)
        fecho.estado = FECHO_FECHADO
        fecho.data = agora
        fecho.utilizador = utilizador
        fecho.nota = None
        fecho.fotografia = mapa.cabecalho_para_json(do_mes)
        fecho.linhas = [
            FechoTrabalhador(
                trabalhador_id=t.trabalhador_id,
                numero=t.numero,
                nome=t.nome,
                total=t.total,
                dados=mapa.trabalhador_para_json(t),
            )
            for t in do_mes.trabalhadores
        ]
        sessao.flush()
        sessao.add(
            Auditoria(
                utilizador=utilizador,
                entidade="fecho_mes",
                entidade_id=fecho.id,
                acao="fechar",
                valor_novo=json.dumps(
                    {
                        "empresa": do_mes.empresa,
                        "mes": do_mes.periodo,
                        "trabalhadores": len(do_mes.trabalhadores),
                        "total": str(do_mes.total),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    do_mes.fechado = True
    do_mes.fechado_em = agora
    do_mes.fechado_por = utilizador
    return do_mes


def reabrir(
    sessao: Session,
    empresa_id: int,
    ano: int,
    mes: int,
    motivo: str,
    *,
    utilizador: str | None = None,
    com_backup: bool = True,
) -> None:
    """Reabre um mês fechado. O motivo é obrigatório e fica registado na auditoria.

    A fotografia do fecho é apagada (fica na cópia de segurança feita antes de reabrir).
    """
    contas.exigir_admin("reabrir o mês")
    motivo = (motivo or "").strip()
    if not motivo:
        raise FechoRecusado("Para reabrir o mês é obrigatório escrever o motivo.")
    utilizador = utilizador or utilizador_atual()
    try:
        fecho = registo(sessao, empresa_id, ano, mes)
        if fecho is None or fecho.estado != FECHO_FECHADO:
            raise FechoRecusado("Este mês não está fechado.")
        if com_backup:
            sessao.commit()
            backups.fazer_backup(sessao.get_bind(), f"reabertura-{ano}-{mes:02d}")
        total = sum((x.total for x in fecho.linhas), calculo.ZERO)
        antigo = json.dumps(
            {
                "fechado_em": fecho.data.isoformat() if fecho.data else None,
                "fechado_por": fecho.utilizador,
                "trabalhadores": len(fecho.linhas),
                "total": str(total),
            },
            ensure_ascii=False,
        )
        fecho.estado = FECHO_ABERTO
        fecho.data = datetime.now()
        fecho.utilizador = utilizador
        fecho.nota = motivo[:250]
        fecho.fotografia = None
        fecho.linhas = []
        sessao.add(
            Auditoria(
                utilizador=utilizador,
                entidade="fecho_mes",
                entidade_id=fecho.id,
                acao="reabrir",
                valor_antigo=antigo,
                motivo=motivo[:250],
            )
        )
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
