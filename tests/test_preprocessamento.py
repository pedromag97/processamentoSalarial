"""Ligação entre a base de dados e o cálculo, sobre os dados de demonstração."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from lsc_presencas import calculo
from lsc_presencas.demo import MES_DEMO, semear
from lsc_presencas.modelos import ParametrosEmpresa, Trabalhador
from lsc_presencas.preprocessamento import calcular_trabalhador, feriados_do_mes


def _demo(sessao):
    semear(sessao)
    sessao.flush()
    return {t.numero: t for t in sessao.scalars(select(Trabalhador))}


def test_feriados_do_mes(sessao):
    assert feriados_do_mes(sessao, 2027, 1) == {date(2027, 1, 1)}
    assert feriados_do_mes(sessao, 2027, 2) == set()


def test_todos_os_trabalhadores_de_demonstracao_calculam(sessao):
    trabalhadores = _demo(sessao)
    for t in trabalhadores.values():
        r = calcular_trabalhador(sessao, t, *MES_DEMO)
        assert "marcacao_fora_contrato" not in r.chaves_de_alerta()
        assert "sem_salario_base" not in r.chaves_de_alerta()
        assert r.total == sum(x.total for x in r.rubricas if x.total is not None)
        if t.ativo:
            assert r.rubrica(calculo.SALARIO_BASE).total > 0


def test_sem_valores_nos_parametros_o_resultado_fica_incompleto_e_avisa(sessao):
    t = _demo(sessao)[4]
    r = calcular_trabalhador(sessao, t, *MES_DEMO)
    assert r.incompleto
    assert r.chaves_de_alerta() & {"subsidio_alimentacao_sem_valor", "ajuda_custo_franca_sem_valor"}


def test_com_parametros_preenchidos_o_resultado_fica_completo(sessao):
    trabalhadores = _demo(sessao)
    for p in sessao.scalars(select(ParametrosEmpresa)):
        p.subsidio_alimentacao_dia = Decimal("6")
        p.ajuda_custo_franca_dia = Decimal("50")
        p.prevencao_dia = Decimal("30")
        p.taxa_seguranca_social = Decimal("0.11")
    sessao.flush()

    # Nº 4: tem um adiantamento de −100 € nos dados de demonstração.
    r = calcular_trabalhador(sessao, trabalhadores[4], *MES_DEMO)
    assert not r.incompleto
    assert r.total_de(calculo.LANCAMENTO) == Decimal("-100.00")

    # Nº 1 entrou a 11 de janeiro: 21 dias de contrato.
    r = calcular_trabalhador(sessao, trabalhadores[1], *MES_DEMO)
    assert r.dias_contrato == 21
    salario = trabalhadores[1].salarios[0].valor
    assert r.total_de(calculo.SALARIO_BASE) == calculo.arredondar(salario / 30 * 21)

    # Nº 3 tem subsídio de alimentação de exceção (7,50 €).
    r = calcular_trabalhador(sessao, trabalhadores[3], *MES_DEMO)
    sub = r.rubrica(calculo.SUBSIDIO_ALIMENTACAO)
    if sub is not None:
        assert sub.valor_unitario == Decimal("7.50")


def test_trabalhador_sem_empresa_nao_tem_parametros(sessao):
    t = Trabalhador(numero=900, nome="Sem Empresa")
    sessao.add(t)
    sessao.flush()
    r = calcular_trabalhador(sessao, t, 2027, 1)
    assert {"parametros_em_falta", "sem_salario_base"} <= r.chaves_de_alerta()
