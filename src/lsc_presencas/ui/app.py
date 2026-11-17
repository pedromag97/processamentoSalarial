"""Janela principal. No marco 1 mostra apenas o estado da base de dados."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .. import __version__, config
from ..modelos import CodigoPresenca, Empresa, Feriado, Marcacao, Trabalhador


def resumo_bd(sessao: Session) -> dict[str, int]:
    def contar(modelo) -> int:
        return sessao.scalar(select(func.count()).select_from(modelo)) or 0

    return {
        "Empresas": contar(Empresa),
        "Trabalhadores": contar(Trabalhador),
        "Marcações": contar(Marcacao),
        "Códigos de presença": contar(CodigoPresenca),
        "Feriados": contar(Feriado),
    }


class JanelaPrincipal(QMainWindow):
    def __init__(self, fabrica: sessionmaker[Session]):
        super().__init__()
        self.setWindowTitle(f"LSC Presenças {__version__}")
        self.resize(720, 420)
        with fabrica() as sessao:
            linhas = [f"{nome}: {total}" for nome, total in resumo_bd(sessao).items()]
        texto = "\n".join(
            ["LSC Presenças — marco 1 (modelo de dados)", "", *linhas, "", str(config.caminho_bd())]
        )
        etiqueta = QLabel(texto)
        etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etiqueta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setCentralWidget(etiqueta)


def correr(fabrica: sessionmaker[Session]) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    janela = JanelaPrincipal(fabrica)
    janela.show()
    return app.exec()
