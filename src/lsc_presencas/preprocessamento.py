"""Liga a base de dados ao módulo de cálculo: lê os dados de um trabalhador e chama `calculo`."""

from calendar import monthrange
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import calculo
from .consultas import parametros_em_vigor, salario_em_vigor
from .modelos import (
    PAIS_FRANCA,
    PAIS_PORTUGAL,
    CodigoPresenca,
    Feriado,
    LancamentoManual,
    Marcacao,
    ParametrosEmpresa,
    Trabalhador,
)

CAMPOS_PARAMETROS = (
    "subsidio_alimentacao_dia",
    "ajuda_custo_franca_dia",
    "prevencao_dia",
    "horas_semanais",
    "divisor_salario",
    "acrescimo_he_primeira_hora",
    "acrescimo_he_horas_seguintes",
    "acrescimo_he_descanso_feriado",
    "limite_isencao_subsidio_dia",
    "limite_isencao_ajuda_custo_dia",
    "limite_horas_extra_mes",
)


def para_codigo(c: CodigoPresenca) -> calculo.Codigo:
    return calculo.Codigo(
        codigo=c.codigo,
        conta_trabalhado=c.conta_trabalhado,
        subsidio_alimentacao=c.subsidio_alimentacao,
        ajuda_custo_franca=c.ajuda_custo_franca,
        desconta_salario=c.desconta_salario,
        soma_prevencao=c.soma_prevencao,
    )


def para_parametros(p: ParametrosEmpresa | None) -> calculo.Parametros | None:
    if p is None:
        return None
    return calculo.Parametros(**{campo: getattr(p, campo) for campo in CAMPOS_PARAMETROS})


def feriados_do_mes(sessao: Session, ano: int, mes: int, pais: str = PAIS_PORTUGAL) -> set[date]:
    primeiro, ultimo = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    return set(
        sessao.scalars(
            select(Feriado.data).where(Feriado.pais == pais, Feriado.data.between(primeiro, ultimo))
        )
    )


def calcular_trabalhador(
    sessao: Session, trabalhador: Trabalhador, ano: int, mes: int
) -> calculo.Resultado:
    """Pré-processamento de um trabalhador num mês, com os dados que estão na base de dados.

    Usa o salário e os parâmetros em vigor no último dia de contrato dentro do mês, e os
    feriados portugueses (o contrato é português).
    """
    primeiro, ultimo = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    referencia = min(ultimo, trabalhador.data_saida or ultimo)

    salario = salario_em_vigor(sessao, trabalhador.id, referencia)
    parametros = (
        parametros_em_vigor(sessao, trabalhador.empresa_id, referencia)
        if trabalhador.empresa_id is not None
        else None
    )
    marcacoes = sessao.scalars(
        select(Marcacao).where(
            Marcacao.trabalhador_id == trabalhador.id, Marcacao.data.between(primeiro, ultimo)
        )
    ).all()
    lancamentos = sessao.scalars(
        select(LancamentoManual)
        .where(
            LancamentoManual.trabalhador_id == trabalhador.id,
            LancamentoManual.ano == ano,
            LancamentoManual.mes == mes,
        )
        .order_by(LancamentoManual.id)
    ).all()

    return calculo.calcular_mes(
        ano,
        mes,
        calculo.DadosTrabalhador(
            salario_base=salario.valor if salario else None,
            data_admissao=trabalhador.data_admissao,
            data_saida=trabalhador.data_saida,
            ativo=trabalhador.ativo,
            exc_subsidio_alimentacao=trabalhador.exc_subsidio_alimentacao,
            exc_ajuda_custo_franca=trabalhador.exc_ajuda_custo_franca,
            exc_prevencao=trabalhador.exc_prevencao,
            exc_valor_hora_extra=trabalhador.exc_valor_hora_extra,
        ),
        para_parametros(parametros),
        [
            calculo.Dia(
                data=m.data,
                codigo=para_codigo(m.codigo),
                horas_extra=m.horas_extra,
                zona_em_franca=m.zona is not None and m.zona.pais == PAIS_FRANCA,
            )
            for m in marcacoes
        ],
        feriados_do_mes(sessao, ano, mes),
        [calculo.Lancamento(lanc.tipo, lanc.descricao, lanc.valor) for lanc in lancamentos],
    )
