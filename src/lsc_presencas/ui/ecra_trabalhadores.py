"""Ecrã «Trabalhadores»: lista com pesquisa e ficha individual."""

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..modelos import SalarioBase, Trabalhador
from . import definicoes as d
from .formatos import sem_acentos
from .tabela import Formulario, ModeloTabela, VistaTabela, mensagem_de_erro


class FiltroTrabalhadores(QSortFilterProxyModel):
    """Filtra por nome (sem distinguir maiúsculas nem acentos) e esconde os inativos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._texto = ""
        self._mostrar_inativos = False
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def definir_texto(self, texto: str) -> None:
        self._texto = sem_acentos(texto.strip())
        self.invalidate()

    def definir_mostrar_inativos(self, mostrar: bool) -> None:
        self._mostrar_inativos = bool(mostrar)
        self.invalidate()

    def filterAcceptsRow(self, linha, pai) -> bool:
        modelo = self.sourceModel()
        trabalhador = modelo.linhas[linha]
        if modelo.pendente(trabalhador):
            return True
        if not self._mostrar_inativos and not trabalhador.ativo:
            return False
        return self._texto in sem_acentos(trabalhador.nome or "")


class FichaTrabalhador(QDialog):
    """Ficha: dados, valores de exceção e histórico do salário base."""

    def __init__(self, sessao: Session, trabalhador: Trabalhador, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.trabalhador = trabalhador
        self.setWindowTitle(f"Ficha — {trabalhador.numero} {trabalhador.nome}")
        self.resize(760, 640)

        self.dados = Formulario(sessao, d.COLUNAS_TRABALHADOR)
        self.excecoes = Formulario(sessao, d.COLUNAS_EXCECOES)
        self.dados.preencher(trabalhador)
        self.excecoes.preencher(trabalhador)

        grupo_dados = QGroupBox("Dados")
        QVBoxLayout(grupo_dados).addWidget(self.dados)
        grupo_excecoes = QGroupBox("Valores de exceção (vazio = usa o valor da empresa)")
        QVBoxLayout(grupo_excecoes).addWidget(self.excecoes)

        self.modelo_salarios = ModeloTabela(
            sessao,
            SalarioBase,
            d.COLUNAS_SALARIO,
            consulta=lambda: (
                select(SalarioBase)
                .where(SalarioBase.trabalhador_id == trabalhador.id)
                .order_by(SalarioBase.inicio_vigencia)
            ),
            ao_criar=lambda salario, _s: setattr(salario, "trabalhador_id", trabalhador.id),
        )
        self.salarios = VistaTabela(self.modelo_salarios, nome_registo="salário")
        self.aviso_salario = QLabel("Este trabalhador ainda não tem salário base.")
        self.aviso_salario.setStyleSheet("background:#FFF3B0; padding:4px;")
        grupo_salarios = QGroupBox(
            "Salário base — histórico (as alterações nesta tabela são gravadas de imediato)"
        )
        disposicao_salarios = QVBoxLayout(grupo_salarios)
        disposicao_salarios.addWidget(self.aviso_salario)
        disposicao_salarios.addWidget(self.salarios)
        self.modelo_salarios.alterado.connect(self._atualizar_aviso_salario)
        self._atualizar_aviso_salario()

        self.erro = QLabel()
        self.erro.setStyleSheet("color:#B00020;")
        self.erro.setWordWrap(True)
        botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botoes.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self.guardar)
        botoes.rejected.connect(self.reject)

        cima = QHBoxLayout()
        cima.addWidget(grupo_dados, 1)
        cima.addWidget(grupo_excecoes, 1)
        disposicao = QVBoxLayout(self)
        disposicao.addLayout(cima)
        disposicao.addWidget(grupo_salarios, 1)
        disposicao.addWidget(self.erro)
        disposicao.addWidget(botoes)

    def _atualizar_aviso_salario(self) -> None:
        gravados = [s for s in self.modelo_salarios.linhas if not self.modelo_salarios.pendente(s)]
        self.aviso_salario.setVisible(not gravados)

    def guardar(self) -> bool:
        try:
            valores = {**self.dados.valores(), **self.excecoes.valores()}
            for campo, valor in valores.items():
                setattr(self.trabalhador, campo, valor)
            self.sessao.commit()
        except (ValueError, SQLAlchemyError) as erro:
            self.sessao.rollback()
            self.erro.setText(mensagem_de_erro(erro))
            return False
        self.accept()
        return True


class EcraTrabalhadores(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.modelo = ModeloTabela(
            sessao,
            Trabalhador,
            [*d.COLUNAS_TRABALHADOR, d.COLUNA_SALARIO_ATUAL],
            consulta=lambda: select(Trabalhador).order_by(Trabalhador.numero),
            ao_criar=d.preparar_trabalhador,
        )
        self.filtro = FiltroTrabalhadores(self)
        self.vista = VistaTabela(self.modelo, proxy=self.filtro, nome_registo="trabalhador")
        self.vista.tabela.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self.pesquisa = QLineEdit()
        self.pesquisa.setPlaceholderText("Pesquisar por nome…")
        self.pesquisa.setClearButtonEnabled(True)
        self.mostrar_inativos = QCheckBox("Mostrar inativos")
        self.botao_ficha = QPushButton("Ficha…")
        self.contagem = QLabel()

        self.vista.barra.insertWidget(2, self.botao_ficha)
        self.vista.barra.addWidget(self.pesquisa, 2)
        self.vista.barra.addWidget(self.mostrar_inativos)
        self.vista.barra.addWidget(self.contagem)

        QVBoxLayout(self).addWidget(self.vista)

        self.pesquisa.textChanged.connect(self.filtro.definir_texto)
        self.mostrar_inativos.toggled.connect(self.filtro.definir_mostrar_inativos)
        self.botao_ficha.clicked.connect(self.abrir_ficha)
        for sinal in (
            self.filtro.modelReset,
            self.filtro.rowsInserted,
            self.filtro.rowsRemoved,
            self.filtro.layoutChanged,
        ):
            sinal.connect(self._atualizar_contagem)
        self._atualizar_contagem()

    def _atualizar_contagem(self, *_args) -> None:
        self.contagem.setText(f"{self.filtro.rowCount()} de {self.modelo.rowCount()}")

    def recarregar(self) -> None:
        self.vista.recarregar()

    def abrir_ficha(self) -> None:
        trabalhador = self.vista.objeto_atual()
        if trabalhador is None:
            self.vista.estado.setText("Selecione primeiro um trabalhador.")
            return
        if self.modelo.pendente(trabalhador):
            self.vista.estado.setText("Preencha primeiro o nº e o nome para gravar o trabalhador.")
            return
        FichaTrabalhador(self.sessao, trabalhador, self).exec()
        self.recarregar()
