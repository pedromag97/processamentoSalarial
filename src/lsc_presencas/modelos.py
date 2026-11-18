"""Modelo de dados (SQLAlchemy 2.x).

Convenções:
- valores monetários, taxas e horas são `Decimal`, guardados como texto para não perder exatidão;
- um campo de valor vazio (None) significa "não definido": nunca se inventa um valor por omissão;
- tabelas com vigência (`ParametrosEmpresa`, `SalarioBase`) usam `inicio_vigencia`: aplica-se a
  linha com a data de início mais recente que não seja posterior ao dia em causa.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Valor(TypeDecorator):
    """Decimal exato, guardado como texto (o SQLite não tem tipo decimal)."""

    impl = String(24)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


# --- Tabelas de apoio -------------------------------------------------------------------------


class Empresa(Base):
    __tablename__ = "empresa"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
    nipc: Mapped[str | None] = mapped_column(String(20))
    morada: Mapped[str | None] = mapped_column(String(250))
    logotipo: Mapped[str | None] = mapped_column(String(250))

    parametros: Mapped[list["ParametrosEmpresa"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Empresa {self.nome}>"


class Cliente(Base):
    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nome: Mapped[str | None] = mapped_column(String(120))


class Viatura(Base):
    __tablename__ = "viatura"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    descricao: Mapped[str | None] = mapped_column(String(120))


class Zona(Base):
    """Obra/zona. O país decide, por exemplo, se a prevenção dá ajuda de custo França."""

    __tablename__ = "zona"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    pais: Mapped[str] = mapped_column(String(2), default="FR")


PAIS_PORTUGAL = "PT"
PAIS_FRANCA = "FR"


# --- Trabalhadores ----------------------------------------------------------------------------


class Trabalhador(Base):
    __tablename__ = "trabalhador"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, unique=True)
    nome: Mapped[str] = mapped_column(String(120), index=True)
    # A empresa pode ficar vazia logo após a importação, até ser atribuída em massa.
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    viatura_id: Mapped[int | None] = mapped_column(ForeignKey("viatura.id"))
    zona_id: Mapped[int | None] = mapped_column(ForeignKey("zona.id"))
    data_admissao: Mapped[date | None] = mapped_column(Date)
    data_saida: Mapped[date | None] = mapped_column(Date)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Valores de exceção: vazio = usa o valor global da empresa.
    exc_subsidio_alimentacao: Mapped[Decimal | None] = mapped_column(Valor)
    exc_ajuda_custo_franca: Mapped[Decimal | None] = mapped_column(Valor)
    exc_prevencao: Mapped[Decimal | None] = mapped_column(Valor)
    exc_valor_hora_extra: Mapped[Decimal | None] = mapped_column(Valor)

    empresa: Mapped[Empresa | None] = relationship()
    cliente: Mapped[Cliente | None] = relationship()
    viatura: Mapped[Viatura | None] = relationship()
    zona: Mapped[Zona | None] = relationship()
    salarios: Mapped[list["SalarioBase"]] = relationship(
        back_populates="trabalhador",
        cascade="all, delete-orphan",
        order_by="SalarioBase.inicio_vigencia",
    )
    marcacoes: Mapped[list["Marcacao"]] = relationship(
        back_populates="trabalhador", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Trabalhador {self.numero} {self.nome}>"


class SalarioBase(Base):
    """Salário base mensal com vigência, para que um aumento não altere meses anteriores."""

    __tablename__ = "salario_base"
    __table_args__ = (UniqueConstraint("trabalhador_id", "inicio_vigencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trabalhador_id: Mapped[int] = mapped_column(ForeignKey("trabalhador.id"))
    inicio_vigencia: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Valor)

    trabalhador: Mapped[Trabalhador] = relationship(back_populates="salarios")


# --- Presenças --------------------------------------------------------------------------------

AJUDA_CUSTO_NAO = "nao"
AJUDA_CUSTO_SIM = "sim"
AJUDA_CUSTO_ZONA = "zona"  # só quando a zona da marcação é em França


class CodigoPresenca(Base):
    """Código de presença. Todos os efeitos no cálculo são atributos editáveis."""

    __tablename__ = "codigo_presenca"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True)
    descricao: Mapped[str] = mapped_column(String(120))
    cor: Mapped[str] = mapped_column(String(7), default="#FFFFFF")
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    conta_trabalhado: Mapped[bool] = mapped_column(Boolean, default=False)
    subsidio_alimentacao: Mapped[bool] = mapped_column(Boolean, default=False)
    ajuda_custo_franca: Mapped[str] = mapped_column(String(4), default=AJUDA_CUSTO_NAO)
    desconta_salario: Mapped[bool] = mapped_column(Boolean, default=False)
    soma_prevencao: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<CodigoPresenca {self.codigo}>"


class Marcacao(Base):
    __tablename__ = "marcacao"
    __table_args__ = (UniqueConstraint("trabalhador_id", "data"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trabalhador_id: Mapped[int] = mapped_column(ForeignKey("trabalhador.id"))
    data: Mapped[date] = mapped_column(Date, index=True)
    codigo_id: Mapped[int] = mapped_column(ForeignKey("codigo_presenca.id"))
    horas_extra: Mapped[Decimal] = mapped_column(Valor, default=Decimal("0"))
    # Copiados da ficha do trabalhador no momento da marcação; editáveis.
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    viatura_id: Mapped[int | None] = mapped_column(ForeignKey("viatura.id"))
    zona_id: Mapped[int | None] = mapped_column(ForeignKey("zona.id"))
    nota: Mapped[str | None] = mapped_column(String(250))

    trabalhador: Mapped[Trabalhador] = relationship(back_populates="marcacoes")
    codigo: Mapped[CodigoPresenca] = relationship()
    cliente: Mapped[Cliente | None] = relationship()
    viatura: Mapped[Viatura | None] = relationship()
    zona: Mapped[Zona | None] = relationship()


FERIADO_NACIONAL = "nacional"
FERIADO_MUNICIPAL = "municipal"


class Feriado(Base):
    __tablename__ = "feriado"
    __table_args__ = (UniqueConstraint("data", "pais"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[date] = mapped_column(Date, index=True)
    nome: Mapped[str] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(10), default=FERIADO_NACIONAL)
    pais: Mapped[str] = mapped_column(String(2), default=PAIS_PORTUGAL)


TIPOS_LANCAMENTO = ("adiantamento", "desconto", "premio", "outro")


class LancamentoManual(Base):
    __tablename__ = "lancamento_manual"

    id: Mapped[int] = mapped_column(primary_key=True)
    trabalhador_id: Mapped[int] = mapped_column(ForeignKey("trabalhador.id"))
    ano: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(15))
    descricao: Mapped[str] = mapped_column(String(250))
    valor: Mapped[Decimal] = mapped_column(Valor)  # positivo soma, negativo subtrai

    trabalhador: Mapped[Trabalhador] = relationship()


# --- Parâmetros, fecho e auditoria ------------------------------------------------------------


class ParametrosEmpresa(Base):
    """Parâmetros de cálculo por empresa, com data de início de vigência.

    Os valores em euros e os limites de isenção ficam vazios até serem preenchidos na app.
    """

    __tablename__ = "parametros_empresa"
    __table_args__ = (UniqueConstraint("empresa_id", "inicio_vigencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"))
    inicio_vigencia: Mapped[date] = mapped_column(Date)

    subsidio_alimentacao_dia: Mapped[Decimal | None] = mapped_column(Valor)
    ajuda_custo_franca_dia: Mapped[Decimal | None] = mapped_column(Valor)
    prevencao_dia: Mapped[Decimal | None] = mapped_column(Valor)

    horas_semanais: Mapped[Decimal] = mapped_column(Valor, default=Decimal("40"))
    divisor_salario: Mapped[Decimal] = mapped_column(Valor, default=Decimal("30"))
    acrescimo_he_primeira_hora: Mapped[Decimal] = mapped_column(Valor, default=Decimal("0.25"))
    acrescimo_he_horas_seguintes: Mapped[Decimal] = mapped_column(Valor, default=Decimal("0.375"))
    acrescimo_he_descanso_feriado: Mapped[Decimal] = mapped_column(Valor, default=Decimal("0.50"))

    limite_isencao_subsidio_dia: Mapped[Decimal | None] = mapped_column(Valor)
    limite_isencao_ajuda_custo_dia: Mapped[Decimal | None] = mapped_column(Valor)
    limite_horas_extra_mes: Mapped[Decimal | None] = mapped_column(Valor)

    empresa: Mapped[Empresa] = relationship(back_populates="parametros")


FECHO_ABERTO = "aberto"
FECHO_FECHADO = "fechado"


class FechoMes(Base):
    __tablename__ = "fecho_mes"
    __table_args__ = (UniqueConstraint("empresa_id", "ano", "mes"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"))
    ano: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(10), default=FECHO_ABERTO)
    data: Mapped[datetime | None] = mapped_column(DateTime)
    utilizador: Mapped[str | None] = mapped_column(String(80))
    nota: Mapped[str | None] = mapped_column(String(250))
    # Fotografia tirada no fecho (JSON): parâmetros, feriados e códigos usados nesse mês.
    fotografia: Mapped[str | None] = mapped_column(Text)

    empresa: Mapped[Empresa] = relationship()
    linhas: Mapped[list["FechoTrabalhador"]] = relationship(
        back_populates="fecho", cascade="all, delete-orphan", order_by="FechoTrabalhador.numero"
    )


class FechoTrabalhador(Base):
    """Fotografia do mapa de um trabalhador no momento do fecho (rubricas, contagens e dias).

    É daqui que saem o Excel e os PDF de um mês fechado, para não mudarem se depois se alterar
    um salário, um parâmetro ou o nome de alguém.
    """

    __tablename__ = "fecho_trabalhador"
    __table_args__ = (UniqueConstraint("fecho_id", "trabalhador_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fecho_id: Mapped[int] = mapped_column(ForeignKey("fecho_mes.id"))
    trabalhador_id: Mapped[int] = mapped_column(ForeignKey("trabalhador.id"))
    numero: Mapped[int] = mapped_column(Integer)
    nome: Mapped[str] = mapped_column(String(120))
    total: Mapped[Decimal] = mapped_column(Valor)
    dados: Mapped[str] = mapped_column(Text)  # JSON do mapa (ver mapa.py)

    fecho: Mapped[FechoMes] = relationship(back_populates="linhas")


class Auditoria(Base):
    """Registo de alterações: quem, quando, valor antigo e valor novo (em JSON)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    quando: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    utilizador: Mapped[str] = mapped_column(String(80))
    entidade: Mapped[str] = mapped_column(String(40), index=True)
    entidade_id: Mapped[int | None] = mapped_column(Integer)
    acao: Mapped[str] = mapped_column(String(20))
    valor_antigo: Mapped[str | None] = mapped_column(Text)
    valor_novo: Mapped[str | None] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(String(250))
