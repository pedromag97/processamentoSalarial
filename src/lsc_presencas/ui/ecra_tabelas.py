"""Ecrã «Tabelas»: empresas, clientes, viaturas, zonas, códigos, feriados e parâmetros."""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import contas
from ..modelos import (
    Cliente,
    CodigoPresenca,
    Empresa,
    Feriado,
    ParametrosEmpresa,
    Viatura,
    Zona,
)
from . import definicoes as d
from .tabela import ModeloTabela, VistaTabela


class EcraTabelas(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.separadores = QTabWidget()
        self.vistas: dict[str, VistaTabela] = {}

        tabelas = [
            (
                "Empresas",
                Empresa,
                d.COLUNAS_EMPRESA,
                select(Empresa).order_by(Empresa.nome),
                "empresa",
            ),
            (
                "Clientes",
                Cliente,
                d.COLUNAS_CLIENTE,
                select(Cliente).order_by(Cliente.codigo),
                "cliente",
            ),
            (
                "Viaturas",
                Viatura,
                d.COLUNAS_VIATURA,
                select(Viatura).order_by(Viatura.codigo),
                "viatura",
            ),
            ("Zonas", Zona, d.COLUNAS_ZONA, select(Zona).order_by(Zona.nome), "zona"),
            (
                "Códigos de presença",
                CodigoPresenca,
                d.COLUNAS_CODIGO,
                select(CodigoPresenca).order_by(CodigoPresenca.ordem, CodigoPresenca.codigo),
                "código",
            ),
            (
                "Feriados",
                Feriado,
                d.COLUNAS_FERIADO,
                select(Feriado).order_by(Feriado.data),
                "feriado",
            ),
            (
                "Parâmetros por empresa",
                ParametrosEmpresa,
                d.COLUNAS_PARAMETROS,
                select(ParametrosEmpresa).order_by(
                    ParametrosEmpresa.empresa_id, ParametrosEmpresa.inicio_vigencia
                ),
                "conjunto de parâmetros",
            ),
        ]
        for titulo, classe, colunas, consulta, nome in tabelas:
            modelo = ModeloTabela(sessao, classe, colunas, consulta=lambda c=consulta: c)
            vista = VistaTabela(modelo, nome_registo=nome)
            self.vistas[titulo] = vista
            self.separadores.addTab(vista, titulo)

        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.separadores)
        # As listas de escolha (ex.: empresas nos parâmetros) dependem dos outros separadores.
        self.separadores.currentChanged.connect(lambda n: self.separadores.widget(n).recarregar())

    def recarregar(self) -> None:
        for vista in self.vistas.values():
            vista.bloquear(not contas.e_admin())
        self.separadores.currentWidget().recarregar()
