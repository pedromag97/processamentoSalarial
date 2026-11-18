"""Tabela só de leitura (relatórios, auditoria), preenchida com uma lista de linhas."""

from datetime import date, datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from .formatos import texto_data, texto_decimal

DIREITA = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return texto_data(valor)
    if isinstance(valor, Decimal):
        return texto_decimal(valor.normalize() if valor == valor.to_integral() else valor)
    return str(valor)


def nova_lista() -> QTableWidget:
    tabela = QTableWidget()
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabela.setAlternatingRowColors(True)
    tabela.verticalHeader().setVisible(False)
    return tabela


def preencher(tabela: QTableWidget, titulos: list[str], linhas: list, negrito_na_ultima=False):
    tabela.clear()
    tabela.setColumnCount(len(titulos))
    tabela.setHorizontalHeaderLabels(titulos)
    tabela.setRowCount(len(linhas))
    for n_linha, linha in enumerate(linhas):
        for n_coluna, valor in enumerate(linha):
            item = QTableWidgetItem(texto(valor))
            if isinstance(valor, int | Decimal) and not isinstance(valor, bool):
                item.setTextAlignment(DIREITA)
            if negrito_na_ultima and n_linha == len(linhas) - 1:
                fonte = item.font()
                fonte.setBold(True)
                item.setFont(fonte)
            tabela.setItem(n_linha, n_coluna, item)
    tabela.resizeColumnsToContents()
    for n in range(len(titulos)):
        if tabela.columnWidth(n) > 520:
            tabela.setColumnWidth(n, 520)
