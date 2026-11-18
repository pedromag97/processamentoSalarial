"""Cálculo do pré-processamento salarial de um trabalhador num mês civil.

Módulo puro: não conhece a base de dados nem a interface. Recebe dados simples e devolve as
rubricas (com a fórmula usada em texto), as contagens e os alertas.

Nenhum valor legal está aqui: valores por dia, limites e acréscimos vêm sempre de `Parametros`.
Um valor em falta (None) nunca é substituído por zero: a rubrica fica sem total e gera um alerta.

Pressupostos assumidos (a confirmar com o Pedro e o contabilista; ver PROGRESSO.md):
- o proporcional de entrada/saída usa dias de calendário de contrato e nunca passa do salário base;
- os limites de isenção são valores por dia;
- em dia útil, a "1.ª hora" de horas extra conta-se por dia;
- dia de descanso ou feriado = sábado, domingo ou um dia do conjunto `feriados` recebido;
- o valor/hora de exceção do trabalhador substitui o valor/hora calculado; os acréscimos mantêm-se;
- a ajuda de custo "conforme zona" (prevenção) só conta quando a zona da marcação é em França.
"""

from calendar import monthrange
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

AJUDA_NAO = "nao"
AJUDA_SIM = "sim"
AJUDA_ZONA = "zona"

NIVEL_ERRO = "erro"  # impede um resultado completo
NIVEL_AVISO = "aviso"
NIVEL_CONFIRMAR = "confirmar"  # precisa de confirmação do utilizador

CENTIMO = Decimal("0.01")
ZERO = Decimal("0")
UM = Decimal("1")


# --- Entradas ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Codigo:
    codigo: str
    conta_trabalhado: bool = False
    subsidio_alimentacao: bool = False
    ajuda_custo_franca: str = AJUDA_NAO
    desconta_salario: bool = False
    soma_prevencao: bool = False


@dataclass(frozen=True)
class Dia:
    """Uma marcação: o código do dia, as horas extra e se a zona da marcação é em França."""

    data: date
    codigo: Codigo
    horas_extra: Decimal = ZERO
    zona_em_franca: bool = False


@dataclass(frozen=True)
class DadosTrabalhador:
    salario_base: Decimal | None = None
    data_admissao: date | None = None
    data_saida: date | None = None
    ativo: bool = True
    exc_subsidio_alimentacao: Decimal | None = None
    exc_ajuda_custo_franca: Decimal | None = None
    exc_prevencao: Decimal | None = None
    exc_valor_hora_extra: Decimal | None = None


@dataclass(frozen=True)
class Parametros:
    subsidio_alimentacao_dia: Decimal | None = None
    ajuda_custo_franca_dia: Decimal | None = None
    prevencao_dia: Decimal | None = None
    horas_semanais: Decimal = Decimal("40")
    divisor_salario: Decimal = Decimal("30")
    acrescimo_he_primeira_hora: Decimal = Decimal("0.25")
    acrescimo_he_horas_seguintes: Decimal = Decimal("0.375")
    acrescimo_he_descanso_feriado: Decimal = Decimal("0.50")
    limite_isencao_subsidio_dia: Decimal | None = None
    limite_isencao_ajuda_custo_dia: Decimal | None = None
    limite_horas_extra_mes: Decimal | None = None


@dataclass(frozen=True)
class Lancamento:
    tipo: str
    descricao: str
    valor: Decimal


# --- Saídas -----------------------------------------------------------------------------------

SALARIO_BASE = "salario_base"
DESCONTO_SALARIO = "desconto_salario"
SUBSIDIO_ALIMENTACAO = "subsidio_alimentacao"
AJUDA_CUSTO_FRANCA = "ajuda_custo_franca"
PREVENCAO = "prevencao"
HE_PRIMEIRA_HORA = "he_primeira_hora"
HE_HORAS_SEGUINTES = "he_horas_seguintes"
HE_DESCANSO_FERIADO = "he_descanso_feriado"
LANCAMENTO = "lancamento"


@dataclass(frozen=True)
class Rubrica:
    chave: str
    descricao: str
    quantidade: Decimal | None
    valor_unitario: Decimal | None
    total: Decimal | None  # None = não foi possível calcular (falta um valor)
    formula: str
    isento: Decimal | None = None  # None = sem separação (não se aplica ou falta o limite)
    sujeito: Decimal | None = None


@dataclass(frozen=True)
class Alerta:
    chave: str
    nivel: str
    mensagem: str
    datas: tuple[date, ...] = ()


@dataclass
class Resultado:
    ano: int
    mes: int
    dias_contrato: int
    contagens: dict[str, int] = field(default_factory=dict)
    rubricas: list[Rubrica] = field(default_factory=list)
    alertas: list[Alerta] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        """Total ilíquido estimado (antes de IRS e TSU): soma das rubricas calculadas."""
        return sum((r.total for r in self.rubricas if r.total is not None), ZERO)

    @property
    def incompleto(self) -> bool:
        """True se alguma rubrica ficou por calcular (o total não inclui essa rubrica)."""
        return any(r.total is None for r in self.rubricas)

    @property
    def horas_extra(self) -> Decimal:
        chaves = (HE_PRIMEIRA_HORA, HE_HORAS_SEGUINTES, HE_DESCANSO_FERIADO)
        return sum((r.quantidade for r in self.rubricas if r.chave in chaves), ZERO)

    def rubrica(self, chave: str) -> Rubrica | None:
        return next((r for r in self.rubricas if r.chave == chave), None)

    def total_de(self, chave: str) -> Decimal:
        return sum(
            (r.total for r in self.rubricas if r.chave == chave and r.total is not None), ZERO
        )

    def chaves_de_alerta(self) -> set[str]:
        return {a.chave for a in self.alertas}


# --- Utilitários ------------------------------------------------------------------------------


def arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _pt(valor: Decimal) -> str:
    """Número em formato português, sem zeros a mais (ex.: 37,5)."""
    texto = f"{Decimal(valor):f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _eur(valor: Decimal) -> str:
    return f"{arredondar(valor):.2f}".replace(".", ",") + " €"


def _perc(valor: Decimal) -> str:
    return _pt(valor * 100) + "%"


def valor_hora(salario_base: Decimal, horas_semanais: Decimal) -> Decimal:
    """Valor/hora = (base × 12) / (52 × horas semanais)."""
    return salario_base * 12 / (52 * horas_semanais)


def descanso_ou_feriado(dia: date, feriados: set[date]) -> bool:
    return dia.weekday() >= 5 or dia in feriados


# --- Cálculo ----------------------------------------------------------------------------------


def calcular_mes(
    ano: int,
    mes: int,
    trabalhador: DadosTrabalhador,
    parametros: Parametros | None,
    dias: Iterable[Dia],
    feriados: Iterable[date] = (),
    lancamentos: Iterable[Lancamento] = (),
) -> Resultado:
    """Pré-processamento de um trabalhador num mês.

    `parametros` são os da empresa em vigor nesse mês (None se não existirem) e
    `trabalhador.salario_base` é o salário em vigor nesse mês (None se não estiver definido).
    Marcações fora do mês são ignoradas; fora do período de contrato geram um alerta.
    """
    feriados = set(feriados)
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, monthrange(ano, mes)[1])
    inicio = max(primeiro, trabalhador.data_admissao or primeiro)
    fim = min(ultimo, trabalhador.data_saida or ultimo)
    dias_contrato = max((fim - inicio).days + 1, 0)
    mes_completo = inicio == primeiro and fim == ultimo

    resultado = Resultado(ano=ano, mes=mes, dias_contrato=dias_contrato)
    alertas = resultado.alertas

    do_mes: dict[date, Dia] = {}
    fora_contrato: list[date] = []
    for dia in dias:
        if not primeiro <= dia.data <= ultimo:
            continue
        if dia.data in do_mes or dia.data in fora_contrato:
            raise ValueError(f"Há mais de uma marcação no dia {dia.data:%d/%m/%Y}.")
        if inicio <= dia.data <= fim:
            do_mes[dia.data] = dia
        else:
            fora_contrato.append(dia.data)
    marcacoes = [do_mes[d] for d in sorted(do_mes)]

    if fora_contrato:
        alertas.append(
            Alerta(
                "marcacao_fora_contrato",
                NIVEL_ERRO,
                f"{len(fora_contrato)} marcação(ões) antes da admissão ou depois da saída "
                "(não entram no cálculo).",
                tuple(sorted(fora_contrato)),
            )
        )
    if parametros is None:
        alertas.append(
            Alerta(
                "parametros_em_falta",
                NIVEL_ERRO,
                "Não há parâmetros da empresa em vigor neste mês.",
            )
        )
        # Sem parâmetros, as rubricas com valor por dia ficam sem total (e com alerta próprio).
        parametros = Parametros()
    base = trabalhador.salario_base
    if base is None and trabalhador.ativo and dias_contrato:
        alertas.append(Alerta("sem_salario_base", NIVEL_ERRO, "Trabalhador sem salário base."))

    # 1. Contagens
    resultado.contagens = dict(Counter(m.codigo.codigo for m in marcacoes))

    # 2. Salário base processado
    if dias_contrato:
        _salario(resultado, base, parametros, marcacoes, dias_contrato, mes_completo)

    # 3 a 5. Subsídio de alimentação, ajuda de custo França e prevenção
    _valor_por_dia(
        resultado,
        SUBSIDIO_ALIMENTACAO,
        "Subsídio de alimentação",
        sum(1 for m in marcacoes if m.codigo.subsidio_alimentacao),
        trabalhador.exc_subsidio_alimentacao,
        parametros.subsidio_alimentacao_dia,
        parametros.limite_isencao_subsidio_dia,
        com_isencao=True,
    )
    _valor_por_dia(
        resultado,
        AJUDA_CUSTO_FRANCA,
        "Ajuda de custo França",
        sum(1 for m in marcacoes if _da_ajuda_de_custo(m)),
        trabalhador.exc_ajuda_custo_franca,
        parametros.ajuda_custo_franca_dia,
        parametros.limite_isencao_ajuda_custo_dia,
        com_isencao=True,
    )
    _valor_por_dia(
        resultado,
        PREVENCAO,
        "Prevenção",
        sum(1 for m in marcacoes if m.codigo.soma_prevencao),
        trabalhador.exc_prevencao,
        parametros.prevencao_dia,
        None,
        com_isencao=False,
    )

    # 6. Horas extra
    _horas_extra(resultado, trabalhador, parametros, marcacoes, feriados)

    # 7. Lançamentos manuais
    for lanc in lancamentos:
        resultado.rubricas.append(
            Rubrica(
                LANCAMENTO,
                f"{lanc.tipo.capitalize()}: {lanc.descricao}",
                None,
                None,
                arredondar(Decimal(lanc.valor)),
                "Lançamento manual",
            )
        )

    # 9. Restantes validações
    em_falta = [
        primeiro + timedelta(days=n)
        for n in range((ultimo - primeiro).days + 1)
        if inicio <= primeiro + timedelta(days=n) <= fim
        and not descanso_ou_feriado(primeiro + timedelta(days=n), feriados)
        and primeiro + timedelta(days=n) not in do_mes
    ]
    if em_falta and trabalhador.ativo:
        alertas.append(
            Alerta(
                "dias_uteis_sem_marcacao",
                NIVEL_AVISO,
                f"{len(em_falta)} dia(s) útil(eis) sem marcação.",
                tuple(em_falta),
            )
        )
    trabalho_em_feriado = [
        m.data for m in marcacoes if m.data in feriados and m.codigo.conta_trabalhado
    ]
    if trabalho_em_feriado:
        alertas.append(
            Alerta(
                "trabalho_em_feriado",
                NIVEL_CONFIRMAR,
                f"{len(trabalho_em_feriado)} dia(s) de feriado marcado(s) como trabalhado(s).",
                tuple(trabalho_em_feriado),
            )
        )
    return resultado


def _da_ajuda_de_custo(m: Dia) -> bool:
    tipo = m.codigo.ajuda_custo_franca
    return tipo == AJUDA_SIM or (tipo == AJUDA_ZONA and m.zona_em_franca)


def _salario(resultado, base, parametros, marcacoes, dias_contrato, mes_completo) -> None:
    divisor = parametros.divisor_salario
    dias_desconto = [m for m in marcacoes if m.codigo.desconta_salario]
    por_codigo = Counter(m.codigo.codigo for m in dias_desconto)
    detalhe = ", ".join(f"{n} {c}" for c, n in sorted(por_codigo.items()))

    if base is None:
        resultado.rubricas.append(
            Rubrica(
                SALARIO_BASE,
                "Salário base",
                Decimal(dias_contrato),
                None,
                None,
                "Falta o salário base do trabalhador.",
            )
        )
        return

    por_dia = base / divisor
    if mes_completo:
        do_periodo = base
        formula = f"Mês completo: {_eur(base)}"
    else:
        do_periodo = min(base, por_dia * dias_contrato)
        formula = (
            f"Proporcional: {_eur(base)} / {_pt(divisor)} × {dias_contrato} dias de contrato"
            " (máximo: salário base)"
        )
    do_periodo = arredondar(do_periodo)
    resultado.rubricas.append(
        Rubrica(
            SALARIO_BASE,
            "Salário base",
            Decimal(dias_contrato),
            arredondar(por_dia),
            do_periodo,
            formula,
        )
    )
    if dias_desconto:
        # O desconto nunca ultrapassa o salário do período.
        desconto = min(arredondar(por_dia * len(dias_desconto)), do_periodo)
        resultado.rubricas.append(
            Rubrica(
                DESCONTO_SALARIO,
                f"Desconto por faltas e baixas ({detalhe})",
                Decimal(len(dias_desconto)),
                arredondar(por_dia),
                -desconto,
                f"{_eur(base)} / {_pt(divisor)} × {len(dias_desconto)} dias",
            )
        )


def _valor_por_dia(
    resultado, chave, descricao, dias, excecao, global_, limite, *, com_isencao
) -> None:
    if not dias:
        return
    origem = "valor de exceção do trabalhador" if excecao is not None else "valor da empresa"
    valor = excecao if excecao is not None else global_
    if valor is None:
        resultado.rubricas.append(
            Rubrica(
                chave, descricao, Decimal(dias), None, None, "Falta o valor por dia nos parâmetros."
            )
        )
        resultado.alertas.append(
            Alerta(
                f"{chave}_sem_valor",
                NIVEL_ERRO,
                f"{descricao}: falta o valor por dia nos parâmetros da empresa.",
            )
        )
        return

    total = arredondar(valor * dias)
    formula = f"{dias} dias × {_eur(valor)} ({origem})"
    isento = sujeito = None
    if com_isencao:
        if limite is None:
            resultado.alertas.append(
                Alerta(
                    f"{chave}_sem_limite_isencao",
                    NIVEL_AVISO,
                    f"{descricao}: falta o limite de isenção; mostra-se só o total.",
                )
            )
        else:
            isento = arredondar(min(valor, limite) * dias)
            sujeito = total - isento
            formula += f"; isento até {_eur(limite)} por dia"
    resultado.rubricas.append(
        Rubrica(chave, descricao, Decimal(dias), valor, total, formula, isento, sujeito)
    )


def _horas_extra(resultado, trabalhador, parametros, marcacoes, feriados) -> None:
    horas = {HE_PRIMEIRA_HORA: ZERO, HE_HORAS_SEGUINTES: ZERO, HE_DESCANSO_FERIADO: ZERO}
    sem_trabalho = []
    for m in marcacoes:
        h = Decimal(m.horas_extra or 0)
        if h <= 0:
            continue
        if not m.codigo.conta_trabalhado:
            sem_trabalho.append(m.data)
        if descanso_ou_feriado(m.data, feriados):
            horas[HE_DESCANSO_FERIADO] += h
        else:
            primeira = min(h, UM)
            horas[HE_PRIMEIRA_HORA] += primeira
            horas[HE_HORAS_SEGUINTES] += h - primeira
    total_horas = sum(horas.values(), ZERO)
    if not total_horas:
        return

    if trabalhador.exc_valor_hora_extra is not None:
        hora = trabalhador.exc_valor_hora_extra
        origem = f"valor/hora de exceção {_eur(hora)}"
    elif trabalhador.salario_base is not None:
        hora = valor_hora(trabalhador.salario_base, parametros.horas_semanais)
        origem = (
            f"valor/hora = {_eur(trabalhador.salario_base)} × 12 / (52 × "
            f"{_pt(parametros.horas_semanais)}) = {_eur(hora)}"
        )
    else:
        hora = None
        origem = "Falta o salário base para calcular o valor/hora."

    tipos = [
        (HE_PRIMEIRA_HORA, "Horas extra em dia útil — 1.ª hora", "acrescimo_he_primeira_hora"),
        (
            HE_HORAS_SEGUINTES,
            "Horas extra em dia útil — horas seguintes",
            "acrescimo_he_horas_seguintes",
        ),
        (
            HE_DESCANSO_FERIADO,
            "Horas extra em dia de descanso ou feriado",
            "acrescimo_he_descanso_feriado",
        ),
    ]
    for chave, descricao, campo in tipos:
        if not horas[chave]:
            continue
        acrescimo = getattr(parametros, campo)
        if hora is None:
            rubrica = Rubrica(chave, descricao, horas[chave], None, None, origem)
        else:
            unitario = hora * (UM + acrescimo)
            rubrica = Rubrica(
                chave,
                descricao,
                horas[chave],
                unitario,
                arredondar(horas[chave] * unitario),
                f"{_pt(horas[chave])} h × {_eur(hora)} × (1 + {_perc(acrescimo)}); {origem}",
            )
        resultado.rubricas.append(rubrica)

    limite = parametros.limite_horas_extra_mes
    if limite is not None and total_horas > limite:
        resultado.alertas.append(
            Alerta(
                "horas_extra_acima_do_limite",
                NIVEL_AVISO,
                f"{_pt(total_horas)} horas extra no mês (limite: {_pt(limite)}).",
            )
        )
    if sem_trabalho:
        resultado.alertas.append(
            Alerta(
                "horas_extra_sem_trabalho",
                NIVEL_CONFIRMAR,
                f"{len(sem_trabalho)} dia(s) com horas extra num código que não conta como "
                "trabalhado.",
                tuple(sem_trabalho),
            )
        )
