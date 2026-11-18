"""Janela principal: navegação à esquerda e um ecrã de cada vez à direita."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .. import __version__, config
from ..modelos import CodigoPresenca, Empresa, Feriado, Marcacao, Trabalhador
from .ecra_importacao import AssistenteImportacao
from .ecra_presencas import EcraPresencas
from .ecra_tabelas import EcraTabelas
from .ecra_trabalhadores import EcraTrabalhadores


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


class EcraInicio(QWidget):
    """Estado da base de dados e a importação inicial da folha de ponto."""

    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.texto = QLabel()
        self.texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.botao_importar = QPushButton("Importar a folha de ponto (s-27)…")
        self.botao_importar.clicked.connect(self.importar)
        disposicao = QVBoxLayout(self)
        disposicao.addStretch(1)
        disposicao.addWidget(self.texto)
        disposicao.addWidget(self.botao_importar, 0, Qt.AlignmentFlag.AlignCenter)
        disposicao.addStretch(1)
        self.recarregar()

    def recarregar(self) -> None:
        linhas = [f"{nome}: {total}" for nome, total in resumo_bd(self.sessao).items()]
        self.texto.setText("\n".join(["LSC Presenças", "", *linhas, "", str(config.caminho_bd())]))

    def importar(self) -> None:
        AssistenteImportacao(self.sessao, self).exec()
        self.recarregar()


class JanelaPrincipal(QMainWindow):
    def __init__(self, fabrica: sessionmaker[Session]):
        super().__init__()
        self.setWindowTitle(f"LSC Presenças {__version__}")
        self.resize(1280, 760)
        # Uma única sessão para toda a interface (app de um só utilizador).
        self.sessao = fabrica(expire_on_commit=True)

        self.ecras: dict[str, QWidget] = {
            "Presenças": EcraPresencas(self.sessao),
            "Trabalhadores": EcraTrabalhadores(self.sessao),
            "Tabelas": EcraTabelas(self.sessao),
            "Base de dados": EcraInicio(self.sessao),
        }
        self.navegacao = QListWidget()
        self.navegacao.setFixedWidth(170)
        self.pilha = QStackedWidget()
        for nome, ecra in self.ecras.items():
            self.navegacao.addItem(nome)
            self.pilha.addWidget(ecra)

        centro = QWidget()
        disposicao = QHBoxLayout(centro)
        disposicao.addWidget(self.navegacao)
        disposicao.addWidget(self.pilha, 1)
        self.setCentralWidget(centro)

        self.navegacao.currentRowChanged.connect(self._mudar_ecra)
        self.navegacao.setCurrentRow(0)

    def _mudar_ecra(self, linha: int) -> None:
        ecra = self.pilha.widget(linha)
        ecra.recarregar()  # os dados podem ter mudado noutro ecrã
        self.pilha.setCurrentIndex(linha)

    def mostrar(self, nome: str) -> QWidget:
        self.navegacao.setCurrentRow(list(self.ecras).index(nome))
        return self.ecras[nome]

    def closeEvent(self, evento) -> None:
        self.sessao.close()
        super().closeEvent(evento)


def correr(fabrica: sessionmaker[Session]) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    janela = JanelaPrincipal(fabrica)
    janela.show()
    return app.exec()
