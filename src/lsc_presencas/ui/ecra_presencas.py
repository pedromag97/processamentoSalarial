"""Dashboard de presenças: grelha mensal/semanal com edição rápida por teclado.

A grelha é feita de três tabelas lado a lado sobre o mesmo modelo: as colunas fixas à esquerda,
os dias ao centro (a única parte editável, com deslocamento horizontal) e os totais à direita.
Por baixo há um rodapé igual, com as pessoas presentes por dia.
"""

import json
from calendar import monthrange
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import bloqueios, config
from ..modelos import CodigoPresenca
from ..presencas import semana_de
from . import definicoes as d
from .grelha import (
    MESES,
    N_DIR,
    N_ESQ,
    PAPEL_HORAS,
    TRABALHADOR,
    Filtros,
    ModeloGrelha,
    ModeloTotaisDia,
)

LARGURAS_ESQ = [44, 210, 64, 70]
INTERVALO_ATUALIZACAO_MS = 15_000
LARGURA_DIA_MES = 36
LARGURA_DIA_SEMANA = 96
LARGURAS_DIR = [38, 38, 38, 38, 38, 38, 58]
ALTURA_LINHA = 24
MAX_LINHAS_RODAPE = 6

MENSAL = "mensal"
SEMANAL = "semanal"


class DelegadoDia(QStyledItemDelegate):
    """Desenha o código ao centro e, se houver, as horas extra em pequeno no canto."""

    def paint(self, pintor, opcao, indice):
        super().paint(pintor, opcao, indice)
        horas = indice.data(PAPEL_HORAS)
        if horas:
            pintor.save()
            letra = QFont(opcao.font)
            letra.setPointSizeF(max(letra.pointSizeF() - 2.5, 6))
            letra.setBold(True)
            pintor.setFont(letra)
            pintor.setPen(QColor("#9C0006"))
            pintor.drawText(
                opcao.rect.adjusted(0, 0, -2, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                f"+{horas}",
            )
            pintor.restore()


class VistaDias(QTableView):
    """Tabela dos dias: escrever o código, Enter desce, copiar/colar, Delete e Ctrl+Z."""

    def a_editar(self) -> bool:
        return self.state() == QAbstractItemView.State.EditingState

    def keyPressEvent(self, evento):
        modelo = self.model()
        if evento.matches(QKeySequence.StandardKey.Copy):
            self.copiar()
        elif evento.matches(QKeySequence.StandardKey.Paste):
            self.colar()
        elif evento.matches(QKeySequence.StandardKey.Undo):
            modelo.desfazer()
        elif evento.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not self.a_editar():
            modelo.aplicar_texto(self.selectedIndexes(), "")
        elif evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.a_editar():
            self.descer()
        elif not self.a_editar() and (
            evento.key() == Qt.Key.Key_F4
            or (
                evento.key() == Qt.Key.Key_Down
                and evento.modifiers() & Qt.KeyboardModifier.AltModifier
            )
        ):
            self.abrir_lista(self.currentIndex())
        else:
            super().keyPressEvent(evento)

    # --- Lista pendente de códigos (duplo clique, botão direito, F4 ou Alt+seta para baixo) ---

    def mouseDoubleClickEvent(self, evento):
        indice = self.indexAt(evento.position().toPoint())
        if self.model().celula(indice) is not None:
            self.setCurrentIndex(indice)
            self.abrir_lista(indice)
        else:
            super().mouseDoubleClickEvent(evento)

    def contextMenuEvent(self, evento):
        indice = self.indexAt(evento.pos())
        if self.model().celula(indice) is None:
            return
        if indice not in self.selectedIndexes():
            self.setCurrentIndex(indice)  # o botão direito fora da seleção passa a ser a seleção
        self.abrir_lista(indice)

    def menu_de_codigos(self, indice) -> QMenu:
        """A lista dos códigos para a célula. Escolher um aplica-o a todas as selecionadas."""
        modelo = self.model()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        celula = modelo.celula(indice)
        if celula is None:
            return menu
        motivo = modelo.motivo_so_leitura(*celula)
        if motivo:
            menu.addAction(motivo).setEnabled(False)
            return menu

        alvo = [i for i in self.selectedIndexes() if modelo.celula(i) is not None] or [indice]
        if indice not in alvo:
            alvo = [indice]
        if len(alvo) > 1:
            menu.addAction(f"Aplicar a {len(alvo)} células:").setEnabled(False)
        for info in modelo.codigos_para_escolher():
            cor = QPixmap(14, 14)
            cor.fill(info.cor)
            acao = menu.addAction(QIcon(cor), f"{info.codigo}  —  {info.descricao}")
            acao.setToolTip(info.efeitos)
            acao.triggered.connect(lambda _=False, c=info.codigo: modelo.aplicar_texto(alvo, c))
        menu.addSeparator()
        menu.addAction("Limpar").triggered.connect(lambda: modelo.aplicar_texto(alvo, ""))
        escrever = menu.addAction("Escrever (para horas extra, ex.: PF+2)…")
        escrever.triggered.connect(lambda: self.edit(indice))
        return menu

    def abrir_lista(self, indice) -> None:
        """Abre a lista por baixo da célula."""
        if not indice.isValid():
            return
        menu = self.menu_de_codigos(indice)
        menu.exec(self.viewport().mapToGlobal(self.visualRect(indice).bottomLeft()))

    def commitData(self, editor):
        # Com várias células selecionadas, o que se escreve aplica-se a todas.
        selecionadas = self.selectedIndexes()
        if len(selecionadas) > 1 and isinstance(editor, QLineEdit):
            self.model().aplicar_texto(selecionadas, editor.text())
        else:
            super().commitData(editor)

    def closeEditor(self, editor, dica):
        super().closeEditor(editor, dica)
        if dica == QAbstractItemDelegate.EndEditHint.SubmitModelCache:
            self.descer()

    def descer(self) -> None:
        """Passa para a linha de trabalhador seguinte, na mesma coluna."""
        atual = self.currentIndex()
        if not atual.isValid():
            return
        seguintes = self.model().linhas_de_trabalhadores(atual.row() + 1)
        if seguintes:
            self.setCurrentIndex(self.model().index(seguintes[0], atual.column()))

    def copiar(self) -> None:
        QApplication.clipboard().setText(self.model().texto_para_copiar(self.selectedIndexes()))

    def colar(self) -> None:
        texto = QApplication.clipboard().text().replace("\r", "")
        if not texto:
            return
        matriz = [linha.split("\t") for linha in texto.rstrip("\n").split("\n")]
        selecionadas = self.selectedIndexes()
        if len(matriz) == 1 and len(matriz[0]) == 1 and len(selecionadas) > 1:
            self.model().aplicar_texto(selecionadas, matriz[0][0])  # preencher a seleção
            return
        if selecionadas:
            inicio = min(selecionadas, key=lambda i: (i.row(), i.column()))
        else:
            inicio = self.currentIndex()
        self.model().colar(inicio, matriz)


class Trio(QWidget):
    """Três tabelas sobre o mesmo modelo: colunas fixas, dias e totais."""

    larguras_esq_mudaram = Signal(list)

    def __init__(self, modelo, centro: QTableView | None = None, *, cabecalho=True, parent=None):
        super().__init__(parent)
        self.modelo = modelo
        self.esq = QTableView()
        self.centro = centro or QTableView()
        self.dir = QTableView()
        self.largura_dia = LARGURA_DIA_MES

        disposicao = QHBoxLayout(self)
        disposicao.setContentsMargins(0, 0, 0, 0)
        disposicao.setSpacing(0)
        barra = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        sempre, nunca = Qt.ScrollBarPolicy.ScrollBarAlwaysOn, Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        for vista in (self.esq, self.centro, self.dir):
            vista.setModel(modelo)
            vista.verticalHeader().setVisible(False)
            vista.verticalHeader().setDefaultSectionSize(ALTURA_LINHA)
            vista.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            vista.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            vista.horizontalHeader().setVisible(cabecalho)
            vista.horizontalHeader().setFixedHeight(40)
            vista.horizontalHeader().setHighlightSections(False)
            vista.setHorizontalScrollBarPolicy(sempre if cabecalho else nunca)
            vista.setVerticalScrollBarPolicy(sempre if vista is self.dir else nunca)
            vista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            if vista is not self.centro or centro is None:
                vista.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
                vista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                vista.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            disposicao.addWidget(vista, 1 if vista is self.centro else 0)
        self.larguras_esq = list(LARGURAS_ESQ)
        if cabecalho:
            # As colunas fixas (nº, nome, cliente, viatura) podem ser alargadas com o rato.
            cab = self.esq.horizontalHeader()
            cab.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            cab.setMinimumSectionSize(30)
            cab.sectionResized.connect(self._coluna_esq_redimensionada)
        self.esq.setFixedWidth(sum(self.larguras_esq) + 4)
        self.dir.setFixedWidth(sum(LARGURAS_DIR) + 4 + barra)

        barras = [v.verticalScrollBar() for v in (self.esq, self.centro, self.dir)]
        for origem in barras:
            for destino in barras:
                if origem is not destino:
                    origem.valueChanged.connect(destino.setValue)

        modelo.modelReset.connect(self.ajustar)
        self.ajustar()

    def ajustar(self) -> None:
        """Mostra em cada tabela só as suas colunas e fixa as larguras."""
        total = self.modelo.columnCount()
        n_dias = total - N_ESQ - N_DIR
        for coluna in range(total):
            e_esq = coluna < N_ESQ
            e_dir = coluna >= N_ESQ + n_dias
            self.esq.setColumnHidden(coluna, not e_esq)
            self.centro.setColumnHidden(coluna, e_esq or e_dir)
            self.dir.setColumnHidden(coluna, not e_dir)
            if e_esq:
                self.esq.setColumnWidth(coluna, self.larguras_esq[coluna])
            elif e_dir:
                self.dir.setColumnWidth(coluna, LARGURAS_DIR[coluna - N_ESQ - n_dias])
            else:
                self.centro.setColumnWidth(coluna, self.largura_dia)

    def definir_larguras_esq(self, larguras: list[int]) -> None:
        """Aplica as larguras das colunas fixas (sem voltar a emitir o sinal)."""
        if len(larguras) != N_ESQ:
            return
        self.larguras_esq = [max(int(x), 30) for x in larguras]
        cab = self.esq.horizontalHeader()
        cab.blockSignals(True)
        for coluna, largura in enumerate(self.larguras_esq):
            self.esq.setColumnWidth(coluna, largura)
        cab.blockSignals(False)
        self.esq.setFixedWidth(sum(self.larguras_esq) + 4)

    def _coluna_esq_redimensionada(self, coluna: int, _antiga: int, nova: int) -> None:
        if coluna >= N_ESQ or self.esq.isColumnHidden(coluna) or self.larguras_esq[coluna] == nova:
            return
        self.larguras_esq[coluna] = nova
        self.esq.setFixedWidth(sum(self.larguras_esq) + 4)
        self.larguras_esq_mudaram.emit(list(self.larguras_esq))


def ler_larguras_guardadas() -> list[int] | None:
    """Larguras das colunas fixas escolhidas pelo utilizador (ficheiro na pasta da app)."""
    try:
        larguras = json.loads(_ficheiro_interface().read_text(encoding="utf-8"))["colunas_fixas"]
        if len(larguras) == N_ESQ and all(isinstance(x, int) for x in larguras):
            return larguras
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def guardar_larguras(larguras: list[int]) -> None:
    try:
        _ficheiro_interface().write_text(json.dumps({"colunas_fixas": larguras}), encoding="utf-8")
    except OSError:
        pass  # não conseguir guardar uma preferência não deve incomodar ninguém


def _ficheiro_interface():
    return config.pasta_app() / "interface.json"


class EcraPresencas(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.referencia = date.today()
        self.vista_periodo = MENSAL

        self.modelo = ModeloGrelha(sessao, self)
        self.totais = ModeloTotaisDia(self.modelo, self)
        self.dias = VistaDias()
        self.dias.setItemDelegate(DelegadoDia(self.dias))
        self.dias.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # Escrever abre o editor de texto; o duplo clique abre a lista de códigos (ver VistaDias).
        self.dias.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.grelha = Trio(self.modelo, self.dias)
        self.rodape = Trio(self.totais, cabecalho=False)
        self.grelha.centro.horizontalScrollBar().valueChanged.connect(
            self.rodape.centro.horizontalScrollBar().setValue
        )
        self.grelha.esq.clicked.connect(lambda indice: self.modelo.alternar_grupo(indice.row()))
        # Larguras das colunas fixas: o rodapé acompanha a grelha e a escolha fica guardada.
        self.grelha.larguras_esq_mudaram.connect(self.rodape.definir_larguras_esq)
        self.grelha.larguras_esq_mudaram.connect(guardar_larguras)
        guardadas = ler_larguras_guardadas()
        if guardadas:
            self.grelha.definir_larguras_esq(guardadas)
            self.rodape.definir_larguras_esq(guardadas)

        # --- Barra de período e filtros ---
        self.botao_anterior = QPushButton("◀")
        self.botao_seguinte = QPushButton("▶")
        self.botao_hoje = QPushButton("Hoje")
        for botao in (self.botao_anterior, self.botao_seguinte):
            botao.setFixedWidth(32)
        self.titulo = QLabel()
        self.titulo.setMinimumWidth(250)
        letra = self.titulo.font()
        letra.setBold(True)
        letra.setPointSize(letra.pointSize() + 2)
        self.titulo.setFont(letra)
        self.escolha_vista = QComboBox()
        self.escolha_vista.addItem("Vista mensal", MENSAL)
        self.escolha_vista.addItem("Vista semanal", SEMANAL)

        self.filtro_empresa = QComboBox()
        self.filtro_cliente = QComboBox()
        self.filtro_viatura = QComboBox()
        self.filtro_zona = QComboBox()
        self.mostrar_inativos = QCheckBox("Inativos")
        self.pesquisa = QLineEdit()
        self.pesquisa.setPlaceholderText("Pesquisar por nome…")
        self.pesquisa.setClearButtonEnabled(True)

        barra = QHBoxLayout()
        for w in (self.botao_anterior, self.titulo, self.botao_seguinte, self.botao_hoje):
            barra.addWidget(w)
        barra.addWidget(self.escolha_vista)
        barra.addSpacing(12)
        for w in (self.filtro_empresa, self.filtro_cliente, self.filtro_viatura, self.filtro_zona):
            barra.addWidget(w)
        barra.addWidget(self.mostrar_inativos)
        barra.addWidget(self.pesquisa, 1)

        # --- Barra de códigos e ações ---
        self.barra_codigos = QHBoxLayout()
        self.botoes_codigo: dict[str, QPushButton] = {}
        self.botao_copiar_semana = QPushButton("Copiar semana anterior")
        self.botao_desfazer = QPushButton("Desfazer (Ctrl+Z)")
        self.botao_atualizar = QPushButton("Atualizar (F5)")
        self.botao_atualizar.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self.botao_atualizar.setToolTip(
            "Vai buscar as marcações gravadas por outras pessoas. Com um servidor, isto "
            "acontece sozinho de 15 em 15 segundos."
        )
        acoes = QHBoxLayout()
        acoes.addWidget(QLabel("Aplicar à seleção:"))
        acoes.addLayout(self.barra_codigos)
        acoes.addStretch(1)
        acoes.addWidget(self.botao_copiar_semana)
        acoes.addWidget(self.botao_desfazer)
        acoes.addWidget(self.botao_atualizar)

        self.estado = QLabel()
        self.estado.setMinimumHeight(18)

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(barra)
        disposicao.addLayout(acoes)
        disposicao.addWidget(self.grelha, 1)
        disposicao.addWidget(self.rodape)
        disposicao.addWidget(self.estado)

        # --- Ligações ---
        self.botao_anterior.clicked.connect(lambda: self.avancar(-1))
        self.botao_seguinte.clicked.connect(lambda: self.avancar(1))
        self.botao_hoje.clicked.connect(lambda: self.ir_para(date.today()))
        self.escolha_vista.currentIndexChanged.connect(self._mudou_vista)
        for caixa in (
            self.filtro_empresa,
            self.filtro_cliente,
            self.filtro_viatura,
            self.filtro_zona,
        ):
            caixa.currentIndexChanged.connect(self._aplicar)
        self.mostrar_inativos.toggled.connect(self._aplicar)
        self.pesquisa.textChanged.connect(self._aplicar)
        self.botao_copiar_semana.clicked.connect(self.copiar_semana_anterior)
        self.botao_desfazer.clicked.connect(self.modelo.desfazer)
        self.modelo.erro.connect(self._mostrar_erro)

        # Os funcionários das células selecionadas ficam com o cadeado desta pessoa. Espera-se
        # um instante depois de a seleção parar, para não pedir cadeados a cada tecla.
        self.temporizador_cadeados = QTimer(self)
        self.temporizador_cadeados.setSingleShot(True)
        self.temporizador_cadeados.setInterval(350)
        self.temporizador_cadeados.timeout.connect(self.pedir_cadeados)
        self.dias.selectionModel().selectionChanged.connect(
            lambda *_: self.temporizador_cadeados.start()
        )

        # Com um servidor, a grelha vai buscar de tempos a tempos o que os outros gravaram.
        self.botao_atualizar.clicked.connect(lambda: self.atualizar(manual=True))
        self.temporizador = QTimer(self)
        self.temporizador.setInterval(INTERVALO_ATUALIZACAO_MS)
        self.temporizador.timeout.connect(self.atualizar)
        if sessao.get_bind().dialect.name != "sqlite":
            self.temporizador.start()
        self.modelo.alterado.connect(self._depois_de_alterar)
        self.totais.modelReset.connect(self._ajustar_rodape)

        self.recarregar()

    # --- Período ---

    def periodo(self) -> tuple[date, date]:
        if self.vista_periodo == SEMANAL:
            return semana_de(self.referencia)
        ano, mes = self.referencia.year, self.referencia.month
        return date(ano, mes, 1), date(ano, mes, monthrange(ano, mes)[1])

    def _titulo(self) -> str:
        inicio, fim = self.periodo()
        if self.vista_periodo == SEMANAL:
            semana = inicio.isocalendar().week
            return f"Semana {semana} — {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
        return f"{MESES[inicio.month - 1]} {inicio.year}"

    def ir_para(self, dia: date) -> None:
        self.referencia = dia
        self._aplicar()

    def avancar(self, passo: int) -> None:
        if self.vista_periodo == SEMANAL:
            self.ir_para(self.referencia + timedelta(days=7 * passo))
        else:
            meses = self.referencia.year * 12 + self.referencia.month - 1 + passo
            self.ir_para(date(meses // 12, meses % 12 + 1, 1))

    def definir_vista(self, vista: str) -> None:
        self.escolha_vista.setCurrentIndex(self.escolha_vista.findData(vista))

    def _mudou_vista(self) -> None:
        self.vista_periodo = self.escolha_vista.currentData()
        self._aplicar()

    # --- Carregamento ---

    def recarregar(self) -> None:
        """Volta a ler tudo da base de dados (listas dos filtros, códigos e marcações)."""
        caixas = (
            (self.filtro_empresa, "Todas as empresas", d.empresas),
            (self.filtro_cliente, "Todos os clientes", d.clientes),
            (self.filtro_viatura, "Todas as viaturas", d.viaturas),
            (self.filtro_zona, "Todas as zonas", d.zonas),
        )
        for caixa, todos, opcoes in caixas:
            atual = caixa.currentData()
            caixa.blockSignals(True)
            caixa.clear()
            caixa.addItem(todos, None)
            for valor, rotulo in opcoes(self.sessao):
                caixa.addItem(rotulo, valor)
            caixa.setCurrentIndex(max(caixa.findData(atual), 0))
            caixa.blockSignals(False)
        self._aplicar()  # carrega os códigos (as dicas dos botões vêm do modelo)
        self._montar_botoes_de_codigo()

    def _montar_botoes_de_codigo(self) -> None:
        while self.barra_codigos.count():
            antigo = self.barra_codigos.takeAt(0).widget()
            antigo.hide()  # o deleteLater só acontece mais tarde; sem isto ficavam sobrepostos
            antigo.deleteLater()
        self.botoes_codigo = {}
        codigos = self.sessao.execute(
            select(CodigoPresenca.codigo, CodigoPresenca.cor)
            .where(CodigoPresenca.ativo)
            .order_by(CodigoPresenca.ordem, CodigoPresenca.codigo)
        ).all()
        for codigo, cor in [*codigos, ("", "#FFFFFF")]:
            botao = QPushButton(codigo or "Limpar")
            info = self.modelo.por_codigo.get(codigo)
            botao.setToolTip(
                f"{info.explicacao}\nClique para aplicar às células selecionadas."
                if info
                else "Apaga as marcações das células selecionadas."
            )
            # Com seletor, para o estilo do botão não passar para a dica.
            botao.setStyleSheet(
                f"QPushButton {{ background:{cor}; border:1px solid #999; padding:3px 8px; "
                "min-width:22px; }"
            )
            botao.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            botao.clicked.connect(lambda _=False, c=codigo: self.aplicar_codigo(c))
            self.barra_codigos.addWidget(botao)
            self.botoes_codigo[codigo] = botao

    def filtros(self) -> Filtros:
        return Filtros(
            empresa_id=self.filtro_empresa.currentData(),
            cliente_id=self.filtro_cliente.currentData(),
            viatura_id=self.filtro_viatura.currentData(),
            zona_id=self.filtro_zona.currentData(),
            mostrar_inativos=self.mostrar_inativos.isChecked(),
            texto=self.pesquisa.text(),
        )

    def _aplicar(self, *_args) -> None:
        largura = LARGURA_DIA_SEMANA if self.vista_periodo == SEMANAL else LARGURA_DIA_MES
        self.grelha.largura_dia = self.rodape.largura_dia = largura
        self.titulo.setText(self._titulo())
        self.modelo.configurar(*self.periodo(), self.filtros())

    def _ajustar_rodape(self) -> None:
        linhas = min(self.totais.rowCount(), MAX_LINHAS_RODAPE)
        self.rodape.setFixedHeight(linhas * ALTURA_LINHA + 4)

    # --- Ações ---

    def aplicar_codigo(self, codigo: str) -> None:
        selecionadas = self.dias.selectedIndexes()
        if not selecionadas:
            self._mostrar_erro("Selecione primeiro as células.")
            return
        self.modelo.aplicar_texto(selecionadas, codigo)

    def copiar_semana_anterior(self) -> None:
        celula = self.modelo.celula(self.dias.currentIndex())
        if celula is not None:
            dia = celula[1]
        elif self.vista_periodo == SEMANAL:
            dia = self.periodo()[0]
        else:
            self._mostrar_erro("Selecione primeiro uma célula da semana de destino.")
            return
        copiadas = self.modelo.copiar_semana_anterior(dia)
        if copiadas:
            segunda, domingo = semana_de(dia)
            self.estado.setText(
                f"Copiei {copiadas} marcações para a semana de {segunda:%d/%m} a {domingo:%d/%m}. "
                "Ctrl+Z desfaz."
            )

    def pedir_cadeados(self) -> dict:
        """Fica com o cadeado dos funcionários das células selecionadas (e larga os outros).
        Devolve os que não conseguiu, por estarem em uso por outra pessoa."""
        selecionados = {
            celula[0].id
            for celula in (self.modelo.celula(i) for i in self.dias.selectedIndexes())
            if celula is not None
        }
        try:
            recusados = bloqueios.definir(self.sessao, selecionados)
        except SQLAlchemyError:
            return {}
        if recusados:
            self.modelo.atualizar()
            quem = sorted({c.nome for c in recusados.values()})
            self._mostrar_erro(
                f"{len(recusados)} funcionário(s) selecionado(s) estão em uso por "
                f"{', '.join(quem)}: ficam só de leitura até essa pessoa sair deles."
            )
        return recusados

    def atualizar(self, manual: bool = False) -> bool:
        """Mostra o que as outras pessoas gravaram entretanto. Não interrompe quem está a
        escrever numa célula nem mexe na seleção. Devolve True se alguma coisa mudou."""
        if not manual and (not self.isVisible() or self.dias.a_editar()):
            return False
        mudou = self.modelo.atualizar()
        if mudou:
            self.estado.setStyleSheet("color:#1B6E1B;")
            self.estado.setText(
                f"Atualizado às {datetime.now():%H:%M:%S}: há alterações de outra pessoa."
            )
        elif manual:
            self.estado.setStyleSheet("")
            self.estado.setText(f"Atualizado às {datetime.now():%H:%M:%S}: sem alterações.")
        return mudou

    def _mostrar_erro(self, mensagem: str) -> None:
        self.estado.setStyleSheet("color:#B00020;")
        self.estado.setText(mensagem)

    def _depois_de_alterar(self) -> None:
        self.estado.setStyleSheet("")
        self.estado.setText("")
        self.botao_desfazer.setEnabled(self.modelo.pode_desfazer())

    def linha_do_trabalhador(self, numero: int) -> int:
        """Linha da grelha de um trabalhador (pelo nº interno); -1 se não estiver visível."""
        for n, linha in enumerate(self.modelo.linhas):
            if linha.tipo == TRABALHADOR and linha.trab.numero == numero:
                return n
        return -1
