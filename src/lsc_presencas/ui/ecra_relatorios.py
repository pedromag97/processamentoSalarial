"""Ecrã «Relatórios»: férias, prevenção e dias por cliente e por viatura."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from sqlalchemy.orm import Session

from .. import config, relatorios
from ..exportacao import nome_limpo
from . import definicoes as d
from .lista import nova_lista, preencher
from .periodo import SeletorMes

# (nome no ecrã, função, é anual?)
RELATORIOS = [
    ("Mapa anual de férias", relatorios.ferias_anual, True),
    ("Mapa de prevenção (anual)", relatorios.prevencao_anual, True),
    ("Dias por cliente (mês)", relatorios.dias_por_cliente, False),
    ("Dias por viatura (mês)", relatorios.dias_por_viatura, False),
]


class EcraRelatorios(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.relatorio: relatorios.Relatorio | None = None
        self.ultimo_ficheiro: Path | None = None

        self.caixa_relatorio = QComboBox()
        for nome, _, _ in RELATORIOS:
            self.caixa_relatorio.addItem(nome)
        self.caixa_empresa = QComboBox()
        self.caixa_empresa.setMinimumWidth(220)
        self.seletor = SeletorMes()
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-weight:bold;")
        self.tabela = nova_lista()
        self.botao_exportar = QPushButton("Exportar para Excel")
        self.botao_pasta = QPushButton("Abrir a pasta")
        self.mensagem = QLabel()
        self.mensagem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        topo = QHBoxLayout()
        for w in (
            QLabel("Relatório:"),
            self.caixa_relatorio,
            QLabel("Empresa:"),
            self.caixa_empresa,
            QLabel("Período:"),
            self.seletor,
        ):
            topo.addWidget(w)
        topo.addStretch(1)
        fundo = QHBoxLayout()
        fundo.addWidget(self.botao_exportar)
        fundo.addWidget(self.botao_pasta)
        fundo.addWidget(self.mensagem, 1)

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(topo)
        disposicao.addWidget(self.titulo)
        disposicao.addWidget(self.tabela, 1)
        disposicao.addLayout(fundo)

        self.caixa_relatorio.currentIndexChanged.connect(lambda _: self.atualizar())
        self.caixa_empresa.currentIndexChanged.connect(lambda _: self.atualizar())
        self.seletor.mudou.connect(self.atualizar)
        self.botao_exportar.clicked.connect(self.exportar)
        self.botao_pasta.clicked.connect(self.abrir_pasta)
        self.recarregar()

    def recarregar(self) -> None:
        atual = self.caixa_empresa.currentData()
        self.caixa_empresa.blockSignals(True)
        self.caixa_empresa.clear()
        self.caixa_empresa.addItem("Todas as empresas", None)
        for id_, nome in d.empresas(self.sessao):
            self.caixa_empresa.addItem(nome, id_)
        self.caixa_empresa.setCurrentIndex(max(self.caixa_empresa.findData(atual), 0))
        self.caixa_empresa.blockSignals(False)
        self.atualizar()

    def escolher(self, relatorio: int, ano: int, mes: int, empresa_id: int | None = None) -> None:
        for caixa, posicao in (
            (self.caixa_relatorio, relatorio),
            (self.caixa_empresa, self.caixa_empresa.findData(empresa_id)),
        ):
            caixa.blockSignals(True)
            caixa.setCurrentIndex(posicao)
            caixa.blockSignals(False)
        self.seletor.blockSignals(True)
        self.seletor.definir(ano, mes)
        self.seletor.blockSignals(False)
        self.atualizar()

    def atualizar(self) -> None:
        _, funcao, anual = RELATORIOS[self.caixa_relatorio.currentIndex()]
        self.seletor.caixa_mes.setEnabled(not anual)
        empresa_id = self.caixa_empresa.currentData()
        if anual:
            self.relatorio = funcao(self.sessao, self.seletor.ano, empresa_id)
        else:
            self.relatorio = funcao(self.sessao, self.seletor.ano, self.seletor.mes, empresa_id)
        r = self.relatorio
        self.titulo.setText(f"{r.titulo} · {r.subtitulo} · {len(r.linhas)} linha(s)")
        linhas = [*r.linhas, r.totais] if r.totais and r.linhas else r.linhas
        preencher(self.tabela, r.colunas, linhas, negrito_na_ultima=bool(r.totais and r.linhas))
        self.botao_exportar.setEnabled(bool(r.linhas))
        self.mensagem.setText("")

    def exportar(self) -> bool:
        r = self.relatorio
        if r is None or not r.linhas:
            return False
        nome = f"{r.nome_ficheiro}_{nome_limpo(r.subtitulo)}.xlsx"
        try:
            self.ultimo_ficheiro = relatorios.para_excel(
                r, config.pasta_saidas() / "relatorios" / nome
            )
        except PermissionError:
            self.mensagem.setStyleSheet("color:#B00020;")
            self.mensagem.setText(f"«{nome}» está aberto noutro programa. Feche-o e repita.")
            return False
        self.mensagem.setStyleSheet("color:#1B6E1B;")
        self.mensagem.setText(f"Guardado em {self.ultimo_ficheiro}")
        return True

    def abrir_pasta(self) -> None:
        pasta = config.pasta_saidas() / "relatorios"
        pasta.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))
