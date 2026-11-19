"""Folha de salário de um trabalhador num mês: do vencimento ao valor a pagar.

Módulo puro, como `calculo.py`: não conhece a base de dados nem a interface. Segue a folha
«Simulação salário» que o Pedro usa em Excel:

    Bloco RC (vai ao recibo)        Bloco GER (ajudas, à parte)
      Presenças                       uma linha por ajuda combinada com o trabalhador
      Subsídio de alimentação         (por dia, por noite, por hora…)
      Subsídios de férias e de Natal
      Férias
      Baixa e faltas (descontam)
      IRS (valor escrito à mão)
      Segurança Social (calculada)

    Líquido = Vencimento RC + total GER          A pagar = Líquido + adiantamentos

Regras (decididas pelo Pedro em 2026-11-19, a confirmar com o contabilista):
- valor por dia = vencimento base / dias de trabalho do mês (dias úteis, sem feriados);
- as Presenças pagam só os dias trabalhados; as férias pagam-se ao mesmo valor por dia;
- cada dia de baixa ou de falta desconta, além disso, um dia de vencimento (como na folha Excel);
- os subsídios de férias e de Natal pagam-se em duodécimos só a quem os tem na ficha, na
  proporção dos dias trabalhados e de férias;
- o IRS é o valor que o contabilista indicar em cada mês;
- a Segurança Social é a taxa dos parâmetros sobre o bloco RC antes dos descontos; do subsídio
  de alimentação só entra a parte acima do limite de isenção (sem limite definido, não entra).

Nenhum valor legal está aqui: taxa, limite e valores por dia vêm sempre de fora. Um valor em
falta nunca é substituído por zero: a linha fica sem total e gera um alerta.
"""

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .calculo import NIVEL_AVISO, NIVEL_ERRO, ZERO, Alerta, _eur, _perc, _pt, arredondar

# Como se chega ao valor unitário de uma linha GER a partir do valor combinado.
UNITARIO = "unitario"  # o valor já é por unidade (por noite, por hora…)
MENSAL = "mensal"  # valor do mês inteiro: divide-se pelos dias de trabalho do mês
SEMANAL = "semanal"  # valor de uma semana inteira: divide-se por 7
BASES_GER = (UNITARIO, MENSAL, SEMANAL)

PRESENCAS = "presencas"
SUBSIDIO_ALIMENTACAO = "subsidio_alimentacao"
SUBSIDIO_FERIAS = "subsidio_ferias"
SUBSIDIO_NATAL = "subsidio_natal"
FERIAS = "ferias"
BAIXA = "baixa"
FALTAS = "faltas"
IRS = "irs"
SEGURANCA_SOCIAL = "seguranca_social"
GER = "ger"

SETE = Decimal(7)


# --- Entradas ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class LinhaGer:
    """Uma ajuda combinada com o trabalhador e a quantidade do mês."""

    nome: str
    unidade: str  # texto livre curto: «dia», «noite», «hora»
    valor: Decimal | None
    base: str = UNITARIO
    quantidade: Decimal = ZERO


@dataclass(frozen=True)
class Movimento:
    """Adiantamento ou acerto depois do líquido. Negativo = já recebido, desconta do a pagar."""

    descricao: str
    valor: Decimal


@dataclass(frozen=True)
class DadosFolha:
    dias_trabalho_mes: int
    vencimento_base: Decimal | None
    dias_trabalhados: int = 0
    dias_ferias: int = 0
    dias_baixa: int = 0
    dias_faltas: int = 0
    subsidio_alimentacao_dia: Decimal | None = None
    limite_isencao_subsidio_dia: Decimal | None = None
    duodecimo_ferias: Decimal | None = None  # None = não recebe em duodécimos
    duodecimo_natal: Decimal | None = None
    irs: Decimal | None = None  # None = ainda não foi escrito neste mês
    taxa_seguranca_social: Decimal | None = None
    linhas_ger: tuple[LinhaGer, ...] = ()
    movimentos: tuple[Movimento, ...] = ()


# --- Saídas -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Linha:
    chave: str
    descricao: str
    valor_mes: Decimal | None  # coluna «Total venc.»: o valor do mês inteiro, quando existe
    valor_unitario: Decimal | None  # coluna «Valor por dia» (ou por noite, por hora)
    quantidade: Decimal | None  # coluna «Dias trabalhados»
    total: Decimal | None  # None = não foi possível calcular (falta um valor)
    formula: str
    unidade: str = "dia"


@dataclass
class Folha:
    dias_trabalho_mes: int
    vencimento_base: Decimal | None
    linhas_rc: list[Linha] = field(default_factory=list)
    linhas_ger: list[Linha] = field(default_factory=list)
    movimentos: list[Movimento] = field(default_factory=list)
    base_seguranca_social: Decimal | None = None
    alertas: list[Alerta] = field(default_factory=list)

    @staticmethod
    def _soma(linhas: Iterable[Linha]) -> Decimal:
        return sum((linha.total for linha in linhas if linha.total is not None), ZERO)

    @property
    def vencimento_rc(self) -> Decimal:
        return self._soma(self.linhas_rc)

    @property
    def total_ger(self) -> Decimal:
        return self._soma(self.linhas_ger)

    @property
    def liquido(self) -> Decimal:
        return self.vencimento_rc + self.total_ger

    @property
    def total_movimentos(self) -> Decimal:
        return sum((arredondar(Decimal(m.valor)) for m in self.movimentos), ZERO)

    @property
    def a_pagar(self) -> Decimal:
        return self.liquido + self.total_movimentos

    @property
    def incompleta(self) -> bool:
        """True se alguma linha ficou por calcular (os totais não a incluem)."""
        return any(linha.total is None for linha in (*self.linhas_rc, *self.linhas_ger))

    def linha(self, chave: str) -> Linha | None:
        return next((linha for linha in self.linhas_rc if linha.chave == chave), None)

    def chaves_de_alerta(self) -> set[str]:
        return {a.chave for a in self.alertas}


# --- Cálculo ----------------------------------------------------------------------------------


def dias_de_trabalho(ano: int, mes: int, feriados: Iterable[date] = ()) -> int:
    """Dias úteis do mês: de segunda a sexta, menos os feriados que calhem nesses dias."""
    feriados = set(feriados)
    dias = (date(ano, mes, n) for n in range(1, monthrange(ano, mes)[1] + 1))
    return sum(1 for dia in dias if dia.weekday() < 5 and dia not in feriados)


def calcular_folha(dados: DadosFolha) -> Folha:
    folha = Folha(dados.dias_trabalho_mes, dados.vencimento_base, movimentos=list(dados.movimentos))
    alertas = folha.alertas
    for nome in ("dias_trabalhados", "dias_ferias", "dias_baixa", "dias_faltas"):
        if getattr(dados, nome) < 0:
            raise ValueError(f"{nome} não pode ser negativo.")
    if dados.dias_trabalho_mes <= 0:
        raise ValueError("O mês tem de ter pelo menos um dia de trabalho.")

    dias_mes = Decimal(dados.dias_trabalho_mes)
    base = dados.vencimento_base
    por_dia = None if base is None else base / dias_mes
    if base is None:
        alertas.append(Alerta("sem_salario_base", NIVEL_ERRO, "Trabalhador sem salário base."))

    marcados = dados.dias_trabalhados + dados.dias_ferias + dados.dias_baixa + dados.dias_faltas
    if marcados > dados.dias_trabalho_mes:
        alertas.append(
            Alerta(
                "dias_a_mais",
                NIVEL_AVISO,
                f"Há {marcados} dias marcados (trabalho, férias, baixa e faltas) num mês com "
                f"{dados.dias_trabalho_mes} dias de trabalho.",
            )
        )

    rc = folha.linhas_rc

    def por_dias(chave: str, descricao: str, dias: int, sinal: int = 1) -> None:
        """Linha «valor por dia × dias», com o valor por dia do vencimento base."""
        if por_dia is None:
            rc.append(
                Linha(chave, descricao, None, None, Decimal(dias), None, "Falta o salário base.")
            )
            return
        unitario = por_dia * sinal
        rc.append(
            Linha(
                chave,
                descricao,
                None,
                unitario,
                Decimal(dias),
                arredondar(unitario * dias),
                f"{_eur(base)} / {_pt(dias_mes)} dias de trabalho × {dias} dias",
            )
        )

    # 1. Presenças
    por_dias(PRESENCAS, "Presenças", dados.dias_trabalhados)

    # 2. Subsídio de alimentação
    sujeito_alimentacao = _alimentacao(dados, rc, alertas)

    # 3. Subsídios de férias e de Natal em duodécimos
    dias_com_subsidio = dados.dias_trabalhados + dados.dias_ferias
    for chave, descricao, duodecimo in (
        (SUBSIDIO_FERIAS, "Subsídio de férias (duodécimos)", dados.duodecimo_ferias),
        (SUBSIDIO_NATAL, "Subsídio de Natal (duodécimos)", dados.duodecimo_natal),
    ):
        if duodecimo is None:
            continue
        unitario = duodecimo / dias_mes
        rc.append(
            Linha(
                chave,
                descricao,
                duodecimo,
                unitario,
                Decimal(dias_com_subsidio),
                arredondar(unitario * dias_com_subsidio),
                f"{_eur(duodecimo)} / {_pt(dias_mes)} dias de trabalho × {dias_com_subsidio} dias"
                " (trabalhados e de férias)",
            )
        )

    # 4. Férias, baixa e faltas
    por_dias(FERIAS, "Férias", dados.dias_ferias)
    por_dias(BAIXA, "Baixa", dados.dias_baixa, sinal=-1)
    por_dias(FALTAS, "Faltas", dados.dias_faltas, sinal=-1)

    # 5. Base da Segurança Social: o bloco RC até aqui; do subsídio de alimentação, só a parte
    #    sujeita.
    base_ss = None
    if base is not None:
        base_ss = (
            sum(
                (linha.total for linha in rc if linha.chave != SUBSIDIO_ALIMENTACAO),
                ZERO,
            )
            + sujeito_alimentacao
        )
        base_ss = max(base_ss, ZERO)
    folha.base_seguranca_social = base_ss

    # 6. IRS (valor escrito à mão em cada mês)
    if dados.irs is None:
        alertas.append(
            Alerta("irs_por_preencher", NIVEL_AVISO, "IRS: falta escrever o valor do mês.")
        )
        rc.append(Linha(IRS, "IRS", None, None, None, ZERO, "Por preencher (conta como 0,00 €)."))
    else:
        if dados.irs < 0:
            raise ValueError("O IRS escreve-se como valor positivo; a folha é que o desconta.")
        irs = arredondar(dados.irs)
        rc.append(Linha(IRS, "IRS", irs, None, None, -irs, "Valor indicado para este mês."))

    # 7. Segurança Social
    taxa = dados.taxa_seguranca_social
    if taxa is None:
        alertas.append(
            Alerta(
                "sem_taxa_seguranca_social",
                NIVEL_ERRO,
                "Segurança Social: falta a taxa nos parâmetros da empresa.",
            )
        )
        rc.append(
            Linha(SEGURANCA_SOCIAL, "Segurança Social", None, None, None, None, "Falta a taxa.")
        )
    elif base_ss is None:
        rc.append(
            Linha(SEGURANCA_SOCIAL, "Segurança Social", None, None, None, None, "Falta a base.")
        )
    else:
        desconto = arredondar(base_ss * taxa)
        rc.append(
            Linha(
                SEGURANCA_SOCIAL,
                f"Segurança Social ({_perc(taxa)})",
                desconto,
                None,
                None,
                -desconto,
                f"{_perc(taxa)} × {_eur(base_ss)} (bloco RC antes dos descontos)",
            )
        )

    # 8. Bloco GER
    for linha in dados.linhas_ger:
        folha.linhas_ger.append(_linha_ger(linha, dias_mes, alertas))

    if not folha.incompleta and folha.vencimento_rc < 0:
        alertas.append(
            Alerta(
                "vencimento_negativo",
                NIVEL_AVISO,
                f"O vencimento RC dá negativo ({_eur(folha.vencimento_rc)}): confirmar as faltas "
                "e as baixas.",
            )
        )
    return folha


def _alimentacao(dados: DadosFolha, rc: list[Linha], alertas: list[Alerta]) -> Decimal:
    """Acrescenta a linha do subsídio de alimentação e devolve a parte sujeita a descontos."""
    dias = dados.dias_trabalhados
    valor = dados.subsidio_alimentacao_dia
    descricao = "Subsídio de alimentação"
    if not dias:
        return ZERO
    if valor is None:
        alertas.append(
            Alerta(
                "subsidio_alimentacao_sem_valor",
                NIVEL_ERRO,
                "Subsídio de alimentação: falta o valor por dia.",
            )
        )
        rc.append(
            Linha(
                SUBSIDIO_ALIMENTACAO, descricao, None, None, Decimal(dias), None, "Falta o valor."
            )
        )
        return ZERO
    total = arredondar(valor * dias)
    formula = f"{dias} dias × {_eur(valor)}"
    limite = dados.limite_isencao_subsidio_dia
    sujeito = ZERO
    if limite is None:
        alertas.append(
            Alerta(
                "subsidio_alimentacao_sem_limite_isencao",
                NIVEL_AVISO,
                "Subsídio de alimentação: falta o limite de isenção; não entra na base da "
                "Segurança Social.",
            )
        )
    else:
        sujeito = arredondar(max(valor - limite, ZERO) * dias)
        formula += f"; isento até {_eur(limite)} por dia"
    rc.append(Linha(SUBSIDIO_ALIMENTACAO, descricao, None, valor, Decimal(dias), total, formula))
    return sujeito


def _linha_ger(linha: LinhaGer, dias_mes: Decimal, alertas: list[Alerta]) -> Linha:
    if linha.base not in BASES_GER:
        raise ValueError(f"Base desconhecida na linha «{linha.nome}»: {linha.base!r}.")
    if linha.quantidade < 0:
        raise ValueError(f"A quantidade da linha «{linha.nome}» não pode ser negativa.")
    if linha.valor is None:
        if linha.quantidade:
            alertas.append(
                Alerta(
                    "ger_sem_valor",
                    NIVEL_ERRO,
                    f"{linha.nome}: tem quantidade no mês mas falta o valor combinado.",
                )
            )
            total = None
        else:
            total = ZERO
        return Linha(
            GER, linha.nome, None, None, linha.quantidade, total, "Falta o valor.", linha.unidade
        )

    if linha.base == MENSAL:
        unitario = linha.valor / dias_mes
        origem = f"{_eur(linha.valor)} / {_pt(dias_mes)} dias de trabalho"
        valor_mes = linha.valor
    elif linha.base == SEMANAL:
        unitario = linha.valor / SETE
        origem = f"{_eur(linha.valor)} / 7 dias"
        valor_mes = linha.valor
    else:
        unitario = linha.valor
        origem = _eur(linha.valor)
        valor_mes = None
    return Linha(
        GER,
        linha.nome,
        valor_mes,
        unitario,
        linha.quantidade,
        arredondar(unitario * linha.quantidade),
        f"{origem} × {_pt(linha.quantidade)} {linha.unidade}(s)",
        linha.unidade,
    )


# --- JSON (fotografia do fecho) ---------------------------------------------------------------


def _dec(valor: Decimal | None) -> str | None:
    return None if valor is None else str(valor)


def _ler(texto: str | None) -> Decimal | None:
    return None if texto is None else Decimal(texto)


_CAMPOS_VALOR = ("valor_mes", "valor_unitario", "quantidade", "total")


def _linha_para_dict(linha: Linha) -> dict:
    d = {"chave": linha.chave, "descricao": linha.descricao, "formula": linha.formula}
    d.update({campo: _dec(getattr(linha, campo)) for campo in _CAMPOS_VALOR})
    d["unidade"] = linha.unidade
    return d


def _linha_de_dict(d: dict) -> Linha:
    return Linha(
        chave=d["chave"],
        descricao=d["descricao"],
        formula=d["formula"],
        unidade=d["unidade"],
        **{campo: _ler(d[campo]) for campo in _CAMPOS_VALOR},
    )


def para_dict(folha: Folha) -> dict:
    """A folha tal como foi calculada, para guardar no fecho do mês."""
    return {
        "dias_trabalho_mes": folha.dias_trabalho_mes,
        "vencimento_base": _dec(folha.vencimento_base),
        "linhas_rc": [_linha_para_dict(x) for x in folha.linhas_rc],
        "linhas_ger": [_linha_para_dict(x) for x in folha.linhas_ger],
        "movimentos": [{"descricao": m.descricao, "valor": str(m.valor)} for m in folha.movimentos],
        "base_seguranca_social": _dec(folha.base_seguranca_social),
        "alertas": [
            {"chave": a.chave, "nivel": a.nivel, "mensagem": a.mensagem} for a in folha.alertas
        ],
    }


def de_dict(d: dict) -> Folha:
    return Folha(
        dias_trabalho_mes=d["dias_trabalho_mes"],
        vencimento_base=_ler(d["vencimento_base"]),
        linhas_rc=[_linha_de_dict(x) for x in d["linhas_rc"]],
        linhas_ger=[_linha_de_dict(x) for x in d["linhas_ger"]],
        movimentos=[Movimento(m["descricao"], Decimal(m["valor"])) for m in d["movimentos"]],
        base_seguranca_social=_ler(d["base_seguranca_social"]),
        alertas=[Alerta(a["chave"], a["nivel"], a["mensagem"]) for a in d["alertas"]],
    )
