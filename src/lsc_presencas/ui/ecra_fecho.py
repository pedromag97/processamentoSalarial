"""Ecrã «Fecho do mês»: alertas, pré-visualização dos totais, fechar/reabrir e exportar."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from .. import calculo, config, contas, exportacao, fecho
from ..exportar_pdf import euros, numero
from ..mapa import MapaMes, MapaTrabalhador
from . import definicoes as d
from .formatos import texto_data
from .periodo import SeletorMes

COR_NIVEL = {
    calculo.NIVEL_ERRO: QColor("#F8C9C9"),
    calculo.NIVEL_CONFIRMAR: QColor("#FFE0B0"),
    calculo.NIVEL_AVISO: QColor("#FFF3B0"),
}
ESTILO_ERRO = "color:#B00020;"
ESTILO_OK = "color:#1B6E1B;"
DIREITA = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def colunas_da_previa(mapa: MapaMes) -> list[tuple[str, object]]:
    """(título, função que dá o texto de um trabalhador). Os valores em euros vão formatados."""
    c = calculo
    usados = [
        k for k, _ in mapa.codigos if any(t.resultado.contagens.get(k) for t in mapa.trabalhadores)
    ]

    def total_de(chave):
        return lambda t: euros(t.resultado.total_de(chave)) if t.resultado.rubrica(chave) else ""

    colunas: list[tuple[str, object]] = [
        ("Nº", lambda t: str(t.numero)),
        ("Nome", lambda t: t.nome),
        ("Cliente", lambda t: t.cliente or ""),
        ("Dias contrato", lambda t: str(t.resultado.dias_contrato)),
    ]
    colunas += [(k, lambda t, k=k: str(t.resultado.contagens.get(k) or "")) for k in usados]
    colunas += [
        ("Base processada", lambda t: euros(t.base_processada)),
        ("Subsídio alim.", total_de(c.SUBSIDIO_ALIMENTACAO)),
        ("Ajuda de custo", total_de(c.AJUDA_CUSTO_FRANCA)),
        ("Prevenção", total_de(c.PREVENCAO)),
        ("Horas extra (h)", lambda t: numero(t.resultado.horas_extra or None)),
        ("Horas extra (€)", lambda t: euros(t.valor_horas_extra() or None)),
        (
            "Lançamentos",
            lambda t: (
                euros(t.resultado.total_de(c.LANCAMENTO))
                if t.resultado.rubrica(c.LANCAMENTO)
                else ""
            ),
        ),
        ("Total ilíquido estimado", lambda t: euros(t.total)),
        ("Estado", lambda t: "incompleto" if t.resultado.incompleto else ""),
    ]
    return colunas


class EcraFecho(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.mapa: MapaMes | None = None
        self.alertas: list[fecho.AlertaFecho] = []
        self.ultima_exportacao: exportacao.Exportacao | None = None

        self.caixa_empresa = QComboBox()
        self.caixa_empresa.setMinimumWidth(260)
        self.seletor = SeletorMes()
        self.rotulo_estado = QLabel()
        self.rotulo_estado.setStyleSheet("font-weight:bold;")

        self.tabela_alertas = self._tabela()
        self.tabela_previa = self._tabela()
        self.titulo_alertas = QLabel()
        self.titulo_previa = QLabel()

        self.visto_avisos = QCheckBox("Vi os avisos e confirmo o fecho")
        self.botao_fechar = QPushButton("Fechar o mês")
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setPlaceholderText("Motivo da reabertura (obrigatório)")
        self.botao_reabrir = QPushButton("Reabrir o mês")
        self.botao_exportar = QPushButton("Exportar Excel e PDF")
        self.botao_pasta = QPushButton("Abrir a pasta")
        self.mensagem = QLabel()
        self.mensagem.setWordWrap(True)
        self.mensagem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:"))
        topo.addWidget(self.caixa_empresa)
        topo.addWidget(QLabel("Mês:"))
        topo.addWidget(self.seletor)
        topo.addSpacing(20)
        topo.addWidget(self.rotulo_estado)
        topo.addStretch(1)

        cima, baixo = QWidget(), QWidget()
        for contentor, titulo, tabela in (
            (cima, self.titulo_alertas, self.tabela_alertas),
            (baixo, self.titulo_previa, self.tabela_previa),
        ):
            caixa = QVBoxLayout(contentor)
            caixa.setContentsMargins(0, 0, 0, 0)
            caixa.addWidget(titulo)
            caixa.addWidget(tabela, 1)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(cima)
        divisor.addWidget(baixo)
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 2)

        acoes = QHBoxLayout()
        for w in (self.visto_avisos, self.botao_fechar):
            acoes.addWidget(w)
        acoes.addSpacing(20)
        acoes.addWidget(self.campo_motivo, 1)
        acoes.addWidget(self.botao_reabrir)
        acoes.addSpacing(20)
        acoes.addWidget(self.botao_exportar)
        acoes.addWidget(self.botao_pasta)

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(topo)
        disposicao.addWidget(divisor, 1)
        disposicao.addLayout(acoes)
        disposicao.addWidget(self.mensagem)

        self.caixa_empresa.currentIndexChanged.connect(lambda _: self.atualizar())
        self.seletor.mudou.connect(self.atualizar)
        self.botao_fechar.clicked.connect(self.fechar)
        self.botao_reabrir.clicked.connect(self.reabrir)
        self.botao_exportar.clicked.connect(self.exportar)
        self.botao_pasta.clicked.connect(self.abrir_pasta)
        self.recarregar()

    @staticmethod
    def _tabela() -> QTableWidget:
        tabela = QTableWidget()
        tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabela.setAlternatingRowColors(True)
        tabela.verticalHeader().setVisible(False)
        return tabela

    # --- Estado ---

    @property
    def empresa_id(self) -> int | None:
        return self.caixa_empresa.currentData()

    def escolher(self, empresa_id: int, ano: int, mes: int) -> None:
        """Muda de empresa e de mês (usado também pelos testes)."""
        self.caixa_empresa.blockSignals(True)
        self.caixa_empresa.setCurrentIndex(self.caixa_empresa.findData(empresa_id))
        self.caixa_empresa.blockSignals(False)
        self.seletor.blockSignals(True)
        self.seletor.definir(ano, mes)
        self.seletor.blockSignals(False)
        self.atualizar()

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
            self._dizer("")
        if self.empresa_id is None:
            self.mapa, self.alertas = None, []
        else:
            self.mapa = fecho.mapa_do_mes(
                self.sessao, self.empresa_id, self.seletor.ano, self.seletor.mes
            )
            self.alertas = fecho.alertas(self.sessao, self.mapa)
        self._mostrar_alertas()
        self._mostrar_previa()
        self._mostrar_estado()

    def _dizer(self, texto: str, erro: bool = False) -> None:
        self.mensagem.setStyleSheet(ESTILO_ERRO if erro else ESTILO_OK)
        self.mensagem.setText(texto)

    def _mostrar_estado(self) -> None:
        mapa = self.mapa
        fechado = bool(mapa and mapa.fechado)
        erros, avisos = fecho.contar_niveis(self.alertas)
        if mapa is None:
            self.rotulo_estado.setText("Crie primeiro uma empresa no ecrã Tabelas.")
        elif fechado:
            quando = f" em {mapa.fechado_em:%d/%m/%Y %H:%M}" if mapa.fechado_em else ""
            self.rotulo_estado.setText(f"FECHADO{quando} por {mapa.fechado_por or '?'}")
        else:
            self.rotulo_estado.setText("ABERTO")
        self.visto_avisos.setChecked(False)
        self.visto_avisos.setVisible(not fechado and avisos > 0 and erros == 0)
        admin = contas.e_admin()
        self.botao_fechar.setVisible(not fechado)
        self.botao_fechar.setEnabled(admin and mapa is not None and erros == 0)
        self.botao_fechar.setToolTip(
            "Só um administrador pode fechar o mês."
            if not admin
            else "Resolva primeiro os erros da lista de alertas."
            if erros
            else ""
        )
        self.visto_avisos.setEnabled(admin)
        self.campo_motivo.setEnabled(admin)
        self.botao_reabrir.setEnabled(admin)
        self.botao_reabrir.setToolTip("" if admin else "Só um administrador pode reabrir o mês.")
        self.campo_motivo.setVisible(fechado)
        self.campo_motivo.clear()
        self.botao_reabrir.setVisible(fechado)
        self.botao_exportar.setEnabled(bool(mapa and mapa.trabalhadores))
        self.botao_exportar.setText(
            "Exportar Excel e PDF" if fechado else "Exportar Excel e PDF (provisório)"
        )

    def _mostrar_alertas(self) -> None:
        erros, avisos = fecho.contar_niveis(self.alertas)
        self.titulo_alertas.setText(
            f"Alertas: {erros} erro(s), {avisos} aviso(s)" if self.alertas else "Alertas: nenhum"
        )
        titulos = ["Nível", "Nº", "Trabalhador", "Alerta", "Dias"]
        tabela = self.tabela_alertas
        tabela.clear()
        tabela.setColumnCount(len(titulos))
        tabela.setHorizontalHeaderLabels(titulos)
        tabela.setRowCount(len(self.alertas))
        for linha, a in enumerate(self.alertas):
            dias = ", ".join(texto_data(x)[:5] for x in a.datas[:12])
            if len(a.datas) > 12:
                dias += f" … (+{len(a.datas) - 12})"
            textos = [
                fecho.NOME_NIVEL.get(a.nivel, a.nivel),
                "" if a.numero is None else str(a.numero),
                a.nome,
                a.mensagem,
                dias,
            ]
            for coluna, texto in enumerate(textos):
                item = QTableWidgetItem(texto)
                if coluna == 0:
                    item.setBackground(COR_NIVEL.get(a.nivel, QColor("white")))
                tabela.setItem(linha, coluna, item)
        tabela.resizeColumnsToContents()

    def _mostrar_previa(self) -> None:
        tabela = self.tabela_previa
        tabela.clear()
        mapa = self.mapa
        if mapa is None:
            tabela.setRowCount(0)
            tabela.setColumnCount(0)
            self.titulo_previa.setText("")
            return
        self.titulo_previa.setText(
            f"Totais por trabalhador ({len(mapa.trabalhadores)}) — total ilíquido estimado, "
            f"antes de IRS e TSU: {euros(mapa.total)}"
        )
        colunas = colunas_da_previa(mapa)
        tabela.setColumnCount(len(colunas))
        tabela.setHorizontalHeaderLabels([titulo for titulo, _ in colunas])
        tabela.setRowCount(len(mapa.trabalhadores) + 1)
        for linha, t in enumerate(mapa.trabalhadores):
            for coluna, (_, obter) in enumerate(colunas):
                item = QTableWidgetItem(obter(t))
                if coluna >= 3:
                    item.setTextAlignment(DIREITA)
                if t.resultado.incompleto:
                    item.setBackground(COR_NIVEL[calculo.NIVEL_ERRO])
                tabela.setItem(linha, coluna, item)
        ultima = len(mapa.trabalhadores)
        for coluna, texto in ((1, "TOTAL"), (len(colunas) - 2, euros(mapa.total))):
            item = QTableWidgetItem(texto)
            fonte = item.font()
            fonte.setBold(True)
            item.setFont(fonte)
            if coluna != 1:
                item.setTextAlignment(DIREITA)
            tabela.setItem(ultima, coluna, item)
        tabela.resizeColumnsToContents()

    def trabalhador(self, numero_interno: int) -> MapaTrabalhador | None:
        if self.mapa is None:
            return None
        return next((t for t in self.mapa.trabalhadores if t.numero == numero_interno), None)

    # --- Ações ---

    def fechar(self) -> bool:
        if self.empresa_id is None:
            return False
        try:
            fecho.fechar(
                self.sessao,
                self.empresa_id,
                self.seletor.ano,
                self.seletor.mes,
                confirmado=self.visto_avisos.isChecked(),
            )
        except (fecho.FechoRecusado, contas.SemPermissao) as erro:
            self._dizer(str(erro), erro=True)
            return False
        except Exception as erro:  # noqa: BLE001 - ex.: a cópia de segurança falhou
            self._dizer(f"O mês não foi fechado: {erro}", erro=True)
            return False
        self.atualizar()
        if self.exportar():
            self._dizer("Mês fechado. " + self.mensagem.text())
        else:
            self._dizer("Mês fechado, mas a exportação falhou. " + self.mensagem.text(), erro=True)
        return True

    def reabrir(self) -> bool:
        if self.empresa_id is None:
            return False
        try:
            fecho.reabrir(
                self.sessao,
                self.empresa_id,
                self.seletor.ano,
                self.seletor.mes,
                self.campo_motivo.text(),
            )
        except (fecho.FechoRecusado, contas.SemPermissao) as erro:
            self._dizer(str(erro), erro=True)
            return False
        except Exception as erro:  # noqa: BLE001
            self._dizer(f"O mês não foi reaberto: {erro}", erro=True)
            return False
        self.atualizar()
        self._dizer("Mês reaberto. O motivo ficou registado.")
        return True

    def exportar(self) -> bool:
        if self.mapa is None:
            return False
        try:
            self.ultima_exportacao = exportacao.exportar(self.mapa)
        except Exception as erro:  # noqa: BLE001 - mostra-se a causa em vez de fechar a app
            self._dizer(f"Não foi possível exportar: {erro}", erro=True)
            return False
        feito = self.ultima_exportacao
        provisorio = "" if self.mapa.fechado else " PROVISÓRIOS (o mês ainda não está fechado)"
        self._dizer(
            f"Ficheiros{provisorio}: 1 Excel, {len(feito.pdfs)} PDF individuais e 1 PDF "
            f"conjunto, em {feito.pasta}"
        )
        return True

    def abrir_pasta(self) -> None:
        pasta = self.ultima_exportacao.pasta if self.ultima_exportacao else None
        if pasta is None:
            pasta = config.pasta_saidas()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))
