"""Ecrã «Auditoria»: quem alterou o quê e quando. Também serve o histórico da ficha."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
from sqlalchemy.orm import Session

from .. import auditoria
from .lista import nova_lista, preencher

TITULOS = ["Quando", "Quem", "O quê", "Ação", "Antes", "Depois", "Motivo"]
LIMITE = 500


class ListaAuditoria(QWidget):
    """Lista de registos com filtros. Com `numero_trabalhador`, mostra só os dessa pessoa."""

    def __init__(self, sessao: Session, numero_trabalhador: int | None = None, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.numero_trabalhador = numero_trabalhador
        self.registos: list[auditoria.Registo] = []

        self.caixa_entidade = QComboBox()
        self.caixa_entidade.addItem("Tudo", None)
        for chave, nome in auditoria.NOMES_ENTIDADE.items():
            self.caixa_entidade.addItem(nome, chave)
        self.pesquisa = QLineEdit()
        self.pesquisa.setPlaceholderText("Pesquisar (utilizador, código, data, motivo…)")
        self.pesquisa.setClearButtonEnabled(True)
        self.contagem = QLabel()
        self.tabela = nova_lista()

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Mostrar:"))
        topo.addWidget(self.caixa_entidade)
        topo.addWidget(self.pesquisa, 1)
        topo.addWidget(self.contagem)
        disposicao = QVBoxLayout(self)
        disposicao.addLayout(topo)
        disposicao.addWidget(self.tabela, 1)

        self.caixa_entidade.currentIndexChanged.connect(lambda _: self.recarregar())
        self.pesquisa.textChanged.connect(lambda _: self.recarregar())
        self.recarregar()

    def recarregar(self) -> None:
        self.registos = auditoria.listar(
            self.sessao,
            entidade=self.caixa_entidade.currentData(),
            texto=self.pesquisa.text(),
            numero_trabalhador=self.numero_trabalhador,
            limite=LIMITE,
        )
        preencher(
            self.tabela,
            TITULOS,
            [
                [r.quando, r.utilizador, r.entidade, r.acao, r.antes, r.depois, r.motivo]
                for r in self.registos
            ],
        )
        n = len(self.registos)
        self.contagem.setText(
            f"os {LIMITE} registos mais recentes" if n >= LIMITE else f"{n} registo(s)"
        )


class EcraAuditoria(ListaAuditoria):
    pass
