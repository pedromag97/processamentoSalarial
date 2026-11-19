"""Folha de salário: do vencimento ao valor a pagar (módulo puro, sem base de dados)."""

from datetime import date
from decimal import Decimal as D

import pytest

from lsc_presencas import folha_salario as fs
from lsc_presencas.calculo import NIVEL_AVISO, NIVEL_ERRO
from lsc_presencas.folha_salario import DadosFolha, LinhaGer, Movimento, calcular_folha


def exemplo(**mudancas) -> DadosFolha:
    """O caso da folha Excel de referência: mês de 21 dias, preenchido até meio."""
    dados = dict(
        dias_trabalho_mes=21,
        vencimento_base=D("920"),
        dias_trabalhados=7,
        dias_faltas=3,
        subsidio_alimentacao_dia=D("8.50"),
        duodecimo_ferias=D("76.67"),
        duodecimo_natal=D("76.67"),
        irs=D("0"),
        taxa_seguranca_social=D("0.11"),
        linhas_ger=(
            LinhaGer("Ajuda (CH+VIAT+PROD)", "dia", D("200"), fs.MENSAL, D("0")),
            LinhaGer("Deslocação", "noite", D("15"), fs.UNITARIO, D("0")),
            LinhaGer("Banco de horas", "hora", D("8.125"), fs.UNITARIO, D("8")),
            LinhaGer("Dias de prevenção", "dia", D("100"), fs.SEMANAL, D("7")),
            LinhaGer("Horas de prevenção", "hora", D("5"), fs.UNITARIO, D("12")),
        ),
        movimentos=(Movimento("07/nov", D("-65")),),
    )
    dados.update(mudancas)
    return DadosFolha(**dados)


def totais(folha, bloco="rc") -> dict:
    linhas = folha.linhas_rc if bloco == "rc" else folha.linhas_ger
    return {(linha.chave if bloco == "rc" else linha.descricao): linha.total for linha in linhas}


# --- dias de trabalho do mês ------------------------------------------------------------------


def test_dias_de_trabalho_conta_de_segunda_a_sexta():
    assert fs.dias_de_trabalho(2026, 11) == 21
    assert fs.dias_de_trabalho(2026, 2) == 20


def test_dias_de_trabalho_tira_os_feriados_em_dia_util():
    feriados = [date(2026, 12, 8), date(2026, 12, 25), date(2026, 12, 26)]  # 26 é sábado
    assert fs.dias_de_trabalho(2026, 12) == 23
    assert fs.dias_de_trabalho(2026, 12, feriados) == 21


# --- bloco RC ---------------------------------------------------------------------------------


def test_exemplo_da_folha_excel_linha_a_linha():
    folha = calcular_folha(exemplo())
    assert totais(folha) == {
        fs.PRESENCAS: D("306.67"),  # 920 / 21 × 7
        fs.SUBSIDIO_ALIMENTACAO: D("59.50"),  # 8,50 × 7
        fs.SUBSIDIO_FERIAS: D("25.56"),  # 76,67 / 21 × 7
        fs.SUBSIDIO_NATAL: D("25.56"),
        fs.FERIAS: D("0.00"),
        fs.BAIXA: D("0.00"),
        fs.FALTAS: D("-131.43"),  # 920 / 21 × 3, a descontar
        fs.IRS: D("0.00"),
        fs.SEGURANCA_SOCIAL: D("-24.90"),  # 11% × 226,36
    }
    assert folha.base_seguranca_social == D("226.36")
    assert folha.vencimento_rc == D("260.96")
    assert not folha.incompleta


def test_valor_por_dia_divide_pelos_dias_de_trabalho_do_mes():
    folha = calcular_folha(exemplo(dias_trabalho_mes=23, dias_trabalhados=23, dias_faltas=0))
    assert folha.linha(fs.PRESENCAS).total == D("920.00")
    assert folha.linha(fs.PRESENCAS).valor_unitario == D("920") / 23


def test_ferias_pagam_se_e_contam_para_os_subsidios():
    folha = calcular_folha(exemplo(dias_trabalhados=16, dias_ferias=5, dias_faltas=0))
    assert folha.linha(fs.PRESENCAS).total == D("700.95")
    assert folha.linha(fs.FERIAS).total == D("219.05")
    assert folha.linha(fs.SUBSIDIO_FERIAS).quantidade == 21
    assert folha.linha(fs.SUBSIDIO_FERIAS).total == D("76.67")
    # o subsídio de alimentação só se paga nos dias trabalhados
    assert folha.linha(fs.SUBSIDIO_ALIMENTACAO).total == D("136.00")


def test_baixa_e_faltas_descontam_um_dia_cada():
    folha = calcular_folha(exemplo(dias_trabalhados=18, dias_baixa=2, dias_faltas=1))
    assert folha.linha(fs.BAIXA).total == D("-87.62")
    assert folha.linha(fs.FALTAS).total == D("-43.81")
    assert folha.linha(fs.BAIXA).valor_unitario < 0


def test_sem_duodecimos_na_ficha_nao_ha_linhas_de_subsidio():
    folha = calcular_folha(exemplo(duodecimo_ferias=None, duodecimo_natal=D("38.33")))
    assert folha.linha(fs.SUBSIDIO_FERIAS) is None
    assert folha.linha(fs.SUBSIDIO_NATAL).valor_mes == D("38.33")


def test_irs_e_o_valor_escrito_no_mes():
    folha = calcular_folha(exemplo(irs=D("35.5")))
    assert folha.linha(fs.IRS).total == D("-35.50")
    assert folha.vencimento_rc == D("225.46")
    # o IRS não mexe na base da Segurança Social
    assert folha.linha(fs.SEGURANCA_SOCIAL).total == D("-24.90")


def test_irs_por_preencher_conta_zero_e_avisa():
    folha = calcular_folha(exemplo(irs=None))
    assert folha.linha(fs.IRS).total == D("0")
    assert "irs_por_preencher" in folha.chaves_de_alerta()
    assert not folha.incompleta


def test_irs_negativo_e_recusado():
    with pytest.raises(ValueError):
        calcular_folha(exemplo(irs=D("-10")))


def test_seguranca_social_sem_limite_nao_conta_o_subsidio_de_alimentacao():
    folha = calcular_folha(exemplo())
    assert folha.base_seguranca_social == D("226.36")
    alerta = next(a for a in folha.alertas if a.chave == "subsidio_alimentacao_sem_limite_isencao")
    assert alerta.nivel == NIVEL_AVISO


def test_seguranca_social_conta_a_parte_do_subsidio_acima_do_limite():
    folha = calcular_folha(exemplo(limite_isencao_subsidio_dia=D("6.00")))
    # (8,50 − 6,00) × 7 dias = 17,50 sujeitos
    assert folha.base_seguranca_social == D("243.86")
    assert folha.linha(fs.SEGURANCA_SOCIAL).total == D("-26.82")
    assert "subsidio_alimentacao_sem_limite_isencao" not in folha.chaves_de_alerta()


def test_subsidio_abaixo_do_limite_fica_todo_isento():
    folha = calcular_folha(exemplo(limite_isencao_subsidio_dia=D("10")))
    assert folha.base_seguranca_social == D("226.36")


def test_base_da_seguranca_social_nunca_e_negativa():
    folha = calcular_folha(exemplo(dias_trabalhados=1, dias_faltas=10))
    assert folha.base_seguranca_social == D("0")
    assert folha.linha(fs.SEGURANCA_SOCIAL).total == D("0.00")
    assert "vencimento_negativo" in folha.chaves_de_alerta()


def test_sem_taxa_de_seguranca_social_fica_por_calcular():
    folha = calcular_folha(exemplo(taxa_seguranca_social=None))
    assert folha.linha(fs.SEGURANCA_SOCIAL).total is None
    assert folha.incompleta
    alerta = next(a for a in folha.alertas if a.chave == "sem_taxa_seguranca_social")
    assert alerta.nivel == NIVEL_ERRO


def test_sem_salario_base_nada_se_inventa():
    folha = calcular_folha(exemplo(vencimento_base=None))
    assert folha.linha(fs.PRESENCAS).total is None
    assert folha.linha(fs.FALTAS).total is None
    assert folha.linha(fs.SEGURANCA_SOCIAL).total is None
    assert folha.base_seguranca_social is None
    assert folha.incompleta
    assert "sem_salario_base" in folha.chaves_de_alerta()


def test_sem_valor_do_subsidio_de_alimentacao_a_linha_fica_por_calcular():
    folha = calcular_folha(exemplo(subsidio_alimentacao_dia=None))
    assert folha.linha(fs.SUBSIDIO_ALIMENTACAO).total is None
    assert "subsidio_alimentacao_sem_valor" in folha.chaves_de_alerta()


def test_mes_sem_dias_trabalhados_nao_tem_subsidio_de_alimentacao():
    folha = calcular_folha(exemplo(dias_trabalhados=0, dias_faltas=0, dias_ferias=21))
    assert folha.linha(fs.SUBSIDIO_ALIMENTACAO) is None
    assert folha.linha(fs.FERIAS).total == D("920.00")


def test_mais_dias_marcados_do_que_o_mes_tem_avisa():
    folha = calcular_folha(exemplo(dias_trabalhados=20, dias_faltas=3))
    assert "dias_a_mais" in folha.chaves_de_alerta()


def test_dias_negativos_ou_mes_sem_dias_sao_recusados():
    with pytest.raises(ValueError):
        calcular_folha(exemplo(dias_faltas=-1))
    with pytest.raises(ValueError):
        calcular_folha(exemplo(dias_trabalho_mes=0))


# --- bloco GER, líquido e a pagar -------------------------------------------------------------


def test_bloco_ger_do_exemplo():
    folha = calcular_folha(exemplo())
    assert totais(folha, "ger") == {
        "Ajuda (CH+VIAT+PROD)": D("0.00"),
        "Deslocação": D("0.00"),
        "Banco de horas": D("65.00"),  # 8 h × 8,125
        "Dias de prevenção": D("100.00"),  # 100 / 7 × 7 dias
        "Horas de prevenção": D("60.00"),  # 12 h × 5
    }
    assert folha.total_ger == D("225.00")


def test_linha_mensal_divide_pelos_dias_de_trabalho_do_mes():
    linha = LinhaGer("Ajuda", "dia", D("200"), fs.MENSAL, D("10"))
    folha = calcular_folha(exemplo(linhas_ger=(linha,)))
    assert folha.linhas_ger[0].total == D("95.24")  # 200 / 21 × 10
    assert folha.linhas_ger[0].valor_mes == D("200")


def test_linha_semanal_divide_por_sete():
    linha = LinhaGer("Prevenção", "dia", D("100"), fs.SEMANAL, D("3"))
    folha = calcular_folha(exemplo(linhas_ger=(linha,)))
    assert folha.linhas_ger[0].total == D("42.86")


def test_linha_ger_com_quantidade_e_sem_valor_e_erro():
    linha = LinhaGer("Deslocação", "noite", None, fs.UNITARIO, D("2"))
    folha = calcular_folha(exemplo(linhas_ger=(linha,)))
    assert folha.linhas_ger[0].total is None
    assert folha.incompleta
    assert "ger_sem_valor" in folha.chaves_de_alerta()


def test_linha_ger_sem_valor_e_sem_quantidade_nao_incomoda():
    linha = LinhaGer("Deslocação", "noite", None, fs.UNITARIO, D("0"))
    folha = calcular_folha(exemplo(linhas_ger=(linha,)))
    assert folha.linhas_ger[0].total == D("0")
    assert not folha.incompleta


def test_linha_ger_invalida_e_recusada():
    with pytest.raises(ValueError):
        calcular_folha(exemplo(linhas_ger=(LinhaGer("X", "dia", D("1"), "quinzenal", D("1")),)))
    with pytest.raises(ValueError):
        calcular_folha(exemplo(linhas_ger=(LinhaGer("X", "dia", D("1"), fs.UNITARIO, D("-1")),)))


def test_liquido_e_a_pagar():
    folha = calcular_folha(exemplo())
    assert folha.liquido == D("485.96")  # 260,96 + 225,00
    assert folha.total_movimentos == D("-65.00")
    assert folha.a_pagar == D("420.96")


def test_sem_adiantamentos_o_a_pagar_e_o_liquido():
    folha = calcular_folha(exemplo(movimentos=()))
    assert folha.a_pagar == folha.liquido


def test_cada_linha_arredonda_a_centimos():
    folha = calcular_folha(exemplo())
    for linha in (*folha.linhas_rc, *folha.linhas_ger):
        assert linha.total == linha.total.quantize(D("0.01"))


def test_a_folha_passa_a_json_e_volta_igual():
    import json

    folha = calcular_folha(
        DadosFolha(
            dias_trabalho_mes=21,
            vencimento_base=D("920"),
            dias_trabalhados=7,
            dias_faltas=3,
            subsidio_alimentacao_dia=D("8.50"),
            duodecimo_ferias=D("76.67"),
            irs=D("12.5"),
            taxa_seguranca_social=D("0.11"),
            linhas_ger=(
                LinhaGer("Ajuda", "dia", D("200"), fs.MENSAL, D("7")),
                LinhaGer("Sem valor", "hora", None, fs.UNITARIO, D("2")),
            ),
            movimentos=(Movimento("Adiantamento: 07/nov", D("-65")),),
        )
    )
    lida = fs.de_dict(json.loads(json.dumps(fs.para_dict(folha), ensure_ascii=False)))
    assert lida == folha
    assert (lida.a_pagar, lida.incompleta) == (folha.a_pagar, True)
