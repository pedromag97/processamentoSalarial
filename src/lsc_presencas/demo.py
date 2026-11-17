"""Dados de demonstração com nomes fictícios, iguais em todos os PCs de desenvolvimento.

Não contém nenhum dado real de trabalhadores. Os valores em euros dos parâmetros ficam vazios
de propósito (não se inventam valores legais); os salários base são fictícios.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .dados_base import carregar_dados_base
from .modelos import (
    PAIS_FRANCA,
    PAIS_PORTUGAL,
    Cliente,
    CodigoPresenca,
    Empresa,
    LancamentoManual,
    Marcacao,
    ParametrosEmpresa,
    SalarioBase,
    Trabalhador,
    Viatura,
    Zona,
)

EMPRESAS = ["LOUSACABO CONSTRUÇÕES LDA", "+INNOVATION"]
CLIENTES = ["drp+", "drp++", "GG", "FD", "BA", "rm", "cgo"]
VIATURAS = ["ZC", "BR", "AD 81", "TS", "UX", "QN", "AE", "XV"]
ZONAS = [("45 Orleans", PAIS_FRANCA), ("64 Biarritz", PAIS_FRANCA), ("Portugal", PAIS_PORTUGAL)]

PROPRIOS = ["Abel", "Bruna", "Caetano", "Dália", "Eurico", "Filipa", "Gil", "Helga"]
APELIDOS = ["Demonstração", "Exemplo", "Fictício"]

MES_DEMO = (2027, 1)


def ja_tem_dados(sessao: Session) -> bool:
    return bool(sessao.scalar(select(func.count()).select_from(Trabalhador)))


def semear(sessao: Session) -> int:
    """Cria os dados de demonstração. Devolve o número de trabalhadores criados."""
    carregar_dados_base(sessao)

    empresas = [Empresa(nome=n) for n in EMPRESAS]
    clientes = [Cliente(codigo=c, nome=f"Cliente {c} (demo)") for c in CLIENTES]
    viaturas = [Viatura(codigo=v, descricao="Viatura de demonstração") for v in VIATURAS]
    zonas = [Zona(nome=n, pais=p) for n, p in ZONAS]
    sessao.add_all(empresas + clientes + viaturas + zonas)
    for empresa in empresas:
        # Só os parâmetros que a especificação define; os valores em euros ficam por preencher.
        empresa.parametros.append(ParametrosEmpresa(inicio_vigencia=date(2026, 1, 1)))

    codigos = {c.codigo: c for c in sessao.scalars(select(CodigoPresenca))}
    ano, mes = MES_DEMO
    trabalhadores = []
    numero = 0
    for apelido in APELIDOS:
        for proprio in PROPRIOS:
            numero += 1
            zona = zonas[numero % len(zonas)]
            t = Trabalhador(
                numero=numero,
                nome=f"{proprio} {apelido}",
                empresa=empresas[numero % 2],
                cliente=clientes[numero % len(clientes)],
                viatura=viaturas[numero % len(viaturas)] if numero % 3 else None,
                zona=zona,
                data_admissao=date(2025, 3, 1),
            )
            t.salarios.append(
                SalarioBase(
                    inicio_vigencia=date(2025, 3, 1), valor=Decimal(900 + 25 * (numero % 9))
                )
            )
            trabalhadores.append(t)
    # Casos especiais para os ecrãs e para os testes manuais.
    trabalhadores[0].data_admissao = date(ano, mes, 11)  # entrou a meio do mês
    trabalhadores[1].data_saida = date(ano, mes, 20)  # saiu a meio do mês
    trabalhadores[2].exc_subsidio_alimentacao = Decimal("7.50")  # valor de exceção fictício
    trabalhadores[-1].ativo = False
    trabalhadores[-1].data_saida = date(2026, 11, 30)
    sessao.add_all(trabalhadores)
    sessao.flush()

    dia = date(ano, mes, 1)
    while dia.month == mes:
        for t in trabalhadores:
            if not t.ativo or (t.data_admissao and dia < t.data_admissao):
                continue
            if t.data_saida and dia > t.data_saida:
                continue
            codigo = _codigo_do_dia(t, dia)
            if codigo is None:
                continue
            horas = Decimal("2") if (t.numero + dia.day) % 11 == 0 and codigo in ("P", "PF") else 0
            sessao.add(
                Marcacao(
                    trabalhador=t,
                    data=dia,
                    codigo=codigos[codigo],
                    horas_extra=Decimal(horas),
                    cliente=t.cliente,
                    viatura=t.viatura,
                    zona=t.zona,
                )
            )
        dia += timedelta(days=1)

    sessao.add(
        LancamentoManual(
            trabalhador=trabalhadores[3],
            ano=ano,
            mes=mes,
            tipo="adiantamento",
            descricao="Adiantamento (demo)",
            valor=Decimal("-100"),
        )
    )
    sessao.flush()
    return len(trabalhadores)


def _codigo_do_dia(t: Trabalhador, dia: date) -> str | None:
    em_franca = t.zona.pais == PAIS_FRANCA
    if dia == date(dia.year, 1, 1):
        return "DF" if em_franca else "FER"
    if dia.weekday() >= 5:
        return "DF" if em_franca else None
    if t.numero % 7 == 0 and 18 <= dia.day <= 22:
        return "FE"
    if t.numero % 10 == 0 and dia.day == 13:
        return "FI"
    if t.numero == 5 and dia.day >= 25:
        return "B"
    if t.numero % 8 == 0 and dia.day == 27:
        return "PR"
    return "PF" if em_franca else "P"
