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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import auditoria, bloqueios, contas
from ..modelos import (
    GER_QUANTIDADE_MANUAL,
    GER_UNITARIO,
    LinhaGer,
    QuantidadeGer,
    SalarioBase,
    Trabalhador,
)
from . import definicoes as d
from .ecra_auditoria import ListaAuditoria
from .formatos import sem_acentos
from .grelha import CADEADO
from .tabela import (
    SEM_PERMISSAO,
    Coluna,
    Formulario,
    ModeloTabela,
    VistaTabela,
    mensagem_de_erro,
)


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
        self.resize(900, 680)

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
            ao_gravar=self._auditar_salario,
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

        self.modelo_ger = ModeloTabela(
            sessao,
            LinhaGer,
            d.COLUNAS_LINHA_GER,
            consulta=lambda: (
                select(LinhaGer)
                .where(LinhaGer.trabalhador_id == trabalhador.id)
                .order_by(LinhaGer.ordem, LinhaGer.id)
            ),
            ao_criar=self._preparar_linha_ger,
            ao_gravar=self._auditar_linha_ger,
        )
        self.linhas_ger = VistaTabela(self.modelo_ger, nome_registo="ajuda")
        pagina_ger = QWidget()
        disposicao_ger = QVBoxLayout(pagina_ger)
        ajuda_ger = QLabel(
            "Ajudas combinadas com este trabalhador (bloco GER da folha de salário). As "
            "quantidades de cada mês escrevem-se no ecrã «Salários». As alterações nesta "
            "tabela são gravadas de imediato."
        )
        ajuda_ger.setWordWrap(True)
        disposicao_ger.addWidget(ajuda_ger)
        disposicao_ger.addWidget(self.linhas_ger, 1)

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
        self.botao_guardar = botoes.button(QDialogButtonBox.StandardButton.Save)
        # Quem abre a ficha para alterar fica com o cadeado do funcionário até a fechar.
        # `cadeado` é None se ficou com ele, ou o cadeado da pessoa que já o tinha.
        self.cadeado = bloqueios.pedir(sessao, trabalhador.id) if contas.e_admin() else None
        self.tem_cadeado = contas.e_admin() and self.cadeado is None
        if self.cadeado is not None:
            self.erro.setText(
                f"{CADEADO} {self.cadeado.descricao}. A ficha está só para consulta; abra-a "
                "outra vez quando essa pessoa sair."
            )
        if not contas.e_admin() or self.cadeado is not None:
            # Sem permissão para alterar, ou em uso: a ficha fica só para consulta.
            self.botao_guardar.setEnabled(False)
            self.botao_guardar.setToolTip(
                self.cadeado.descricao if self.cadeado is not None else SEM_PERMISSAO
            )
            self.dados.setEnabled(False)
            self.excecoes.setEnabled(False)
            self.salarios.bloquear(True)
            self.linhas_ger.bloquear(True)
            botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Fechar")

        cima = QHBoxLayout()
        cima.addWidget(grupo_dados, 1)
        cima.addWidget(grupo_excecoes, 1)
        pagina_ficha = QWidget()
        disposicao_ficha = QVBoxLayout(pagina_ficha)
        disposicao_ficha.addLayout(cima)
        disposicao_ficha.addWidget(grupo_salarios, 1)

        self.historico = ListaAuditoria(sessao, numero_trabalhador=trabalhador.numero)
        self.separadores = QTabWidget()
        self.separadores.addTab(pagina_ficha, "Ficha")
        self.separadores.addTab(pagina_ger, "Ajudas (GER)")
        self.separadores.addTab(self.historico, "Histórico de alterações")
        self.separadores.currentChanged.connect(lambda _: self.historico.recarregar())

        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.separadores, 1)
        disposicao.addWidget(self.erro)
        disposicao.addWidget(botoes)

    def _atualizar_aviso_salario(self) -> None:
        gravados = [s for s in self.modelo_salarios.linhas if not self.modelo_salarios.pendente(s)]
        self.aviso_salario.setVisible(not gravados)

    def _auditar_salario(self, sessao: Session, salario: SalarioBase, acao: str) -> None:
        def descrever(inicio, valor, ferias, natal) -> dict:
            return {
                "trabalhador": self.trabalhador.numero,
                "em_vigor_desde": inicio,
                "valor": valor,
                "duodecimo_ferias": ferias,
                "duodecimo_natal": natal,
            }

        with sessao.no_autoflush:
            antigo = None
            if acao != "criar":
                linha = sessao.execute(
                    select(
                        SalarioBase.inicio_vigencia,
                        SalarioBase.valor,
                        SalarioBase.duodecimo_ferias,
                        SalarioBase.duodecimo_natal,
                    ).where(SalarioBase.id == salario.id)
                ).first()
                antigo = descrever(*linha) if linha else None
            novo = (
                None
                if acao == "apagar"
                else descrever(
                    salario.inicio_vigencia,
                    salario.valor,
                    salario.duodecimo_ferias,
                    salario.duodecimo_natal,
                )
            )
            if acao == "alterar" and antigo == novo:
                return
            auditoria.registar(sessao, "salario_base", salario.id, acao, antigo, novo)

    def _preparar_linha_ger(self, linha: LinhaGer, _sessao: Session) -> None:
        linha.trabalhador_id = self.trabalhador.id
        linha.ordem = len(self.modelo_ger.linhas) + 1
        linha.unidade = "dia"
        linha.base = GER_UNITARIO
        linha.quantidade_de = GER_QUANTIDADE_MANUAL
        linha.ativo = True

    CAMPOS_GER = ("ordem", "nome", "unidade", "valor", "base", "quantidade_de", "ativo")

    def _auditar_linha_ger(self, sessao: Session, linha: LinhaGer, acao: str) -> None:
        def descrever(valores) -> dict:
            return {
                "trabalhador": self.trabalhador.numero,
                **dict(zip(self.CAMPOS_GER, valores, strict=True)),
            }

        with sessao.no_autoflush:
            antigo = None
            if acao != "criar":
                gravado = sessao.execute(
                    select(*(getattr(LinhaGer, c) for c in self.CAMPOS_GER)).where(
                        LinhaGer.id == linha.id
                    )
                ).first()
                antigo = descrever(gravado) if gravado else None
            if acao == "apagar":
                # As quantidades já escritas para esta linha vão com ela.
                sessao.execute(delete(QuantidadeGer).where(QuantidadeGer.linha_ger_id == linha.id))
            novo = (
                None
                if acao == "apagar"
                else descrever([getattr(linha, c) for c in self.CAMPOS_GER])
            )
            if acao == "alterar" and antigo == novo:
                return
            auditoria.registar(sessao, "linha_ger", linha.id, acao, antigo, novo)

    def done(self, resultado: int) -> None:
        """Ao fechar a ficha (guardar, cancelar ou fechar a janela), larga o cadeado."""
        if self.tem_cadeado:
            self.tem_cadeado = False
            try:
                bloqueios.largar(self.sessao, [self.trabalhador.id])
            except SQLAlchemyError:
                pass  # sem ligação: o cadeado caduca sozinho ao fim de 90 segundos
        super().done(resultado)

    def guardar(self) -> bool:
        if not contas.e_admin():
            self.erro.setText(SEM_PERMISSAO)
            return False
        if self.cadeado is not None:
            self.erro.setText(f"{CADEADO} {self.cadeado.descricao}.")
            return False
        try:
            bloqueios.exigir_livres(self.sessao, [self.trabalhador.id])
            valores = {**self.dados.valores(), **self.excecoes.valores()}
            with self.sessao.no_autoflush:
                gravado = self.sessao.execute(
                    select(*(getattr(Trabalhador, campo) for campo in valores)).where(
                        Trabalhador.id == self.trabalhador.id
                    )
                ).one()
            antes = dict(zip(valores, gravado, strict=True))
            mudou = [campo for campo, valor in valores.items() if antes[campo] != valor]
            for campo, valor in valores.items():
                setattr(self.trabalhador, campo, valor)
            if mudou:
                rotulos = {c.campo: c.titulo for c in (*d.COLUNAS_TRABALHADOR, *d.COLUNAS_EXCECOES)}
                escolhas = {
                    c.campo: dict(c.escolhas(self.sessao))
                    for c in d.COLUNAS_TRABALHADOR
                    if c.escolhas
                }

                def legivel(campo, valor):
                    return escolhas[campo].get(valor, valor) if campo in escolhas else valor

                numero = {"trabalhador": antes["numero"]}
                auditoria.registar(
                    self.sessao,
                    "trabalhador",
                    self.trabalhador.id,
                    "alterar",
                    numero | {rotulos[c]: legivel(c, antes[c]) for c in mudou},
                    numero | {rotulos[c]: legivel(c, valores[c]) for c in mudou},
                )
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
        self.cadeados: dict[int, bloqueios.Cadeado] = {}
        coluna_cadeado = Coluna(
            "cadeado",
            CADEADO,
            obter=lambda t: CADEADO if t.id in self.cadeados else "",
            dica="Com cadeado: outra pessoa está a mexer neste funcionário.",
        )
        self.modelo = ModeloTabela(
            sessao,
            Trabalhador,
            [*d.COLUNAS_TRABALHADOR, d.COLUNA_SALARIO_ATUAL, coluna_cadeado],
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
        self.vista.bloquear(not contas.e_admin())
        try:
            self.cadeados = bloqueios.de_outros(self.sessao)
        except SQLAlchemyError:
            self.sessao.rollback()
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
