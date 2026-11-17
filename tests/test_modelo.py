from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lsc_presencas.consultas import parametros_em_vigor, salario_em_vigor
from lsc_presencas.dados_base import carregar_dados_base, domingo_de_pascoa, feriados_nacionais
from lsc_presencas.modelos import (
    AJUDA_CUSTO_NAO,
    AJUDA_CUSTO_SIM,
    AJUDA_CUSTO_ZONA,
    CodigoPresenca,
    Empresa,
    Feriado,
    Marcacao,
    ParametrosEmpresa,
    SalarioBase,
    Trabalhador,
)


def _codigo(sessao, codigo):
    return sessao.scalars(select(CodigoPresenca).where(CodigoPresenca.codigo == codigo)).one()


def _trabalhador(sessao, numero=1, **campos):
    t = Trabalhador(numero=numero, nome=f"Teste {numero}", **campos)
    sessao.add(t)
    sessao.flush()
    return t


# --- Códigos de presença ----------------------------------------------------------------------


def test_os_dez_codigos_base_existem(sessao):
    codigos = set(sessao.scalars(select(CodigoPresenca.codigo)))
    assert codigos == {"P", "PF", "DF", "FE", "FER", "FJ", "FI", "B", "AT", "PR"}


@pytest.mark.parametrize(
    "codigo, trabalhado, subsidio, ajuda, desconta, prevencao",
    [
        ("P", True, True, AJUDA_CUSTO_NAO, False, False),
        ("PF", True, False, AJUDA_CUSTO_SIM, False, False),
        ("DF", False, False, AJUDA_CUSTO_SIM, False, False),
        ("FE", False, False, AJUDA_CUSTO_NAO, False, False),
        ("FER", False, False, AJUDA_CUSTO_NAO, False, False),
        ("FJ", False, False, AJUDA_CUSTO_NAO, False, False),
        ("FI", False, False, AJUDA_CUSTO_NAO, True, False),
        ("B", False, False, AJUDA_CUSTO_NAO, True, False),
        ("AT", False, False, AJUDA_CUSTO_NAO, True, False),
        ("PR", True, True, AJUDA_CUSTO_ZONA, False, True),
    ],
)
def test_flags_dos_codigos(sessao, codigo, trabalhado, subsidio, ajuda, desconta, prevencao):
    c = _codigo(sessao, codigo)
    assert c.conta_trabalhado is trabalhado
    assert c.subsidio_alimentacao is subsidio
    assert c.ajuda_custo_franca == ajuda
    assert c.desconta_salario is desconta
    assert c.soma_prevencao is prevencao


def test_carregar_dados_base_nao_duplica_nem_repoe_edicoes(sessao):
    pf = _codigo(sessao, "PF")
    pf.subsidio_alimentacao = True  # o utilizador mudou a flag
    sessao.flush()
    codigos_antes = sessao.scalar(select(func.count()).select_from(CodigoPresenca))
    feriados_antes = sessao.scalar(select(func.count()).select_from(Feriado))

    carregar_dados_base(sessao)

    assert sessao.scalar(select(func.count()).select_from(CodigoPresenca)) == codigos_antes
    assert sessao.scalar(select(func.count()).select_from(Feriado)) == feriados_antes
    assert _codigo(sessao, "PF").subsidio_alimentacao is True


def test_codigo_novo_pode_ser_criado_sem_mexer_no_codigo(sessao):
    sessao.add(CodigoPresenca(codigo="FORM", descricao="Formação", conta_trabalhado=True))
    sessao.flush()
    assert _codigo(sessao, "FORM").ajuda_custo_franca == AJUDA_CUSTO_NAO


# --- Feriados ---------------------------------------------------------------------------------


def test_pascoa():
    assert domingo_de_pascoa(2026) == date(2026, 4, 5)
    assert domingo_de_pascoa(2027) == date(2027, 3, 28)


def test_feriados_nacionais_2027():
    feriados = dict(feriados_nacionais(2027))
    assert len(feriados) == 13
    assert feriados[date(2027, 3, 26)] == "Sexta-feira Santa"
    assert feriados[date(2027, 5, 27)] == "Corpo de Deus"
    assert date(2027, 12, 25) in feriados


def test_feriados_de_2026_e_2027_carregados(sessao):
    anos = {f.data.year for f in sessao.scalars(select(Feriado))}
    assert anos == {2026, 2027}
    assert sessao.scalar(select(func.count()).select_from(Feriado)) == 26
    assert sessao.scalars(select(Feriado).where(Feriado.data == date(2026, 6, 4))).one()


# --- Marcações --------------------------------------------------------------------------------


def test_marcacao_unica_por_trabalhador_e_dia(sessao):
    t = _trabalhador(sessao)
    p = _codigo(sessao, "P")
    sessao.add(Marcacao(trabalhador=t, data=date(2027, 1, 4), codigo=p))
    sessao.flush()
    sessao.add(Marcacao(trabalhador=t, data=date(2027, 1, 4), codigo=p))
    with pytest.raises(IntegrityError):
        sessao.flush()


def test_marcacao_tem_zero_horas_extra_por_defeito_e_guarda_decimais(sessao):
    t = _trabalhador(sessao)
    sessao.add(Marcacao(trabalhador=t, data=date(2027, 1, 4), codigo=_codigo(sessao, "P")))
    sessao.add(
        Marcacao(
            trabalhador=t,
            data=date(2027, 1, 5),
            codigo=_codigo(sessao, "PF"),
            horas_extra=Decimal("1.5"),
        )
    )
    sessao.commit()
    sessao.expire_all()
    horas = [m.horas_extra for m in sessao.scalars(select(Marcacao).order_by(Marcacao.data))]
    assert horas == [Decimal("0"), Decimal("1.5")]


def test_marcacao_exige_trabalhador_existente(sessao):
    sessao.add(Marcacao(trabalhador_id=999, data=date(2027, 1, 4), codigo=_codigo(sessao, "P")))
    with pytest.raises(IntegrityError):
        sessao.flush()


# --- Trabalhadores, salários e parâmetros -----------------------------------------------------


def test_numero_de_trabalhador_unico(sessao):
    _trabalhador(sessao, numero=7)
    sessao.add(Trabalhador(numero=7, nome="Outro"))
    with pytest.raises(IntegrityError):
        sessao.flush()


def test_excecoes_vazias_e_trabalhador_sem_empresa(sessao):
    t = _trabalhador(sessao)
    assert t.empresa is None
    assert t.ativo is True
    assert t.exc_subsidio_alimentacao is None
    assert t.exc_ajuda_custo_franca is None
    assert t.exc_prevencao is None
    assert t.exc_valor_hora_extra is None


def test_valores_sao_decimais_exatos(sessao):
    t = _trabalhador(sessao, exc_subsidio_alimentacao=Decimal("0.1"))
    t.exc_ajuda_custo_franca = Decimal("0.2")
    sessao.commit()
    sessao.expire_all()
    assert t.exc_subsidio_alimentacao + t.exc_ajuda_custo_franca == Decimal("0.3")


def test_salario_em_vigor(sessao):
    t = _trabalhador(sessao)
    t.salarios.append(SalarioBase(inicio_vigencia=date(2026, 1, 1), valor=Decimal("1000")))
    t.salarios.append(SalarioBase(inicio_vigencia=date(2027, 6, 1), valor=Decimal("1100")))
    sessao.flush()
    assert salario_em_vigor(sessao, t.id, date(2025, 12, 31)) is None
    assert salario_em_vigor(sessao, t.id, date(2027, 5, 31)).valor == Decimal("1000")
    assert salario_em_vigor(sessao, t.id, date(2027, 6, 1)).valor == Decimal("1100")


def test_parametros_em_vigor_e_valores_por_omissao(sessao):
    empresa = Empresa(nome="Empresa Teste")
    empresa.parametros.append(ParametrosEmpresa(inicio_vigencia=date(2026, 1, 1)))
    empresa.parametros.append(
        ParametrosEmpresa(inicio_vigencia=date(2027, 1, 1), subsidio_alimentacao_dia=Decimal("9"))
    )
    sessao.add(empresa)
    sessao.flush()

    assert parametros_em_vigor(sessao, empresa.id, date(2025, 1, 1)) is None
    antigos = parametros_em_vigor(sessao, empresa.id, date(2026, 12, 31))
    novos = parametros_em_vigor(sessao, empresa.id, date(2027, 1, 1))
    assert novos.subsidio_alimentacao_dia == Decimal("9")

    # Valores definidos na especificação ...
    assert antigos.horas_semanais == Decimal("40")
    assert antigos.divisor_salario == Decimal("30")
    assert antigos.acrescimo_he_primeira_hora == Decimal("0.25")
    assert antigos.acrescimo_he_horas_seguintes == Decimal("0.375")
    assert antigos.acrescimo_he_descanso_feriado == Decimal("0.50")
    # ... e os que só o utilizador pode preencher ficam vazios.
    assert antigos.subsidio_alimentacao_dia is None
    assert antigos.ajuda_custo_franca_dia is None
    assert antigos.prevencao_dia is None
    assert antigos.limite_isencao_subsidio_dia is None
    assert antigos.limite_isencao_ajuda_custo_dia is None
    assert antigos.limite_horas_extra_mes is None


def test_uma_so_linha_de_parametros_por_empresa_e_data(sessao):
    empresa = Empresa(nome="Empresa Teste")
    empresa.parametros.append(ParametrosEmpresa(inicio_vigencia=date(2026, 1, 1)))
    empresa.parametros.append(ParametrosEmpresa(inicio_vigencia=date(2026, 1, 1)))
    sessao.add(empresa)
    with pytest.raises(IntegrityError):
        sessao.flush()
