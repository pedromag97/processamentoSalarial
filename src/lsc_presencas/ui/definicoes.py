"""Colunas de cada tabela editável. É aqui que se acrescenta ou muda um campo nos ecrãs."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..modelos import (
    AJUDA_CUSTO_NAO,
    AJUDA_CUSTO_SIM,
    AJUDA_CUSTO_ZONA,
    FERIADO_MUNICIPAL,
    FERIADO_NACIONAL,
    FOLHA_BAIXA,
    FOLHA_FALTA,
    FOLHA_FERIAS,
    FOLHA_NADA,
    FOLHA_TRABALHO,
    GER_MENSAL,
    GER_QUANTIDADE_FRANCA,
    GER_QUANTIDADE_MANUAL,
    GER_QUANTIDADE_PREVENCAO,
    GER_QUANTIDADE_TRABALHO,
    GER_SEMANAL,
    GER_UNITARIO,
    PAIS_FRANCA,
    PAIS_PORTUGAL,
    Cliente,
    Empresa,
    Trabalhador,
    Viatura,
    Zona,
)
from .tabela import BOOL, COR, DATA, DECIMAL, ESCOLHA, INTEIRO, Coluna

PAISES = [(PAIS_PORTUGAL, "Portugal"), (PAIS_FRANCA, "França")]
TIPOS_FERIADO = [(FERIADO_NACIONAL, "Nacional"), (FERIADO_MUNICIPAL, "Municipal")]
AJUDAS_CUSTO = [
    (AJUDA_CUSTO_NAO, "Não"),
    (AJUDA_CUSTO_SIM, "Sim"),
    (AJUDA_CUSTO_ZONA, "Conforme a zona"),
]
CONTA_NA_FOLHA = [
    (FOLHA_NADA, "Não conta"),
    (FOLHA_TRABALHO, "Dia trabalhado"),
    (FOLHA_FERIAS, "Férias"),
    (FOLHA_BAIXA, "Baixa"),
    (FOLHA_FALTA, "Falta"),
]
BASES_GER = [
    (GER_UNITARIO, "Por unidade"),
    (GER_MENSAL, "Do mês (÷ dias de trabalho)"),
    (GER_SEMANAL, "Da semana (÷ 7)"),
]
QUANTIDADES_GER = [
    (GER_QUANTIDADE_MANUAL, "Escreve-se em cada mês"),
    (GER_QUANTIDADE_TRABALHO, "Dias trabalhados da grelha"),
    (GER_QUANTIDADE_FRANCA, "Dias trabalhados em França da grelha"),
    (GER_QUANTIDADE_PREVENCAO, "Dias de prevenção da grelha"),
]


def _fixas(opcoes):
    return lambda _sessao: opcoes


def empresas(sessao: Session):
    return list(sessao.execute(select(Empresa.id, Empresa.nome).order_by(Empresa.nome)).all())


def clientes(sessao: Session):
    return list(sessao.execute(select(Cliente.id, Cliente.codigo).order_by(Cliente.codigo)).all())


def viaturas(sessao: Session):
    return list(sessao.execute(select(Viatura.id, Viatura.codigo).order_by(Viatura.codigo)).all())


def zonas(sessao: Session):
    return list(sessao.execute(select(Zona.id, Zona.nome).order_by(Zona.nome)).all())


COLUNAS_EMPRESA = [
    Coluna("nome", "Nome", obrigatorio=True),
    Coluna("nipc", "NIPC"),
    Coluna("morada", "Morada"),
    Coluna("logotipo", "Logótipo (caminho do ficheiro)"),
]

COLUNAS_CLIENTE = [
    Coluna("codigo", "Código", obrigatorio=True),
    Coluna("nome", "Nome completo"),
]

COLUNAS_VIATURA = [
    Coluna("codigo", "Código / matrícula", obrigatorio=True),
    Coluna("descricao", "Descrição"),
]

COLUNAS_ZONA = [
    Coluna("nome", "Nome", obrigatorio=True),
    Coluna("pais", "País", ESCOLHA, obrigatorio=True, escolhas=_fixas(PAISES)),
]

COLUNAS_CODIGO = [
    Coluna("codigo", "Código", obrigatorio=True),
    Coluna("descricao", "Significado", obrigatorio=True),
    Coluna("cor", "Cor", COR, obrigatorio=True, dica="Cor da célula na grelha, em #RRGGBB."),
    Coluna("ordem", "Ordem", INTEIRO, obrigatorio=True),
    Coluna("ativo", "Ativo", BOOL),
    Coluna("conta_trabalhado", "Conta como trabalhado", BOOL),
    Coluna("subsidio_alimentacao", "Subsídio de alimentação", BOOL),
    Coluna(
        "ajuda_custo_franca",
        "Ajuda de custo França",
        ESCOLHA,
        obrigatorio=True,
        escolhas=_fixas(AJUDAS_CUSTO),
        dica="«Conforme a zona»: só quando a zona da marcação é em França.",
    ),
    Coluna("desconta_salario", "Desconta salário base", BOOL),
    Coluna("soma_prevencao", "Soma prevenção", BOOL),
    Coluna(
        "conta_folha",
        "Conta na folha de salário",
        ESCOLHA,
        escolhas=_fixas(CONTA_NA_FOLHA),
        dica="Dia trabalhado e férias pagam-se; baixa e falta descontam um dia; "
        "«Não conta» não paga nem desconta.",
    ),
]

COLUNAS_FERIADO = [
    Coluna("data", "Data", DATA, obrigatorio=True),
    Coluna("nome", "Nome", obrigatorio=True),
    Coluna("tipo", "Tipo", ESCOLHA, obrigatorio=True, escolhas=_fixas(TIPOS_FERIADO)),
    Coluna("pais", "País", ESCOLHA, obrigatorio=True, escolhas=_fixas(PAISES)),
]

_DICA_ACRESCIMO = "Em fração: 0,25 = +25%."
_DICA_LIMITE = "Valor por dia, a confirmar com o contabilista."

COLUNAS_PARAMETROS = [
    Coluna("empresa_id", "Empresa", ESCOLHA, obrigatorio=True, escolhas=empresas),
    Coluna("inicio_vigencia", "Em vigor desde", DATA, obrigatorio=True),
    Coluna("subsidio_alimentacao_dia", "Subsídio alim. / dia (€)", DECIMAL, aviso_vazio=True),
    Coluna("ajuda_custo_franca_dia", "Ajuda de custo França / dia (€)", DECIMAL, aviso_vazio=True),
    Coluna("prevencao_dia", "Prevenção / dia (€)", DECIMAL, aviso_vazio=True),
    Coluna("horas_semanais", "Horas semanais", DECIMAL, obrigatorio=True),
    Coluna("divisor_salario", "Divisor do salário", DECIMAL, obrigatorio=True),
    Coluna(
        "acrescimo_he_primeira_hora",
        "HE dia útil, 1.ª hora",
        DECIMAL,
        obrigatorio=True,
        dica=_DICA_ACRESCIMO,
    ),
    Coluna(
        "acrescimo_he_horas_seguintes",
        "HE dia útil, horas seguintes",
        DECIMAL,
        obrigatorio=True,
        dica=_DICA_ACRESCIMO,
    ),
    Coluna(
        "acrescimo_he_descanso_feriado",
        "HE descanso / feriado",
        DECIMAL,
        obrigatorio=True,
        dica=_DICA_ACRESCIMO,
    ),
    Coluna(
        "limite_isencao_subsidio_dia",
        "Limite isenção subsídio / dia (€)",
        DECIMAL,
        aviso_vazio=True,
        dica=_DICA_LIMITE,
    ),
    Coluna(
        "limite_isencao_ajuda_custo_dia",
        "Limite isenção ajuda de custo / dia (€)",
        DECIMAL,
        aviso_vazio=True,
        dica=_DICA_LIMITE,
    ),
    Coluna(
        "limite_horas_extra_mes",
        "Alerta de horas extra / mês",
        DECIMAL,
        dica="Vazio = sem alerta.",
    ),
    Coluna(
        "taxa_seguranca_social",
        "Taxa de Segurança Social",
        DECIMAL,
        aviso_vazio=True,
        dica="Escreva 0,11 ou 11% (as duas dão 11%). A confirmar com o contabilista.",
        fracao=True,
    ),
]


def salario_atual(trabalhador: Trabalhador):
    return trabalhador.salarios[-1].valor if trabalhador.salarios else None


COLUNAS_TRABALHADOR = [
    Coluna("numero", "Nº", INTEIRO, obrigatorio=True),
    Coluna("nome", "Nome", obrigatorio=True),
    Coluna("empresa_id", "Empresa", ESCOLHA, escolhas=empresas, aviso_vazio=True),
    Coluna("cliente_id", "Cliente", ESCOLHA, escolhas=clientes),
    Coluna("viatura_id", "Viatura", ESCOLHA, escolhas=viaturas),
    Coluna("zona_id", "Zona", ESCOLHA, escolhas=zonas),
    Coluna("data_admissao", "Admissão", DATA),
    Coluna("data_saida", "Saída", DATA),
    Coluna("ativo", "Ativo", BOOL),
]

COLUNA_SALARIO_ATUAL = Coluna(
    "salario_atual",
    "Salário base (€)",
    DECIMAL,
    obter=salario_atual,
    aviso_vazio=True,
    dica="Edita-se na ficha do trabalhador.",
)

_DICA_EXCECAO = "Vazio = usa o valor da empresa."

COLUNAS_EXCECOES = [
    Coluna(
        "exc_subsidio_alimentacao", "Subsídio de alimentação / dia (€)", DECIMAL, dica=_DICA_EXCECAO
    ),
    Coluna(
        "exc_ajuda_custo_franca", "Ajuda de custo França / dia (€)", DECIMAL, dica=_DICA_EXCECAO
    ),
    Coluna("exc_prevencao", "Prevenção / dia (€)", DECIMAL, dica=_DICA_EXCECAO),
    Coluna(
        "exc_valor_hora_extra",
        "Valor / hora extra (€)",
        DECIMAL,
        dica="Vazio = calculado a partir do salário base. Os acréscimos aplicam-se na mesma.",
    ),
]

COLUNAS_SALARIO = [
    Coluna("inicio_vigencia", "Em vigor desde", DATA, obrigatorio=True),
    Coluna("valor", "Salário base mensal (€)", DECIMAL, obrigatorio=True),
    Coluna(
        "duodecimo_ferias",
        "Duodécimo de férias (€)",
        DECIMAL,
        dica="Valor do subsídio de férias pago em cada mês. Vazio = não recebe em duodécimos.",
    ),
    Coluna(
        "duodecimo_natal",
        "Duodécimo de Natal (€)",
        DECIMAL,
        dica="Valor do subsídio de Natal pago em cada mês. Vazio = não recebe em duodécimos.",
    ),
]

COLUNAS_LINHA_GER = [
    Coluna("ordem", "Ordem", INTEIRO, obrigatorio=True),
    Coluna("nome", "Ajuda", obrigatorio=True),
    Coluna("unidade", "Unidade", obrigatorio=True, dica="Por exemplo: dia, noite, hora."),
    Coluna("valor", "Valor (€)", DECIMAL, aviso_vazio=True),
    Coluna(
        "base",
        "O valor é",
        ESCOLHA,
        obrigatorio=True,
        escolhas=_fixas(BASES_GER),
        dica="«Do mês»: o valor divide-se pelos dias de trabalho do mês. «Da semana»: por 7.",
    ),
    Coluna(
        "quantidade_de",
        "Quantidade",
        ESCOLHA,
        obrigatorio=True,
        escolhas=_fixas(QUANTIDADES_GER),
    ),
    Coluna("ativo", "Ativa", BOOL),
]


TIPOS_LANCAMENTO = [
    ("adiantamento", "Adiantamento"),
    ("desconto", "Desconto"),
    ("premio", "Prémio"),
    ("outro", "Outro"),
]


def trabalhadores(sessao: Session):
    linhas = sessao.execute(
        select(Trabalhador.id, Trabalhador.nome, Trabalhador.numero).order_by(Trabalhador.nome)
    )
    return [(id_, f"{nome} (n.º {numero})") for id_, nome, numero in linhas]


def empresa_do_lancamento(lancamento):
    t = lancamento.trabalhador
    return t.empresa.nome if t is not None and t.empresa is not None else None


COLUNAS_LANCAMENTO = [
    Coluna("trabalhador_id", "Trabalhador", ESCOLHA, obrigatorio=True, escolhas=trabalhadores),
    Coluna("empresa", "Empresa", obter=empresa_do_lancamento),
    Coluna("tipo", "Tipo", ESCOLHA, obrigatorio=True, escolhas=_fixas(TIPOS_LANCAMENTO)),
    Coluna("descricao", "Descrição", obrigatorio=True),
    Coluna(
        "valor",
        "Valor (€)",
        DECIMAL,
        obrigatorio=True,
        dica="Positivo soma ao total; negativo subtrai (ex.: adiantamento de 100 € = -100).",
    ),
]


def preparar_trabalhador(trabalhador: Trabalhador, sessao: Session) -> None:
    """Valores iniciais de um trabalhador novo: o nº interno seguinte."""
    maximo = sessao.scalar(select(func.max(Trabalhador.numero))) or 0
    trabalhador.numero = maximo + 1
    trabalhador.ativo = True
