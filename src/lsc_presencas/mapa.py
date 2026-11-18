"""Mapa de pré-processamento de uma empresa num mês: o que o Excel e os PDF mostram.

O mesmo `MapaMes` serve para a pré-visualização no ecrã de fecho, para o Excel e para os PDF,
e é o que fica guardado (em JSON) quando o mês é fechado. Assim os totais batem sempre certo.
"""

import json
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import calculo
from .consultas import parametros_em_vigor
from .modelos import (
    PAIS_PORTUGAL,
    CodigoPresenca,
    Empresa,
    Feriado,
    Marcacao,
    Trabalhador,
)
from .preprocessamento import CAMPOS_PARAMETROS, calcular_trabalhador

MESES = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]

CHAVES_HORAS_EXTRA = (
    calculo.HE_PRIMEIRA_HORA,
    calculo.HE_HORAS_SEGUINTES,
    calculo.HE_DESCANSO_FERIADO,
)


ROTULOS_PARAMETROS = {
    "subsidio_alimentacao_dia": "Subsídio de alimentação por dia (€)",
    "ajuda_custo_franca_dia": "Ajuda de custo França por dia (€)",
    "prevencao_dia": "Prevenção por dia (€)",
    "horas_semanais": "Horas semanais",
    "divisor_salario": "Divisor do salário (dias)",
    "acrescimo_he_primeira_hora": "Acréscimo das horas extra em dia útil, 1.ª hora",
    "acrescimo_he_horas_seguintes": "Acréscimo das horas extra em dia útil, horas seguintes",
    "acrescimo_he_descanso_feriado": "Acréscimo das horas extra em descanso ou feriado",
    "limite_isencao_subsidio_dia": "Limite de isenção do subsídio de alimentação por dia (€)",
    "limite_isencao_ajuda_custo_dia": "Limite de isenção da ajuda de custo por dia (€)",
    "limite_horas_extra_mes": "Alerta de horas extra por mês (horas)",
}


def nome_do_mes(ano: int, mes: int) -> str:
    return f"{MESES[mes - 1]} de {ano}"


@dataclass(frozen=True)
class DiaMapa:
    data: date
    codigo: str
    horas_extra: Decimal = calculo.ZERO
    cliente: str | None = None
    viatura: str | None = None
    zona: str | None = None
    nota: str | None = None


@dataclass
class MapaTrabalhador:
    trabalhador_id: int
    numero: int
    nome: str
    cliente: str | None  # cliente principal do mês
    zona: str | None  # zona principal do mês
    resultado: calculo.Resultado
    dias: list[DiaMapa] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.resultado.total

    @property
    def base_processada(self) -> Decimal:
        """Salário base do período menos os descontos por faltas e baixas."""
        r = self.resultado
        return r.total_de(calculo.SALARIO_BASE) + r.total_de(calculo.DESCONTO_SALARIO)

    def lancamentos(self, tipo: str) -> Decimal:
        return sum(
            (
                r.total
                for r in self.resultado.rubricas
                if r.chave == calculo.LANCAMENTO and r.tipo == tipo
            ),
            calculo.ZERO,
        )

    def valor_horas_extra(self) -> Decimal:
        return sum((self.resultado.total_de(c) for c in CHAVES_HORAS_EXTRA), calculo.ZERO)


@dataclass
class MapaMes:
    empresa_id: int
    empresa: str
    nipc: str | None
    morada: str | None
    logotipo: str | None
    ano: int
    mes: int
    codigos: list[tuple[str, str]]  # (código, significado), pela ordem da tabela
    parametros: dict[str, Decimal | None] | None  # None = sem parâmetros em vigor
    feriados: list[tuple[date, str]]
    trabalhadores: list[MapaTrabalhador] = field(default_factory=list)
    fechado: bool = False
    fechado_em: datetime | None = None
    fechado_por: str | None = None

    @property
    def total(self) -> Decimal:
        return sum((t.total for t in self.trabalhadores), calculo.ZERO)

    @property
    def periodo(self) -> str:
        return f"{self.ano}-{self.mes:02d}"

    @property
    def titulo_mes(self) -> str:
        return nome_do_mes(self.ano, self.mes)


# --- Construir a partir da base de dados ------------------------------------------------------


def _principal(valores) -> str | None:
    contagem = Counter(v for v in valores if v)
    return contagem.most_common(1)[0][0] if contagem else None


def construir(sessao: Session, empresa_id: int, ano: int, mes: int) -> MapaMes:
    """Calcula o mapa do mês com os dados que estão agora na base de dados.

    Entram os trabalhadores da empresa que estão ativos com contrato nesse mês, e também quem
    tiver marcações ou lançamentos no mês (mesmo inativo ou fora do contrato, para dar alerta).
    """
    empresa = sessao.get(Empresa, empresa_id)
    if empresa is None:
        raise ValueError("A empresa não existe.")
    primeiro, ultimo = date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])
    parametros = parametros_em_vigor(sessao, empresa_id, ultimo)

    mapa = MapaMes(
        empresa_id=empresa.id,
        empresa=empresa.nome,
        nipc=empresa.nipc,
        morada=empresa.morada,
        logotipo=empresa.logotipo,
        ano=ano,
        mes=mes,
        codigos=[
            (c, d)
            for c, d in sessao.execute(
                select(CodigoPresenca.codigo, CodigoPresenca.descricao).order_by(
                    CodigoPresenca.ordem, CodigoPresenca.codigo
                )
            )
        ],
        parametros=(
            None if parametros is None else {c: getattr(parametros, c) for c in CAMPOS_PARAMETROS}
        ),
        feriados=[
            (d, n)
            for d, n in sessao.execute(
                select(Feriado.data, Feriado.nome)
                .where(Feriado.pais == PAIS_PORTUGAL, Feriado.data.between(primeiro, ultimo))
                .order_by(Feriado.data)
            )
        ],
    )

    trabalhadores = sessao.scalars(
        select(Trabalhador).where(Trabalhador.empresa_id == empresa_id).order_by(Trabalhador.numero)
    ).all()
    for t in trabalhadores:
        marcacoes = sessao.scalars(
            select(Marcacao)
            .where(Marcacao.trabalhador_id == t.id, Marcacao.data.between(primeiro, ultimo))
            .order_by(Marcacao.data)
        ).all()
        resultado = calcular_trabalhador(sessao, t, ano, mes)
        tem_lancamentos = any(r.chave == calculo.LANCAMENTO for r in resultado.rubricas)
        if not marcacoes and not tem_lancamentos and not (t.ativo and resultado.dias_contrato):
            continue
        dias = [
            DiaMapa(
                data=m.data,
                codigo=m.codigo.codigo,
                horas_extra=m.horas_extra or calculo.ZERO,
                cliente=m.cliente.codigo if m.cliente else None,
                viatura=m.viatura.codigo if m.viatura else None,
                zona=m.zona.nome if m.zona else None,
                nota=m.nota,
            )
            for m in marcacoes
        ]
        mapa.trabalhadores.append(
            MapaTrabalhador(
                trabalhador_id=t.id,
                numero=t.numero,
                nome=t.nome,
                cliente=_principal(d.cliente for d in dias)
                or (t.cliente.codigo if t.cliente else None),
                zona=_principal(d.zona for d in dias) or (t.zona.nome if t.zona else None),
                resultado=resultado,
                dias=dias,
            )
        )
    return mapa


# --- JSON (fotografia do fecho) ---------------------------------------------------------------


def _dec(valor) -> str | None:
    return None if valor is None else str(valor)


def _ler_dec(texto) -> Decimal | None:
    return None if texto is None else Decimal(texto)


def resultado_para_dict(r: calculo.Resultado) -> dict:
    return {
        "ano": r.ano,
        "mes": r.mes,
        "dias_contrato": r.dias_contrato,
        "contagens": r.contagens,
        "rubricas": [
            {
                "chave": x.chave,
                "descricao": x.descricao,
                "quantidade": _dec(x.quantidade),
                "valor_unitario": _dec(x.valor_unitario),
                "total": _dec(x.total),
                "formula": x.formula,
                "isento": _dec(x.isento),
                "sujeito": _dec(x.sujeito),
                "tipo": x.tipo,
            }
            for x in r.rubricas
        ],
        "alertas": [
            {
                "chave": a.chave,
                "nivel": a.nivel,
                "mensagem": a.mensagem,
                "datas": [d.isoformat() for d in a.datas],
            }
            for a in r.alertas
        ],
    }


def resultado_de_dict(d: dict) -> calculo.Resultado:
    return calculo.Resultado(
        ano=d["ano"],
        mes=d["mes"],
        dias_contrato=d["dias_contrato"],
        contagens=dict(d["contagens"]),
        rubricas=[
            calculo.Rubrica(
                chave=x["chave"],
                descricao=x["descricao"],
                quantidade=_ler_dec(x["quantidade"]),
                valor_unitario=_ler_dec(x["valor_unitario"]),
                total=_ler_dec(x["total"]),
                formula=x["formula"],
                isento=_ler_dec(x["isento"]),
                sujeito=_ler_dec(x["sujeito"]),
                tipo=x.get("tipo"),
            )
            for x in d["rubricas"]
        ],
        alertas=[
            calculo.Alerta(
                a["chave"],
                a["nivel"],
                a["mensagem"],
                tuple(date.fromisoformat(x) for x in a["datas"]),
            )
            for a in d["alertas"]
        ],
    )


def trabalhador_para_json(t: MapaTrabalhador) -> str:
    return json.dumps(
        {
            "cliente": t.cliente,
            "zona": t.zona,
            "resultado": resultado_para_dict(t.resultado),
            "dias": [
                {
                    "data": d.data.isoformat(),
                    "codigo": d.codigo,
                    "horas_extra": str(d.horas_extra),
                    "cliente": d.cliente,
                    "viatura": d.viatura,
                    "zona": d.zona,
                    "nota": d.nota,
                }
                for d in t.dias
            ],
        },
        ensure_ascii=False,
    )


def trabalhador_de_json(trabalhador_id: int, numero: int, nome: str, texto: str) -> MapaTrabalhador:
    d = json.loads(texto)
    return MapaTrabalhador(
        trabalhador_id=trabalhador_id,
        numero=numero,
        nome=nome,
        cliente=d["cliente"],
        zona=d["zona"],
        resultado=resultado_de_dict(d["resultado"]),
        dias=[
            DiaMapa(
                data=date.fromisoformat(x["data"]),
                codigo=x["codigo"],
                horas_extra=Decimal(x["horas_extra"]),
                cliente=x["cliente"],
                viatura=x["viatura"],
                zona=x["zona"],
                nota=x["nota"],
            )
            for x in d["dias"]
        ],
    )


def cabecalho_para_json(mapa: MapaMes) -> str:
    return json.dumps(
        {
            "empresa": mapa.empresa,
            "nipc": mapa.nipc,
            "morada": mapa.morada,
            "logotipo": mapa.logotipo,
            "codigos": mapa.codigos,
            "parametros": (
                None
                if mapa.parametros is None
                else {c: _dec(v) for c, v in mapa.parametros.items()}
            ),
            "feriados": [[d.isoformat(), n] for d, n in mapa.feriados],
        },
        ensure_ascii=False,
    )


def cabecalho_de_json(empresa_id: int, ano: int, mes: int, texto: str) -> MapaMes:
    d = json.loads(texto)
    return MapaMes(
        empresa_id=empresa_id,
        empresa=d["empresa"],
        nipc=d["nipc"],
        morada=d["morada"],
        logotipo=d["logotipo"],
        ano=ano,
        mes=mes,
        codigos=[(c, s) for c, s in d["codigos"]],
        parametros=(
            None
            if d["parametros"] is None
            else {c: _ler_dec(v) for c, v in d["parametros"].items()}
        ),
        feriados=[(date.fromisoformat(x), n) for x, n in d["feriados"]],
    )
