"""Tabela editável genérica sobre uma classe do modelo de dados, e formulário equivalente.

Cada ecrã descreve as suas colunas com `Coluna`; o resto (ler, validar, gravar, apagar) é comum.
As alterações são gravadas célula a célula. Uma linha nova fica "pendente" (não gravada) até
os campos obrigatórios estarem preenchidos.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .formatos import ler_data, ler_decimal, ler_inteiro, texto_data, texto_decimal

TEXTO = "texto"
INTEIRO = "inteiro"
DECIMAL = "decimal"
DATA = "data"
BOOL = "bool"
ESCOLHA = "escolha"
COR = "cor"

COR_AVISO = QColor("#FFF3B0")
SEM_PERMISSAO = "A sua conta não tem permissão para alterar estes dados (só um administrador)."
COR_PENDENTE = QColor("#EFEFEF")

Papel = Qt.ItemDataRole


@dataclass
class Coluna:
    campo: str
    titulo: str
    tipo: str = TEXTO
    obrigatorio: bool = False
    # Para ESCOLHA: devolve [(valor, rótulo), ...]
    escolhas: Callable[[Session], list[tuple[Any, str]]] | None = None
    # Realça a célula quando está vazia (valor que o utilizador ainda tem de preencher).
    aviso_vazio: bool = False
    # Coluna calculada, só de leitura.
    obter: Callable[[Any], Any] | None = None
    dica: str | None = None

    @property
    def so_leitura(self) -> bool:
        return self.obter is not None


def vazio(valor) -> bool:
    return valor is None or valor == ""


def formatar(coluna: Coluna, valor) -> str:
    if valor is None:
        return ""
    if coluna.tipo == DECIMAL:
        return texto_decimal(valor)
    if coluna.tipo == DATA:
        return texto_data(valor)
    return str(valor)


def interpretar(coluna: Coluna, texto: str):
    """Converte o texto escrito no valor da coluna. Levanta ValueError se for inválido."""
    if coluna.tipo == DECIMAL:
        valor = ler_decimal(texto)
    elif coluna.tipo == INTEIRO:
        valor = ler_inteiro(texto)
    elif coluna.tipo == DATA:
        valor = ler_data(texto)
    elif coluna.tipo == COR:
        valor = texto.strip() or None
        if valor is not None and not QColor.isValidColorName(valor):
            raise ValueError(f"«{valor}» não é uma cor válida (use #RRGGBB).")
    else:
        valor = texto.strip() or None
    if valor is None and coluna.obrigatorio:
        raise ValueError(f"«{coluna.titulo}» é obrigatório.")
    return valor


def mensagem_de_erro(erro: Exception) -> str:
    if isinstance(erro, ValueError):
        return str(erro)
    texto = str(getattr(erro, "orig", erro))
    if "UNIQUE" in texto:
        return "Já existe um registo com esse valor."
    if "FOREIGN KEY" in texto:
        return "Este registo está a ser usado noutro sítio e não pode ser apagado."
    if "NOT NULL" in texto:
        return "Falta preencher um campo obrigatório."
    return f"Não foi possível gravar: {texto}"


def opcoes_da_coluna(coluna: Coluna, sessao: Session) -> list[tuple[Any, str]]:
    opcoes = list(coluna.escolhas(sessao)) if coluna.escolhas else []
    if not coluna.obrigatorio:
        opcoes.insert(0, (None, ""))
    return opcoes


class ModeloTabela(QAbstractTableModel):
    erro = Signal(str)
    alterado = Signal()

    def __init__(
        self,
        sessao: Session,
        classe,
        colunas: list[Coluna],
        *,
        consulta: Callable[[], Any] | None = None,
        ao_criar: Callable[[Any, Session], None] | None = None,
        ao_gravar: Callable[[Session, Any, str], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.sessao = sessao
        self.classe = classe
        self.colunas = colunas
        self._consulta = consulta
        self._ao_criar = ao_criar
        # Chamado antes de cada gravação com a ação («criar», «alterar» ou «apagar»), para
        # validar e registar a auditoria. Se levantar ValueError, a alteração é desfeita.
        self._ao_gravar = ao_gravar
        # Só de leitura: usado quando a conta em sessão não pode alterar esta tabela.
        self.bloqueada = False
        self.linhas: list[Any] = []
        self._pendentes: set[int] = set()
        self.opcoes: dict[int, list[tuple[Any, str]]] = {}
        self.recarregar()

    # --- Dados ---

    def recarregar(self) -> None:
        self.beginResetModel()
        consulta = self._consulta() if self._consulta else select(self.classe)
        self.linhas = list(self.sessao.scalars(consulta))
        self._pendentes.clear()
        self.opcoes = {
            n: opcoes_da_coluna(c, self.sessao)
            for n, c in enumerate(self.colunas)
            if c.tipo == ESCOLHA
        }
        self.endResetModel()
        self.alterado.emit()

    def pendente(self, obj) -> bool:
        return id(obj) in self._pendentes

    def valor(self, obj, coluna: Coluna):
        return coluna.obter(obj) if coluna.obter else getattr(obj, coluna.campo)

    def n_avisos(self) -> int:
        """Número de células por preencher nas colunas marcadas com `aviso_vazio`."""
        return sum(
            1
            for obj in self.linhas
            for c in self.colunas
            if c.aviso_vazio and not self.pendente(obj) and vazio(self.valor(obj, c))
        )

    # --- Interface do Qt ---

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.linhas)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.colunas)

    def headerData(self, seccao, orientacao, papel=Papel.DisplayRole):
        if orientacao == Qt.Orientation.Horizontal:
            coluna = self.colunas[seccao]
            if papel == Papel.DisplayRole:
                return coluna.titulo
            if papel == Papel.ToolTipRole:
                return coluna.dica
        return None

    def flags(self, indice):
        if not indice.isValid():
            return Qt.ItemFlag.NoItemFlags
        coluna = self.colunas[indice.column()]
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if coluna.so_leitura or self.bloqueada:
            return base
        if coluna.tipo == BOOL:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base | Qt.ItemFlag.ItemIsEditable

    def data(self, indice, papel=Papel.DisplayRole):
        if not indice.isValid():
            return None
        obj = self.linhas[indice.row()]
        coluna = self.colunas[indice.column()]
        valor = self.valor(obj, coluna)
        if papel == Papel.DisplayRole:
            if coluna.tipo == BOOL:
                return None
            if coluna.tipo == ESCOLHA:
                rotulos = dict(self.opcoes[indice.column()])
                return rotulos.get(valor, "" if valor is None else str(valor))
            return formatar(coluna, valor)
        if papel == Papel.EditRole:
            return valor if coluna.tipo in (ESCOLHA, BOOL) else formatar(coluna, valor)
        if papel == Papel.UserRole:  # valor para ordenar
            if coluna.tipo == ESCOLHA:
                return dict(self.opcoes[indice.column()]).get(valor, "")
            if coluna.tipo == DECIMAL:
                return None if valor is None else float(valor)
            if coluna.tipo == DATA:
                return None if valor is None else valor.isoformat()
            return valor
        if papel == Papel.CheckStateRole and coluna.tipo == BOOL:
            return Qt.CheckState.Checked if valor else Qt.CheckState.Unchecked
        if papel == Papel.BackgroundRole:
            if coluna.tipo == COR and valor and QColor.isValidColorName(valor):
                return QColor(valor)
            if self.pendente(obj):
                return COR_PENDENTE
            if coluna.aviso_vazio and vazio(valor):
                return COR_AVISO
        if papel == Papel.ToolTipRole:
            if self.pendente(obj):
                return "Linha nova: preencha os campos obrigatórios para a gravar."
            if coluna.aviso_vazio and vazio(valor):
                return "Por preencher."
            return coluna.dica
        if papel == Papel.TextAlignmentRole and coluna.tipo in (INTEIRO, DECIMAL):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, indice, valor, papel=Papel.EditRole) -> bool:
        if not indice.isValid():
            return False
        obj = self.linhas[indice.row()]
        coluna = self.colunas[indice.column()]
        if coluna.so_leitura:
            return False
        if self.bloqueada:
            self.erro.emit(SEM_PERMISSAO)
            return False
        try:
            if coluna.tipo == BOOL:
                if papel != Papel.CheckStateRole:
                    return False
                novo = valor in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, True)
            elif papel != Papel.EditRole:
                return False
            elif coluna.tipo == ESCOLHA:
                novo = valor
                if novo is None and coluna.obrigatorio:
                    raise ValueError(f"«{coluna.titulo}» é obrigatório.")
            else:
                novo = interpretar(coluna, str(valor or ""))
            setattr(obj, coluna.campo, novo)
            self._gravar(obj)
        except (ValueError, SQLAlchemyError) as erro:
            self.sessao.rollback()
            self._linha_mudou(indice.row())
            self.erro.emit(mensagem_de_erro(erro))
            return False
        self._linha_mudou(indice.row())
        self.alterado.emit()
        return True

    def _linha_mudou(self, linha: int) -> None:
        self.dataChanged.emit(self.index(linha, 0), self.index(linha, len(self.colunas) - 1))

    def _completo(self, obj) -> bool:
        return all(
            not vazio(getattr(obj, c.campo))
            for c in self.colunas
            if c.obrigatorio and not c.so_leitura
        )

    def _gravar(self, obj) -> None:
        if self.pendente(obj):
            if not self._completo(obj):
                return
            self.sessao.add(obj)
            if self._ao_gravar:
                self.sessao.flush()
                self._ao_gravar(self.sessao, obj, "criar")
            self.sessao.commit()
            self._pendentes.discard(id(obj))
        else:
            if self._ao_gravar:
                self._ao_gravar(self.sessao, obj, "alterar")
            self.sessao.commit()

    # --- Criar e apagar ---

    def novo(self) -> int:
        """Acrescenta uma linha nova (pendente) e devolve o seu número."""
        obj = self.classe()
        for coluna in inspect(self.classe).columns:
            if coluna.default is not None and coluna.default.is_scalar:
                setattr(obj, coluna.key, coluna.default.arg)
        if self._ao_criar:
            self._ao_criar(obj, self.sessao)
        linha = len(self.linhas)
        self.beginInsertRows(QModelIndex(), linha, linha)
        self.linhas.append(obj)
        self._pendentes.add(id(obj))
        self.endInsertRows()
        return linha

    def apagar(self, linha: int) -> bool:
        obj = self.linhas[linha]
        if self.bloqueada:
            self.erro.emit(SEM_PERMISSAO)
            return False
        if not self.pendente(obj):
            try:
                if self._ao_gravar:
                    self._ao_gravar(self.sessao, obj, "apagar")
                self.sessao.delete(obj)
                self.sessao.commit()
            except (ValueError, IntegrityError, SQLAlchemyError) as erro:
                self.sessao.rollback()
                self.erro.emit(mensagem_de_erro(erro))
                return False
        self.beginRemoveRows(QModelIndex(), linha, linha)
        self.linhas.pop(linha)
        self._pendentes.discard(id(obj))
        self.endRemoveRows()
        self.alterado.emit()
        return True


class DelegadoEscolha(QStyledItemDelegate):
    """Editor em lista pendente para as colunas de escolha."""

    def __init__(self, modelo: ModeloTabela, coluna: int, parent=None):
        super().__init__(parent)
        self._modelo = modelo
        self._coluna = coluna

    def createEditor(self, parent, opcao, indice):
        caixa = QComboBox(parent)
        for valor, rotulo in self._modelo.opcoes[self._coluna]:
            caixa.addItem(rotulo, valor)
        return caixa

    def setEditorData(self, editor, indice):
        atual = indice.data(Papel.EditRole)
        for n in range(editor.count()):
            if editor.itemData(n) == atual:
                editor.setCurrentIndex(n)
                return

    def setModelData(self, editor, modelo, indice):
        modelo.setData(indice, editor.currentData(), Papel.EditRole)


class VistaTabela(QWidget):
    """Tabela com os botões Novo e Apagar, a faixa de avisos e a linha de erros."""

    def __init__(
        self,
        modelo: ModeloTabela,
        *,
        proxy: QSortFilterProxyModel | None = None,
        nome_registo: str = "registo",
        parent=None,
    ):
        super().__init__(parent)
        self.modelo = modelo
        self.proxy = proxy
        self.nome_registo = nome_registo

        self.botao_novo = QPushButton("Novo")
        self.botao_apagar = QPushButton("Apagar")
        self.barra = QHBoxLayout()
        self.barra.addWidget(self.botao_novo)
        self.barra.addWidget(self.botao_apagar)
        self.barra.addStretch(1)

        self.aviso = QLabel()
        self.aviso.setStyleSheet("background:#FFF3B0; padding:4px; border:1px solid #E0C040;")
        self.aviso.setWordWrap(True)
        self.estado = QLabel()
        self.estado.setStyleSheet("color:#B00020;")

        self.tabela = QTableView()
        if proxy is not None:
            proxy.setSourceModel(modelo)
            self.tabela.setModel(proxy)
            self.tabela.setSortingEnabled(True)
        else:
            self.tabela.setModel(modelo)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.tabela.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.tabela.setAlternatingRowColors(True)
        self.tabela.verticalHeader().setVisible(False)
        for n, coluna in enumerate(modelo.colunas):
            if coluna.tipo == ESCOLHA:
                self.tabela.setItemDelegateForColumn(n, DelegadoEscolha(modelo, n, self.tabela))
        self.tabela.resizeColumnsToContents()

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(self.barra)
        disposicao.addWidget(self.aviso)
        disposicao.addWidget(self.tabela, 1)
        disposicao.addWidget(self.estado)

        self.botao_novo.clicked.connect(self.novo)
        self.botao_apagar.clicked.connect(self.apagar)
        modelo.erro.connect(self.estado.setText)
        modelo.alterado.connect(self._atualizar_aviso)
        modelo.alterado.connect(lambda: self.estado.setText(""))
        self._atualizar_aviso()

    def _atualizar_aviso(self) -> None:
        n = self.modelo.n_avisos()
        self.aviso.setVisible(n > 0)
        if n:
            self.aviso.setText(
                f"Há {n} valor(es) por preencher (células a amarelo). "
                "Enquanto estiverem vazios, as rubricas correspondentes não são calculadas."
            )

    def _para_vista(self, indice: QModelIndex) -> QModelIndex:
        return self.proxy.mapFromSource(indice) if self.proxy else indice

    def _para_modelo(self, indice: QModelIndex) -> QModelIndex:
        return self.proxy.mapToSource(indice) if self.proxy else indice

    def bloquear(self, bloqueada: bool) -> None:
        """Põe a tabela só de leitura (ou volta a deixá-la editável)."""
        self.modelo.bloqueada = bloqueada
        self.botao_novo.setEnabled(not bloqueada)
        self.botao_apagar.setEnabled(not bloqueada)
        dica = SEM_PERMISSAO if bloqueada else ""
        self.botao_novo.setToolTip(dica)
        self.botao_apagar.setToolTip(dica)

    def objeto_atual(self):
        indice = self._para_modelo(self.tabela.currentIndex())
        return self.modelo.linhas[indice.row()] if indice.isValid() else None

    def recarregar(self) -> None:
        self.modelo.recarregar()
        self.tabela.resizeColumnsToContents()

    def novo(self) -> None:
        if self.modelo.bloqueada:
            return
        linha = self.modelo.novo()
        coluna = next(
            (n for n, c in enumerate(self.modelo.colunas) if not c.so_leitura and c.tipo != BOOL), 0
        )
        indice = self._para_vista(self.modelo.index(linha, coluna))
        if indice.isValid():
            self.tabela.setCurrentIndex(indice)
            self.tabela.scrollTo(indice)
            self.tabela.edit(indice)

    def apagar(self) -> None:
        indice = self._para_modelo(self.tabela.currentIndex())
        if not indice.isValid():
            return
        obj = self.modelo.linhas[indice.row()]
        if not self.modelo.pendente(obj):
            resposta = QMessageBox.question(
                self, "Apagar", f"Apagar este {self.nome_registo}? Não é possível desfazer."
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
        self.modelo.apagar(indice.row())


class Formulario(QWidget):
    """Formulário com um campo por coluna, para editar um objeto de uma vez."""

    def __init__(self, sessao: Session, colunas: list[Coluna], parent=None):
        super().__init__(parent)
        self.colunas = colunas
        self.campos: dict[str, QWidget] = {}
        disposicao = QFormLayout(self)
        for coluna in colunas:
            if coluna.tipo == BOOL:
                campo = QCheckBox()
            elif coluna.tipo == ESCOLHA:
                campo = QComboBox()
                for valor, rotulo in opcoes_da_coluna(coluna, sessao):
                    campo.addItem(rotulo, valor)
            else:
                campo = QLineEdit()
                if coluna.tipo == DATA:
                    campo.setPlaceholderText("dd/mm/aaaa")
            if coluna.dica:
                campo.setToolTip(coluna.dica)
            self.campos[coluna.campo] = campo
            disposicao.addRow(coluna.titulo + (" *" if coluna.obrigatorio else ""), campo)

    def preencher(self, obj) -> None:
        for coluna in self.colunas:
            campo = self.campos[coluna.campo]
            valor = getattr(obj, coluna.campo)
            if coluna.tipo == BOOL:
                campo.setChecked(bool(valor))
            elif coluna.tipo == ESCOLHA:
                for n in range(campo.count()):
                    if campo.itemData(n) == valor:
                        campo.setCurrentIndex(n)
                        break
            else:
                campo.setText(formatar(coluna, valor))

    def valores(self) -> dict[str, Any]:
        """Lê e valida todos os campos. Levanta ValueError no primeiro que for inválido."""
        lidos = {}
        for coluna in self.colunas:
            campo = self.campos[coluna.campo]
            if coluna.tipo == BOOL:
                lidos[coluna.campo] = campo.isChecked()
            elif coluna.tipo == ESCOLHA:
                lidos[coluna.campo] = campo.currentData()
                if lidos[coluna.campo] is None and coluna.obrigatorio:
                    raise ValueError(f"«{coluna.titulo}» é obrigatório.")
            else:
                try:
                    lidos[coluna.campo] = interpretar(coluna, campo.text())
                except ValueError as erro:
                    raise ValueError(f"{coluna.titulo}: {erro}") from None
        return lidos

    def aplicar(self, obj) -> None:
        for campo, valor in self.valores().items():
            setattr(obj, campo, valor)
