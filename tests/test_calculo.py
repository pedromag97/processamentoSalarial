"""Testes do módulo de cálculo.

Mês de referência: janeiro de 2027 (31 dias). O dia 1 é sexta-feira e feriado; há 20 dias úteis
sem contar o feriado. Os valores em euros são fictícios, escolhidos para dar contas redondas.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from lsc_presencas import calculo as c
from lsc_presencas.calculo import Codigo, DadosTrabalhador, Dia, Lancamento, Parametros

P = Codigo("P", conta_trabalhado=True, subsidio_alimentacao=True)
PF = Codigo("PF", conta_trabalhado=True, ajuda_custo_franca=c.AJUDA_SIM)
DF = Codigo("DF", ajuda_custo_franca=c.AJUDA_SIM)
FE = Codigo("FE")
FER = Codigo("FER")
FJ = Codigo("FJ")
FI = Codigo("FI", desconta_salario=True)
B = Codigo("B", desconta_salario=True)
AT = Codigo("AT", desconta_salario=True)
PR = Codigo(
    "PR",
    conta_trabalhado=True,
    subsidio_alimentacao=True,
    ajuda_custo_franca=c.AJUDA_ZONA,
    soma_prevencao=True,
)

FERIADOS = {date(2027, 1, 1)}
PARAMS = Parametros(
    subsidio_alimentacao_dia=D("6"), ajuda_custo_franca_dia=D("50"), prevencao_dia=D("30")
)
TRAB = DadosTrabalhador(salario_base=D("900"))
# Com 1040 € e 40 h semanais o valor/hora é exatamente 6,00 €.
TRAB_HE = DadosTrabalhador(salario_base=D("1040"))


def jan(dia: int) -> date:
    return date(2027, 1, dia)


def dias(codigo: Codigo, *numeros: int, horas=0, franca=False) -> list[Dia]:
    return [Dia(jan(n), codigo, D(str(horas)), franca) for n in numeros]


def calc(marcacoes=(), trabalhador=TRAB, parametros=PARAMS, lancamentos=(), mes=1):
    return c.calcular_mes(2027, mes, trabalhador, parametros, marcacoes, FERIADOS, lancamentos)


UTEIS = [4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 25, 26, 27, 28, 29]


# --- 1. Contagens -----------------------------------------------------------------------------


def test_contagens_por_codigo():
    r = calc(
        dias(P, 4, 5, 6)
        + dias(PF, 7, 8)
        + dias(DF, 9, 10)
        + dias(FE, 11)
        + dias(FER, 1)
        + dias(FJ, 12)
        + dias(FI, 13)
        + dias(B, 14)
        + dias(AT, 15)
        + dias(PR, 16)
    )
    assert r.contagens == {
        "P": 3, "PF": 2, "DF": 2, "FE": 1, "FER": 1, "FJ": 1, "FI": 1, "B": 1, "AT": 1, "PR": 1
    }  # fmt: skip


def test_marcacoes_de_outro_mes_sao_ignoradas():
    r = calc([Dia(date(2027, 2, 1), P), Dia(date(2026, 12, 31), P)] + dias(P, 4))
    assert r.contagens == {"P": 1}


def test_duas_marcacoes_no_mesmo_dia_e_erro():
    with pytest.raises(ValueError):
        calc(dias(P, 4) + dias(PF, 4))


# --- 2. Salário base --------------------------------------------------------------------------


def test_mes_completo_sem_faltas_paga_o_salario_base():
    r = calc(dias(P, *UTEIS))
    assert r.total_de(c.SALARIO_BASE) == D("900.00")
    assert r.rubrica(c.DESCONTO_SALARIO) is None


@pytest.mark.parametrize("codigo", [FI, B, AT])
def test_codigos_que_descontam_o_salario(codigo):
    r = calc(dias(codigo, 4, 5))
    # 900 / 30 × 2 = 60
    assert r.total_de(c.DESCONTO_SALARIO) == D("-60.00")
    assert r.total_de(c.SALARIO_BASE) + r.total_de(c.DESCONTO_SALARIO) == D("840.00")


@pytest.mark.parametrize("codigo", [P, PF, DF, FE, FER, FJ, PR])
def test_codigos_que_nao_descontam_o_salario(codigo):
    r = calc(dias(codigo, 4, 5))
    assert r.rubrica(c.DESCONTO_SALARIO) is None


def test_fj_desconta_se_a_flag_for_ligada():
    fj = replace(FJ, desconta_salario=True)
    assert calc(dias(fj, 4)).total_de(c.DESCONTO_SALARIO) == D("-30.00")


def test_desconto_junta_varios_codigos_e_arredonda_ao_centimo():
    r = calc(dias(FI, 4) + dias(B, 5, 6), trabalhador=DadosTrabalhador(salario_base=D("1000")))
    desconto = r.rubrica(c.DESCONTO_SALARIO)
    assert desconto.total == D("-100.00")  # 1000 / 30 × 3
    assert desconto.quantidade == 3
    assert "2 B" in desconto.descricao and "1 FI" in desconto.descricao
    r1 = calc(dias(FI, 4), trabalhador=DadosTrabalhador(salario_base=D("1000")))
    assert r1.total_de(c.DESCONTO_SALARIO) == D("-33.33")


def test_divisor_configuravel():
    r = calc(dias(FI, 4), parametros=replace(PARAMS, divisor_salario=D("22")))
    assert r.total_de(c.DESCONTO_SALARIO) == D("-40.91")  # 900 / 22


def test_admissao_a_meio_do_mes():
    r = calc(trabalhador=replace(TRAB, data_admissao=jan(11)))
    assert r.dias_contrato == 21
    assert r.total_de(c.SALARIO_BASE) == D("630.00")  # 900 / 30 × 21
    assert "Proporcional" in r.rubrica(c.SALARIO_BASE).formula


def test_saida_a_meio_do_mes():
    r = calc(trabalhador=replace(TRAB, data_saida=jan(20)))
    assert r.dias_contrato == 20
    assert r.total_de(c.SALARIO_BASE) == D("600.00")


def test_admissao_e_saida_no_mesmo_mes():
    r = calc(trabalhador=replace(TRAB, data_admissao=jan(11), data_saida=jan(20)))
    assert r.dias_contrato == 10
    assert r.total_de(c.SALARIO_BASE) == D("300.00")


def test_proporcional_nunca_passa_do_salario_base():
    # Admitido a 2 de janeiro: 30 dias de contrato num mês de 31.
    r = calc(trabalhador=replace(TRAB, data_admissao=jan(2)))
    assert r.total_de(c.SALARIO_BASE) == D("900.00")
    # Saída a 31 de um mês de 31 dias com admissão anterior = mês completo.
    r = calc(trabalhador=replace(TRAB, data_admissao=date(2026, 5, 1), data_saida=jan(31)))
    assert r.total_de(c.SALARIO_BASE) == D("900.00")


def test_fevereiro_completo_paga_o_salario_base_inteiro():
    r = calc(mes=2)
    assert r.dias_contrato == 28
    assert r.total_de(c.SALARIO_BASE) == D("900.00")


def test_faltas_no_mes_de_admissao():
    r = calc(dias(FI, 12), trabalhador=replace(TRAB, data_admissao=jan(11)))
    assert r.total == D("600.00")  # 630 − 30


def test_fora_do_contrato_nao_ha_salario():
    r = calc(trabalhador=replace(TRAB, data_saida=date(2026, 12, 31), ativo=False))
    assert r.dias_contrato == 0
    assert r.rubricas == []
    assert r.total == 0
    assert r.alertas == []


def test_marcacoes_fora_do_contrato_nao_contam_e_geram_alerta():
    r = calc(
        dias(P, 8, 11, 20, 21),
        trabalhador=replace(TRAB, data_admissao=jan(11), data_saida=jan(20)),
    )
    assert r.contagens == {"P": 2}
    alerta = next(a for a in r.alertas if a.chave == "marcacao_fora_contrato")
    assert alerta.datas == (jan(8), jan(21))
    assert alerta.nivel == c.NIVEL_ERRO


def test_trabalhador_ativo_sem_salario_base():
    r = calc(dias(P, 4), trabalhador=DadosTrabalhador())
    assert "sem_salario_base" in r.chaves_de_alerta()
    assert r.rubrica(c.SALARIO_BASE).total is None
    assert r.incompleto
    assert r.total == D("6.00")  # só o subsídio de alimentação


# --- 3. Subsídio de alimentação ---------------------------------------------------------------


def test_subsidio_de_alimentacao_sem_limite_mostra_so_o_total_e_avisa():
    r = calc(dias(P, *UTEIS[:10]))
    sub = r.rubrica(c.SUBSIDIO_ALIMENTACAO)
    assert (sub.quantidade, sub.valor_unitario, sub.total) == (10, D("6"), D("60.00"))
    assert sub.isento is None and sub.sujeito is None
    assert "subsidio_alimentacao_sem_limite_isencao" in r.chaves_de_alerta()
    assert not r.incompleto


@pytest.mark.parametrize(
    "limite, isento, sujeito",
    [("5", "50.00", "10.00"), ("6", "60.00", "0.00"), ("7", "60.00", "0.00")],
)
def test_subsidio_de_alimentacao_com_limite(limite, isento, sujeito):
    r = calc(
        dias(P, *UTEIS[:10]), parametros=replace(PARAMS, limite_isencao_subsidio_dia=D(limite))
    )
    sub = r.rubrica(c.SUBSIDIO_ALIMENTACAO)
    assert (sub.total, sub.isento, sub.sujeito) == (D("60.00"), D(isento), D(sujeito))
    assert "subsidio_alimentacao_sem_limite_isencao" not in r.chaves_de_alerta()


def test_subsidio_de_alimentacao_com_valor_de_excecao():
    r = calc(
        dias(P, *UTEIS[:10]),
        trabalhador=replace(TRAB, exc_subsidio_alimentacao=D("7.50")),
        parametros=replace(PARAMS, limite_isencao_subsidio_dia=D("6")),
    )
    sub = r.rubrica(c.SUBSIDIO_ALIMENTACAO)
    assert (sub.total, sub.isento, sub.sujeito) == (D("75.00"), D("60.00"), D("15.00"))
    assert "exceção" in sub.formula


def test_subsidio_sem_valor_nos_parametros_fica_por_calcular():
    r = calc(dias(P, 4, 5), parametros=replace(PARAMS, subsidio_alimentacao_dia=None))
    assert r.rubrica(c.SUBSIDIO_ALIMENTACAO).total is None
    assert "subsidio_alimentacao_sem_valor" in r.chaves_de_alerta()
    assert r.incompleto
    assert r.total == D("900.00")


def test_excecao_dispensa_o_valor_da_empresa():
    r = calc(
        dias(P, 4, 5),
        trabalhador=replace(TRAB, exc_subsidio_alimentacao=D("8")),
        parametros=replace(PARAMS, subsidio_alimentacao_dia=None),
    )
    assert r.total_de(c.SUBSIDIO_ALIMENTACAO) == D("16.00")
    assert not r.incompleto


def test_sem_dias_nao_ha_rubrica_nem_alerta_de_parametro_em_falta():
    r = calc(dias(FE, 4, 5), parametros=Parametros())
    assert r.rubrica(c.SUBSIDIO_ALIMENTACAO) is None
    assert not r.incompleto


def test_pf_so_da_subsidio_se_a_flag_for_ligada():
    assert calc(dias(PF, 4, 5)).rubrica(c.SUBSIDIO_ALIMENTACAO) is None
    pf = replace(PF, subsidio_alimentacao=True)
    assert calc(dias(pf, 4, 5)).total_de(c.SUBSIDIO_ALIMENTACAO) == D("12.00")


@pytest.mark.parametrize("codigo", [DF, FE, FER, FJ, FI, B, AT])
def test_codigos_sem_subsidio_de_alimentacao(codigo):
    assert calc(dias(codigo, 4)).rubrica(c.SUBSIDIO_ALIMENTACAO) is None


# --- 4. Ajuda de custo França -----------------------------------------------------------------


def test_ajuda_de_custo_conta_pf_e_df():
    r = calc(dias(PF, 4, 5, 6, 7, 8) + dias(DF, 9, 10) + dias(P, 11))
    ajuda = r.rubrica(c.AJUDA_CUSTO_FRANCA)
    assert (ajuda.quantidade, ajuda.total) == (7, D("350.00"))
    assert ajuda.isento is None
    assert "ajuda_custo_franca_sem_limite_isencao" in r.chaves_de_alerta()


def test_ajuda_de_custo_com_limite_e_excecao():
    r = calc(
        dias(PF, 4, 5),
        trabalhador=replace(TRAB, exc_ajuda_custo_franca=D("62.75")),
        parametros=replace(PARAMS, limite_isencao_ajuda_custo_dia=D("50")),
    )
    ajuda = r.rubrica(c.AJUDA_CUSTO_FRANCA)
    assert (ajuda.total, ajuda.isento, ajuda.sujeito) == (D("125.50"), D("100.00"), D("25.50"))


def test_ajuda_de_custo_sem_valor_fica_por_calcular():
    r = calc(dias(PF, 4), parametros=replace(PARAMS, ajuda_custo_franca_dia=None))
    assert r.rubrica(c.AJUDA_CUSTO_FRANCA).total is None
    assert "ajuda_custo_franca_sem_valor" in r.chaves_de_alerta()


def test_prevencao_so_da_ajuda_de_custo_em_zona_francesa():
    assert calc(dias(PR, 4, franca=False)).rubrica(c.AJUDA_CUSTO_FRANCA) is None
    assert calc(dias(PR, 4, franca=True)).total_de(c.AJUDA_CUSTO_FRANCA) == D("50.00")


@pytest.mark.parametrize("codigo", [P, FE, FER, FJ, FI, B, AT])
def test_codigos_sem_ajuda_de_custo(codigo):
    assert calc(dias(codigo, 4, franca=True)).rubrica(c.AJUDA_CUSTO_FRANCA) is None


# --- 5. Prevenção -----------------------------------------------------------------------------


def test_prevencao():
    r = calc(dias(PR, 9, 10))
    assert r.total_de(c.PREVENCAO) == D("60.00")
    assert r.total_de(c.SUBSIDIO_ALIMENTACAO) == D("12.00")  # PR também dá subsídio
    assert r.rubrica(c.PREVENCAO).isento is None


def test_prevencao_com_excecao_e_sem_valor():
    r = calc(dias(PR, 9), trabalhador=replace(TRAB, exc_prevencao=D("45")))
    assert r.total_de(c.PREVENCAO) == D("45.00")
    r = calc(dias(PR, 9), parametros=replace(PARAMS, prevencao_dia=None))
    assert r.rubrica(c.PREVENCAO).total is None
    assert "prevencao_sem_valor" in r.chaves_de_alerta()


# --- 6. Horas extra ---------------------------------------------------------------------------


def test_valor_hora():
    assert c.valor_hora(D("1040"), D("40")) == D("6")


def test_horas_extra_em_dia_util():
    r = calc(dias(P, 4, horas=3), trabalhador=TRAB_HE)
    primeira, seguintes = r.rubrica(c.HE_PRIMEIRA_HORA), r.rubrica(c.HE_HORAS_SEGUINTES)
    assert (primeira.quantidade, primeira.total) == (1, D("7.50"))  # 6 × 1,25
    assert (seguintes.quantidade, seguintes.total) == (2, D("16.50"))  # 2 × 6 × 1,375
    assert r.rubrica(c.HE_DESCANSO_FERIADO) is None
    assert r.horas_extra == 3
    assert "25%" in primeira.formula and "37,5%" in seguintes.formula


def test_a_primeira_hora_conta_se_por_dia():
    r = calc(dias(P, 4, 5, horas=1) + dias(PF, 6, horas=0.5), trabalhador=TRAB_HE)
    assert r.rubrica(c.HE_PRIMEIRA_HORA).quantidade == D("2.5")
    assert r.total_de(c.HE_PRIMEIRA_HORA) == D("18.75")  # 2,5 × 7,50
    assert r.rubrica(c.HE_HORAS_SEGUINTES) is None


def test_horas_extra_ao_fim_de_semana():
    r = calc(dias(PF, 9, horas=2) + dias(PF, 10, horas=1.5), trabalhador=TRAB_HE)  # sáb. e dom.
    descanso = r.rubrica(c.HE_DESCANSO_FERIADO)
    assert (descanso.quantidade, descanso.total) == (D("3.5"), D("31.50"))  # 3,5 × 6 × 1,5
    assert r.rubrica(c.HE_PRIMEIRA_HORA) is None


def test_horas_extra_em_feriado():
    r = calc(dias(PF, 1, horas=2), trabalhador=TRAB_HE)  # sexta-feira, 1 de janeiro
    assert r.total_de(c.HE_DESCANSO_FERIADO) == D("18.00")
    assert r.rubrica(c.HE_PRIMEIRA_HORA) is None


def test_acrescimos_editaveis():
    params = replace(
        PARAMS,
        acrescimo_he_primeira_hora=D("0.5"),
        acrescimo_he_horas_seguintes=D("0.75"),
        acrescimo_he_descanso_feriado=D("1"),
        horas_semanais=D("35"),
    )
    # valor/hora = 1050 × 12 / (52 × 35) = 6,923076...
    trab = DadosTrabalhador(salario_base=D("1050"))
    r = calc(dias(P, 4, horas=2) + dias(P, 9, horas=1), trabalhador=trab, parametros=params)
    assert r.total_de(c.HE_PRIMEIRA_HORA) == D("10.38")
    assert r.total_de(c.HE_HORAS_SEGUINTES) == D("12.12")
    assert r.total_de(c.HE_DESCANSO_FERIADO) == D("13.85")


def test_valor_hora_de_excecao():
    r = calc(dias(P, 4, horas=1), trabalhador=replace(TRAB_HE, exc_valor_hora_extra=D("10")))
    assert r.total_de(c.HE_PRIMEIRA_HORA) == D("12.50")
    assert "exceção" in r.rubrica(c.HE_PRIMEIRA_HORA).formula


def test_horas_extra_sem_salario_ficam_por_calcular():
    r = calc(dias(P, 4, horas=1), trabalhador=DadosTrabalhador())
    assert r.rubrica(c.HE_PRIMEIRA_HORA).total is None
    assert r.horas_extra == 1


def test_limite_de_horas_extra_no_mes():
    marcacoes = dias(P, 4, 5, 6, horas=4)
    com_limite = replace(PARAMS, limite_horas_extra_mes=D("10"))
    assert (
        "horas_extra_acima_do_limite" in calc(marcacoes, parametros=com_limite).chaves_de_alerta()
    )
    no_limite = replace(PARAMS, limite_horas_extra_mes=D("12"))
    assert (
        "horas_extra_acima_do_limite"
        not in calc(marcacoes, parametros=no_limite).chaves_de_alerta()
    )
    assert "horas_extra_acima_do_limite" not in calc(marcacoes).chaves_de_alerta()


def test_horas_extra_em_codigo_nao_trabalhado_pede_confirmacao():
    r = calc(dias(FE, 4, horas=2), trabalhador=TRAB_HE)
    assert "horas_extra_sem_trabalho" in r.chaves_de_alerta()
    assert r.horas_extra == 2


# --- 7 e 8. Lançamentos e total ---------------------------------------------------------------


def test_lancamentos_manuais_somam_e_subtraem():
    r = calc(
        lancamentos=[
            Lancamento("adiantamento", "Adiantamento de dia 15", D("-100")),
            Lancamento("premio", "Prémio de produção", D("50.555")),
        ]
    )
    valores = [x.total for x in r.rubricas if x.chave == c.LANCAMENTO]
    assert valores == [D("-100.00"), D("50.56")]
    assert r.total == D("850.56")
    assert "Adiantamento de dia 15" in r.rubricas[1].descricao


def test_total_e_a_soma_das_rubricas():
    r = calc(
        dias(P, 4, 5, horas=1)
        + dias(PF, 6, 7, 8)
        + dias(DF, 9, 10)
        + dias(PR, 16, franca=True)
        + dias(FI, 11)
        + dias(B, 12, 13),
        trabalhador=TRAB_HE,
        parametros=replace(
            PARAMS, limite_isencao_subsidio_dia=D("5"), limite_isencao_ajuda_custo_dia=D("40")
        ),
        lancamentos=[Lancamento("desconto", "Multa", D("-25"))],
    )
    esperado = {
        c.SALARIO_BASE: D("1040.00"),
        c.DESCONTO_SALARIO: D("-104.00"),  # 1040 / 30 × 3
        c.SUBSIDIO_ALIMENTACAO: D("18.00"),  # 2 P + 1 PR
        c.AJUDA_CUSTO_FRANCA: D("300.00"),  # 3 PF + 2 DF + 1 PR em França
        c.PREVENCAO: D("30.00"),
        c.HE_PRIMEIRA_HORA: D("15.00"),
        c.LANCAMENTO: D("-25.00"),
    }
    assert {x.chave: x.total for x in r.rubricas} == esperado
    assert r.total == sum(esperado.values())
    assert not r.incompleto
    assert r.rubrica(c.SUBSIDIO_ALIMENTACAO).sujeito == D("3.00")
    assert r.rubrica(c.AJUDA_CUSTO_FRANCA).isento == D("240.00")
    assert all(x.formula for x in r.rubricas)


# --- 9. Validações e alertas ------------------------------------------------------------------


def test_dias_uteis_sem_marcacao():
    r = calc(dias(P, *UTEIS[:-2]))
    alerta = next(a for a in r.alertas if a.chave == "dias_uteis_sem_marcacao")
    assert alerta.datas == (jan(28), jan(29))
    # Fins de semana e o feriado de dia 1 não contam como dias em falta.
    assert "dias_uteis_sem_marcacao" not in calc(dias(P, *UTEIS)).chaves_de_alerta()


def test_dias_uteis_sem_marcacao_so_dentro_do_contrato():
    r = calc(dias(P, 11, 12), trabalhador=replace(TRAB, data_admissao=jan(11), data_saida=jan(13)))
    alerta = next(a for a in r.alertas if a.chave == "dias_uteis_sem_marcacao")
    assert alerta.datas == (jan(13),)


def test_trabalho_em_feriado_pede_confirmacao():
    r = calc(dias(PF, 1))
    alerta = next(a for a in r.alertas if a.chave == "trabalho_em_feriado")
    assert alerta.nivel == c.NIVEL_CONFIRMAR and alerta.datas == (jan(1),)
    assert "trabalho_em_feriado" not in calc(dias(FER, 1) + dias(DF, 2)).chaves_de_alerta()


def test_sem_parametros_da_empresa():
    r = c.calcular_mes(2027, 1, TRAB, None, dias(P, 4) + dias(PF, 5), FERIADOS)
    assert "parametros_em_falta" in r.chaves_de_alerta()
    assert r.rubrica(c.SUBSIDIO_ALIMENTACAO).total is None
    assert r.rubrica(c.AJUDA_CUSTO_FRANCA).total is None
    assert r.incompleto
    assert r.total == D("900.00")


def test_mes_limpo_nao_tem_alertas():
    params = replace(
        PARAMS, limite_isencao_subsidio_dia=D("6"), limite_isencao_ajuda_custo_dia=D("50")
    )
    r = calc(dias(FER, 1) + dias(P, *UTEIS[:10]) + dias(PF, *UTEIS[10:]), parametros=params)
    assert r.alertas == []
