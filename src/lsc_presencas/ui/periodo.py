"""Seletor de mês e ano, usado nos ecrãs de lançamentos e de fecho."""

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSpinBox, QWidget

from ..mapa import MESES


class SeletorMes(QWidget):
    mudou = Signal()

    def __init__(self, ano: int | None = None, mes: int | None = None, parent=None):
        super().__init__(parent)
        hoje = date.today()
        self.botao_anterior = QPushButton("◀")
        self.botao_seguinte = QPushButton("▶")
        for botao in (self.botao_anterior, self.botao_seguinte):
            botao.setFixedWidth(32)
        self.caixa_mes = QComboBox()
        self.caixa_mes.addItems([m.capitalize() for m in MESES])
        self.caixa_ano = QSpinBox()
        self.caixa_ano.setRange(2000, 2100)

        disposicao = QHBoxLayout(self)
        disposicao.setContentsMargins(0, 0, 0, 0)
        for w in (self.botao_anterior, self.caixa_mes, self.caixa_ano, self.botao_seguinte):
            disposicao.addWidget(w)

        self.definir(ano or hoje.year, mes or hoje.month)
        self.botao_anterior.clicked.connect(lambda: self.avancar(-1))
        self.botao_seguinte.clicked.connect(lambda: self.avancar(1))
        self.caixa_mes.currentIndexChanged.connect(lambda _: self.mudou.emit())
        self.caixa_ano.valueChanged.connect(lambda _: self.mudou.emit())

    @property
    def ano(self) -> int:
        return self.caixa_ano.value()

    @property
    def mes(self) -> int:
        return self.caixa_mes.currentIndex() + 1

    def definir(self, ano: int, mes: int) -> None:
        """Muda o mês e o ano, emitindo `mudou` uma só vez (se algo mudou de facto)."""
        if (ano, mes) == (self.ano, self.mes):
            return
        bloqueado = self.blockSignals(True)
        self.caixa_ano.blockSignals(True)
        self.caixa_mes.blockSignals(True)
        self.caixa_ano.setValue(ano)
        self.caixa_mes.setCurrentIndex(mes - 1)
        self.caixa_ano.blockSignals(False)
        self.caixa_mes.blockSignals(False)
        self.blockSignals(bloqueado)
        self.mudou.emit()

    def avancar(self, meses: int) -> None:
        total = self.ano * 12 + (self.mes - 1) + meses
        self.definir(total // 12, total % 12 + 1)
