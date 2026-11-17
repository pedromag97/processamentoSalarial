"""Consultas de apoio ao modelo (vigências)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .modelos import ParametrosEmpresa, SalarioBase


def parametros_em_vigor(sessao: Session, empresa_id: int, dia: date) -> ParametrosEmpresa | None:
    """Parâmetros da empresa aplicáveis a um dia (None se não houver nenhuns em vigor)."""
    return sessao.scalars(
        select(ParametrosEmpresa)
        .where(ParametrosEmpresa.empresa_id == empresa_id, ParametrosEmpresa.inicio_vigencia <= dia)
        .order_by(ParametrosEmpresa.inicio_vigencia.desc())
        .limit(1)
    ).first()


def salario_em_vigor(sessao: Session, trabalhador_id: int, dia: date) -> SalarioBase | None:
    """Salário base do trabalhador aplicável a um dia (None se não estiver definido)."""
    return sessao.scalars(
        select(SalarioBase)
        .where(SalarioBase.trabalhador_id == trabalhador_id, SalarioBase.inicio_vigencia <= dia)
        .order_by(SalarioBase.inicio_vigencia.desc())
        .limit(1)
    ).first()
