"""Liga a base de dados à folha de salário: lê os dados de um trabalhador num mês, chama
`folha_salario` e grava os valores que se escrevem à mão (IRS e quantidades das linhas GER).

As contagens de dias vêm da grelha de presenças, pelo atributo «Conta na folha» de cada código.
Os adiantamentos e restantes lançamentos manuais do mês entram depois do líquido.
"""

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auditoria, bloqueios, concorrencia
from . import folha_salario as fs
from .consultas import parametros_em_vigor, salario_em_vigor
from .modelos import (
    AJUDA_CUSTO_SIM,
    AJUDA_CUSTO_ZONA,
    FOLHA_BAIXA,
    FOLHA_FALTA,
    FOLHA_FERIAS,
    FOLHA_TRABALHO,
    GER_MENSAL,
    GER_QUANTIDADE_FRANCA,
    GER_QUANTIDADE_MANUAL,
    GER_QUANTIDADE_PREVENCAO,
    GER_QUANTIDADE_TRABALHO,
    GER_UNITARIO,
    PAIS_FRANCA,
    FolhaMes,
    LancamentoManual,
    LinhaGer,
    Marcacao,
    QuantidadeGer,
    Trabalhador,
)
from .preprocessamento import feriados_do_mes
from .presencas import meses_fechados

ZERO = Decimal("0")


@dataclass
class FolhaTrabalhador:
    trabalhador_id: int
    numero: int
    nome: str
    ano: int
    mes: int
    folha: fs.Folha
    contagens: dict[str, int] = field(default_factory=dict)  # por código marcado na grelha
    # Para cada linha GER da folha, pela mesma ordem: (id da linha, a quantidade escreve-se à mão?)
    linhas_ger: list[tuple[int, bool]] = field(default_factory=list)
    irs: Decimal | None = None


def _limites(ano: int, mes: int) -> tuple[date, date]:
    return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])


def _em_franca(m: Marcacao) -> bool:
    """Dia trabalhado em França: o mesmo critério da ajuda de custo França dos códigos."""
    if m.codigo.conta_folha != FOLHA_TRABALHO:
        return False
    regra = m.codigo.ajuda_custo_franca
    if regra == AJUDA_CUSTO_ZONA:
        return m.zona is not None and m.zona.pais == PAIS_FRANCA
    return regra == AJUDA_CUSTO_SIM


def folha_do_trabalhador(
    sessao: Session, trabalhador: Trabalhador, ano: int, mes: int
) -> FolhaTrabalhador:
    """Folha de salário de um trabalhador num mês, com o que está agora na base de dados."""
    primeiro, ultimo = _limites(ano, mes)
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
    na_folha = Counter(m.codigo.conta_folha for m in marcacoes)
    # Quantidades das linhas GER que se contam da grelha (as outras escrevem-se à mão).
    da_grelha = {
        GER_QUANTIDADE_PREVENCAO: sum(1 for m in marcacoes if m.codigo.soma_prevencao),
        GER_QUANTIDADE_TRABALHO: na_folha[FOLHA_TRABALHO],
        GER_QUANTIDADE_FRANCA: sum(1 for m in marcacoes if _em_franca(m)),
    }

    registo = sessao.scalar(
        select(FolhaMes).where(
            FolhaMes.trabalhador_id == trabalhador.id, FolhaMes.ano == ano, FolhaMes.mes == mes
        )
    )
    irs = registo.irs if registo else None

    linhas = sessao.scalars(
        select(LinhaGer)
        .where(LinhaGer.trabalhador_id == trabalhador.id, LinhaGer.ativo.is_(True))
        .order_by(LinhaGer.ordem, LinhaGer.id)
    ).all()
    escritas = {
        q.linha_ger_id: q.quantidade
        for q in sessao.scalars(
            select(QuantidadeGer).where(
                QuantidadeGer.linha_ger_id.in_([x.id for x in linhas]),
                QuantidadeGer.ano == ano,
                QuantidadeGer.mes == mes,
            )
        )
    }
    linhas_ger = []
    for linha in linhas:
        if linha.quantidade_de in da_grelha:
            quantidade = Decimal(da_grelha[linha.quantidade_de])
        else:
            quantidade = escritas.get(linha.id, ZERO)
        linhas_ger.append(
            fs.LinhaGer(linha.nome, linha.unidade, linha.valor, linha.base, quantidade)
        )

    lancamentos = sessao.scalars(
        select(LancamentoManual)
        .where(
            LancamentoManual.trabalhador_id == trabalhador.id,
            LancamentoManual.ano == ano,
            LancamentoManual.mes == mes,
        )
        .order_by(LancamentoManual.id)
    ).all()

    subsidio = trabalhador.exc_subsidio_alimentacao
    if subsidio is None and parametros is not None:
        subsidio = parametros.subsidio_alimentacao_dia

    folha = fs.calcular_folha(
        fs.DadosFolha(
            dias_trabalho_mes=fs.dias_de_trabalho(ano, mes, feriados_do_mes(sessao, ano, mes)),
            vencimento_base=salario.valor if salario else None,
            dias_trabalhados=na_folha[FOLHA_TRABALHO],
            dias_ferias=na_folha[FOLHA_FERIAS],
            dias_baixa=na_folha[FOLHA_BAIXA],
            dias_faltas=na_folha[FOLHA_FALTA],
            subsidio_alimentacao_dia=subsidio,
            limite_isencao_subsidio_dia=(
                parametros.limite_isencao_subsidio_dia if parametros else None
            ),
            duodecimo_ferias=salario.duodecimo_ferias if salario else None,
            duodecimo_natal=salario.duodecimo_natal if salario else None,
            irs=irs,
            taxa_seguranca_social=parametros.taxa_seguranca_social if parametros else None,
            linhas_ger=tuple(linhas_ger),
            movimentos=tuple(
                fs.Movimento(f"{x.tipo.capitalize()}: {x.descricao}", x.valor) for x in lancamentos
            ),
        )
    )
    return FolhaTrabalhador(
        trabalhador_id=trabalhador.id,
        numero=trabalhador.numero,
        nome=trabalhador.nome,
        ano=ano,
        mes=mes,
        folha=folha,
        contagens=dict(Counter(m.codigo.codigo for m in marcacoes)),
        linhas_ger=[(linha.id, linha.quantidade_de not in da_grelha) for linha in linhas],
        irs=irs,
    )


def folhas_do_mes(sessao: Session, empresa_id: int, ano: int, mes: int) -> list[FolhaTrabalhador]:
    """As folhas dos trabalhadores de uma empresa: os ativos com contrato no mês e quem tiver
    marcações ou lançamentos nesse mês."""
    primeiro, ultimo = _limites(ano, mes)
    com_marcacoes = set(
        sessao.scalars(
            select(Marcacao.trabalhador_id)
            .where(Marcacao.data.between(primeiro, ultimo))
            .distinct()
        )
    )
    com_lancamentos = set(
        sessao.scalars(
            select(LancamentoManual.trabalhador_id)
            .where(LancamentoManual.ano == ano, LancamentoManual.mes == mes)
            .distinct()
        )
    )
    folhas = []
    for t in sessao.scalars(
        select(Trabalhador).where(Trabalhador.empresa_id == empresa_id).order_by(Trabalhador.numero)
    ):
        com_contrato = (
            t.ativo
            and (t.data_admissao is None or t.data_admissao <= ultimo)
            and (t.data_saida is None or t.data_saida >= primeiro)
        )
        if com_contrato or t.id in com_marcacoes or t.id in com_lancamentos:
            folhas.append(folha_do_trabalhador(sessao, t, ano, mes))
    return folhas


# --- As linhas GER habituais ------------------------------------------------------------------

# As seis linhas do bloco GER da folha Excel «Simulação salário»: (nome, unidade, base).
# Os valores combinam-se com cada trabalhador e escrevem-se na ficha: aqui não há nenhum.
LINHAS_GER_HABITUAIS = (
    ("Aj.PT (CH+VIAT+PROD)", "dia", GER_MENSAL),
    ("Aj.PT Desloq (por noite)", "noite", GER_UNITARIO),
    ("Aj.PT Banco de horas (sáb + horas)", "hora", GER_UNITARIO),
    ("Aj.ES (CH+VIAT+PROD)", "dia", GER_MENSAL),
    ("Aj.ES Desloq (por noite)", "noite", GER_UNITARIO),
    ("Aj.ES Banco de horas (sáb + horas)", "hora", GER_UNITARIO),
)


def criar_linhas_habituais(sessao: Session, empresa_id: int) -> int:
    """Dá as seis linhas GER do Excel (sem valor) aos trabalhadores da empresa que ainda não
    têm nenhuma linha. Quem já tem linhas, mesmo inativas, fica como está. Faz o commit e
    devolve o número de trabalhadores a que acrescentou linhas."""
    com_linhas = select(LinhaGer.trabalhador_id).distinct()

    def em_falta() -> list[Trabalhador]:
        return list(
            sessao.scalars(
                select(Trabalhador)
                .where(Trabalhador.empresa_id == empresa_id, Trabalhador.id.not_in(com_linhas))
                .order_by(Trabalhador.numero)
            )
        )

    try:
        if not em_falta():
            return 0
        concorrencia.fechar_ou_reabrir(sessao)  # um PC de cada vez, para não haver linhas a dobrar
        trabalhadores = em_falta()
        for t in trabalhadores:
            for ordem, (nome, unidade, base) in enumerate(LINHAS_GER_HABITUAIS, start=1):
                sessao.add(
                    LinhaGer(
                        trabalhador_id=t.id, ordem=ordem, nome=nome, unidade=unidade, base=base
                    )
                )
            auditoria.registar(
                sessao,
                "linha_ger",
                t.id,
                "criar",
                None,
                {"trabalhador": t.numero, "linhas": [x[0] for x in LINHAS_GER_HABITUAIS]},
            )
        sessao.commit()
        return len(trabalhadores)
    except Exception:
        sessao.rollback()
        raise


# --- Gravar os valores escritos à mão ---------------------------------------------------------


def _preparar_alteracao(sessao: Session, trabalhador_id: int, ano: int, mes: int) -> Trabalhador:
    concorrencia.alterar_marcacoes(sessao)  # espera por um fecho que esteja a decorrer
    bloqueios.exigir_livres(sessao, [trabalhador_id])
    trabalhador = sessao.get(Trabalhador, trabalhador_id)
    if trabalhador is None:
        raise ValueError("O trabalhador não existe.")
    if (trabalhador.empresa_id, ano, mes) in meses_fechados(sessao):
        raise ValueError(
            f"O mês {mes:02d}/{ano} está fechado para a empresa deste trabalhador. "
            "Reabra o mês para alterar a folha de salário."
        )
    return trabalhador


def gravar_irs(
    sessao: Session, trabalhador_id: int, ano: int, mes: int, valor: Decimal | None
) -> None:
    """Grava o IRS do mês (None = apagar o valor). Faz o commit."""
    try:
        if valor is not None and valor < 0:
            raise ValueError("O IRS escreve-se como valor positivo; a folha é que o desconta.")
        trabalhador = _preparar_alteracao(sessao, trabalhador_id, ano, mes)
        registo = sessao.scalar(
            select(FolhaMes).where(
                FolhaMes.trabalhador_id == trabalhador_id, FolhaMes.ano == ano, FolhaMes.mes == mes
            )
        )
        antigo = registo.irs if registo else None
        if antigo == valor:
            sessao.rollback()
            return
        if registo is None:
            registo = FolhaMes(trabalhador_id=trabalhador_id, ano=ano, mes=mes)
            sessao.add(registo)
        registo.irs = valor
        sessao.flush()
        contexto = {"trabalhador": trabalhador.numero, "mes": f"{ano}-{mes:02d}"}
        auditoria.registar(
            sessao,
            "folha_mes",
            registo.id,
            "alterar",
            {**contexto, "irs": antigo},
            {**contexto, "irs": valor},
        )
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise


def gravar_quantidade(
    sessao: Session, linha_ger_id: int, ano: int, mes: int, quantidade: Decimal
) -> None:
    """Grava a quantidade do mês de uma linha GER (dias, noites, horas). Faz o commit."""
    try:
        if quantidade < 0:
            raise ValueError("A quantidade não pode ser negativa.")
        linha = sessao.get(LinhaGer, linha_ger_id)
        if linha is None:
            raise ValueError("Essa linha já não existe na ficha do trabalhador.")
        if linha.quantidade_de != GER_QUANTIDADE_MANUAL:
            raise ValueError(f"A quantidade de «{linha.nome}» conta-se da grelha de presenças.")
        trabalhador = _preparar_alteracao(sessao, linha.trabalhador_id, ano, mes)
        registo = sessao.scalar(
            select(QuantidadeGer).where(
                QuantidadeGer.linha_ger_id == linha_ger_id,
                QuantidadeGer.ano == ano,
                QuantidadeGer.mes == mes,
            )
        )
        antiga = registo.quantidade if registo else ZERO
        if antiga == quantidade:
            sessao.rollback()
            return
        if registo is None:
            registo = QuantidadeGer(linha_ger_id=linha_ger_id, ano=ano, mes=mes)
            sessao.add(registo)
        registo.quantidade = quantidade
        sessao.flush()
        contexto = {
            "trabalhador": trabalhador.numero,
            "mes": f"{ano}-{mes:02d}",
            "linha": linha.nome,
        }
        auditoria.registar(
            sessao,
            "quantidade_ger",
            registo.id,
            "alterar",
            {**contexto, "quantidade": antiga},
            {**contexto, "quantidade": quantidade},
        )
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
