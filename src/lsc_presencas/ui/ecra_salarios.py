"""Ecrã «Salários»: a folha de salário de cada trabalhador num mês, do vencimento ao a pagar.

À esquerda, os trabalhadores da empresa com os totais; à direita, a folha do que está
selecionado, com o aspeto da folha Excel «Simulação salário». Escrevem-se aqui o IRS do mês e
as quantidades das ajudas (células a amarelo); tudo o resto vem da grelha, da ficha e das
tabelas.
"""

from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from .. import calculo, salarios
from .. import folha_salario as fs
from ..exportar_pdf import euros, numero
from ..presencas import meses_fechados
from . import definicoes as d
from .formatos import ler_decimal
from .lista import nova_lista, preencher
from .periodo import SeletorMes
from .tabela import mensagem_de_erro

DIREITA = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
PAPEL_CAMPO = Qt.ItemDataRole.UserRole  # ("irs",) ou ("ger", id da linha): o que a célula edita

COR_EDITAVEL = QColor("#FFF9C4")
COR_RC = QColor("#EAF2FB")
COR_GER = QColor("#EAF6EA")
COR_TOTAL = QColor("#E0E0E0")
COR_POR_CALCULAR = QColor("#F8CBAD")

TITULOS_FOLHA = ["", "Descrição", "Valor do mês", "Valor unitário", "Quantidade", "€"]
TITULOS_LISTA = ["Nº", "Nome", "Vencimento RC", "GER", "Líquido", "A pagar", "Estado"]
NIVEIS = {
    calculo.NIVEL_ERRO: "Erro",
    calculo.NIVEL_AVISO: "Aviso",
    calculo.NIVEL_CONFIRMAR: "Confirmar",
}


def estado_da_folha(folha: fs.Folha) -> str:
    if folha.incompleta or any(a.nivel == calculo.NIVEL_ERRO for a in folha.alertas):
        return "Por calcular"
    return "Com avisos" if folha.alertas else "OK"


class EcraSalarios(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.folhas: list[salarios.FolhaTrabalhador] = []
        self.fechado = False
        self._a_preencher = False

        self.caixa_empresa = QComboBox()
        self.caixa_empresa.setMinimumWidth(280)
        self.seletor = SeletorMes()
        self.botao_atualizar = QPushButton("Atualizar")
        self.resumo = QLabel()
        barra = QHBoxLayout()
        barra.addWidget(QLabel("Empresa:"))
        barra.addWidget(self.caixa_empresa)
        barra.addWidget(QLabel("Mês:"))
        barra.addWidget(self.seletor)
        barra.addWidget(self.botao_atualizar)
        barra.addStretch(1)
        barra.addWidget(self.resumo)

        self.aviso = QLabel()
        self.aviso.setStyleSheet("background:#FFF3B0; padding:4px; border:1px solid #E0C040;")
        self.aviso.setWordWrap(True)

        self.lista = nova_lista()
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.titulo_folha = QLabel()
        self.titulo_folha.setStyleSheet("font-weight:bold; font-size:14px;")
        self.tabela = QTableWidget()
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ajuda = QLabel(
            "Células a amarelo: escreve-se o IRS do mês e as quantidades das ajudas (dias, "
            "noites, horas). As ajudas de cada trabalhador definem-se na ficha, em «Ajudas (GER)»."
        )
        self.ajuda.setWordWrap(True)
        self.alertas = QLabel()
        self.alertas.setWordWrap(True)
        self.alertas.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.mensagem = QLabel()
        self.mensagem.setStyleSheet("color:#B00020;")
        self.mensagem.setWordWrap(True)

        direita = QWidget()
        disposicao_direita = QVBoxLayout(direita)
        disposicao_direita.setContentsMargins(0, 0, 0, 0)
        disposicao_direita.addWidget(self.titulo_folha)
        disposicao_direita.addWidget(self.tabela, 1)
        disposicao_direita.addWidget(self.ajuda)
        disposicao_direita.addWidget(self.alertas)
        disposicao_direita.addWidget(self.mensagem)

        self.divisor = QSplitter(Qt.Orientation.Horizontal)
        self.divisor.addWidget(self.lista)
        self.divisor.addWidget(direita)
        self.divisor.setStretchFactor(0, 1)
        self.divisor.setStretchFactor(1, 1)
        self.divisor.setSizes([620, 760])

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(barra)
        disposicao.addWidget(self.aviso)
        disposicao.addWidget(self.divisor, 1)

        self.caixa_empresa.currentIndexChanged.connect(lambda _: self.atualizar())
        self.seletor.mudou.connect(self.atualizar)
        self.botao_atualizar.clicked.connect(self.atualizar)
        self.lista.itemSelectionChanged.connect(self._mostrar_selecionada)
        self.tabela.itemChanged.connect(self._celula_mudou)
        self.recarregar()

    # --- estado -------------------------------------------------------------------------------

    @property
    def empresa_id(self) -> int | None:
        return self.caixa_empresa.currentData()

    @property
    def selecionada(self) -> salarios.FolhaTrabalhador | None:
        linha = self.lista.currentRow()
        return self.folhas[linha] if 0 <= linha < len(self.folhas) else None

    def recarregar(self) -> None:
        """Volta a ler as empresas (podem ter mudado no ecrã Tabelas) e recalcula."""
        atual = self.empresa_id
        self.caixa_empresa.blockSignals(True)
        self.caixa_empresa.clear()
        for id_, nome in d.empresas(self.sessao):
            self.caixa_empresa.addItem(nome, id_)
        posicao = self.caixa_empresa.findData(atual)
        self.caixa_empresa.setCurrentIndex(max(posicao, 0) if self.caixa_empresa.count() else -1)
        self.caixa_empresa.blockSignals(False)
        self.atualizar()

    def atualizar(self, manter_mensagem: bool = False) -> None:
        if not manter_mensagem:
            self.mensagem.setText("")
        anterior = self.selecionada.trabalhador_id if self.selecionada else None
        ano, mes = self.seletor.ano, self.seletor.mes
        if self.empresa_id is None:
            self.folhas = []
            self.fechado = False
        else:
            self.folhas = salarios.folhas_do_mes(self.sessao, self.empresa_id, ano, mes)
            self.fechado = (self.empresa_id, ano, mes) in meses_fechados(self.sessao)
            self.sessao.rollback()  # só leitura: não deixa uma transação aberta

        self.aviso.setText(
            "Este mês está fechado: a folha é só para consulta. Reabra o mês para a alterar."
            if self.fechado
            else ""
        )
        self.aviso.setVisible(self.fechado)

        self.lista.blockSignals(True)
        preencher(
            self.lista,
            TITULOS_LISTA,
            [
                (
                    f.numero,
                    f.nome,
                    euros(f.folha.vencimento_rc),
                    euros(f.folha.total_ger),
                    euros(f.folha.liquido),
                    euros(f.folha.a_pagar),
                    estado_da_folha(f.folha),
                )
                for f in self.folhas
            ],
        )
        for linha in range(self.lista.rowCount()):
            for coluna in range(2, 6):
                self.lista.item(linha, coluna).setTextAlignment(DIREITA)
        posicao = next(
            (n for n, f in enumerate(self.folhas) if f.trabalhador_id == anterior),
            0 if self.folhas else -1,
        )
        if posicao >= 0:
            self.lista.selectRow(posicao)
        self.lista.blockSignals(False)

        total = sum((f.folha.a_pagar for f in self.folhas), Decimal(0))
        por_calcular = sum(1 for f in self.folhas if estado_da_folha(f.folha) == "Por calcular")
        texto = f"{len(self.folhas)} trabalhador(es) · a pagar: {euros(total)}"
        if por_calcular:
            texto += f" · {por_calcular} por calcular"
        self.resumo.setText(texto)
        self._mostrar_selecionada()

    # --- a folha ------------------------------------------------------------------------------

    def _mostrar_selecionada(self) -> None:
        f = self.selecionada
        self._a_preencher = True
        try:
            self.tabela.clear()
            self.tabela.setColumnCount(len(TITULOS_FOLHA))
            self.tabela.setHorizontalHeaderLabels(TITULOS_FOLHA)
            self.tabela.setRowCount(0)
            if f is None:
                self.titulo_folha.setText("Sem trabalhadores neste mês.")
                self.alertas.setText("")
                return
            periodo = f"{self.seletor.mes:02d}/{self.seletor.ano}"
            self.titulo_folha.setText(f"{f.numero} {f.nome} — folha de salário de {periodo}")
            self._preencher_folha(f)
            self.alertas.setText(
                "\n".join(f"{NIVEIS.get(a.nivel, a.nivel)}: {a.mensagem}" for a in f.folha.alertas)
            )
        finally:
            self._a_preencher = False

    def _linha(self, textos, *, cor=None, negrito=False, editavel=None, dica="") -> None:
        """Acrescenta uma linha à folha. `editavel` = (coluna, campo) torna essa célula editável."""
        n = self.tabela.rowCount()
        self.tabela.insertRow(n)
        for coluna, texto in enumerate(textos):
            item = QTableWidgetItem(texto)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if coluna >= 2:
                item.setTextAlignment(DIREITA)
            if cor is not None:
                item.setBackground(cor)
            if negrito:
                fonte = item.font()
                fonte.setBold(True)
                item.setFont(fonte)
            if dica:
                item.setToolTip(dica)
            if editavel is not None and editavel[0] == coluna and not self.fechado:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setBackground(COR_EDITAVEL)
                item.setData(PAPEL_CAMPO, editavel[1])
            self.tabela.setItem(n, coluna, item)

    def _preencher_folha(self, f: salarios.FolhaTrabalhador) -> None:
        folha = f.folha
        self._linha(
            [
                "rc",
                f"Vencimento base (mês com {folha.dias_trabalho_mes} dias de trabalho)",
                euros(folha.vencimento_base),
                "",
                "",
                "",
            ],
            cor=COR_RC,
            negrito=True,
        )
        for linha in folha.linhas_rc:
            self._linha(
                [
                    "rc",
                    linha.descricao,
                    euros(linha.valor_mes),
                    euros(linha.valor_unitario),
                    numero(linha.quantidade),
                    euros(linha.total),
                ],
                cor=COR_POR_CALCULAR if linha.total is None else COR_RC,
                editavel=(2, ("irs",)) if linha.chave == fs.IRS else None,
                dica=linha.formula,
            )
        self._linha(
            ["", "Vencimento RC", "", "", "", euros(folha.vencimento_rc)],
            cor=COR_TOTAL,
            negrito=True,
        )
        for linha, (linha_id, manual) in zip(folha.linhas_ger, f.linhas_ger, strict=True):
            unitario = euros(linha.valor_unitario)
            self._linha(
                [
                    "ger",
                    linha.descricao,
                    euros(linha.valor_mes),
                    f"{unitario} / {linha.unidade}" if unitario else "",
                    numero(linha.quantidade),
                    euros(linha.total),
                ],
                cor=COR_POR_CALCULAR if linha.total is None else COR_GER,
                editavel=(4, ("ger", linha_id)) if manual else None,
                dica=linha.formula,
            )
        self._linha(
            ["", "Total GER", "", "", "", euros(folha.total_ger)], cor=COR_TOTAL, negrito=True
        )
        self._linha(["", "Líquido", "", "", "", euros(folha.liquido)], cor=COR_TOTAL, negrito=True)
        for movimento in folha.movimentos:
            self._linha(["", movimento.descricao, "", "", "", euros(movimento.valor)])
        self._linha(["", "A pagar", "", "", "", euros(folha.a_pagar)], cor=COR_TOTAL, negrito=True)
        self.tabela.resizeColumnsToContents()

    # --- escrever o IRS e as quantidades ------------------------------------------------------

    def _celula_mudou(self, item: QTableWidgetItem) -> None:
        campo = item.data(PAPEL_CAMPO)
        f = self.selecionada
        if self._a_preencher or campo is None or f is None:
            return
        ano, mes = self.seletor.ano, self.seletor.mes
        try:
            valor = ler_decimal(item.text())
            if campo[0] == "irs":
                salarios.gravar_irs(self.sessao, f.trabalhador_id, ano, mes, valor)
            else:
                salarios.gravar_quantidade(self.sessao, campo[1], ano, mes, valor or Decimal(0))
        except Exception as erro:  # noqa: BLE001 - qualquer recusa aparece na linha de mensagens
            self.sessao.rollback()
            texto = mensagem_de_erro(erro)
        else:
            texto = ""
        # A tabela só se reconstrói depois de o Qt acabar de fechar o editor desta célula.
        QTimer.singleShot(0, lambda: self._depois_de_gravar(texto))

    def _depois_de_gravar(self, erro: str) -> None:
        self.atualizar()
        self.mensagem.setText(erro)
