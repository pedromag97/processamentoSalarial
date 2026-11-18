"""Assistente de importação da folha «s-27»: nada é gravado antes do botão «Importar»."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, importacao, presencas
from ..modelos import CodigoPresenca, Empresa, Trabalhador

POR_DECIDIR = "— escolher —"


def _tabela(titulos: list[str]) -> QTableWidget:
    tabela = QTableWidget(0, len(titulos))
    tabela.setHorizontalHeaderLabels(titulos)
    tabela.verticalHeader().setVisible(False)
    tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabela.horizontalHeader().setStretchLastSection(True)
    return tabela


def _celula(texto) -> QTableWidgetItem:
    return QTableWidgetItem("" if texto is None else str(texto))


def ficheiro_por_omissao() -> str:
    pasta = config.pasta_dados_reais()
    if pasta and pasta.is_dir():
        candidatos = sorted(
            f for f in pasta.glob("*PONTO*Semanal*.xlsx") if not f.name.startswith("~$")
        )
        if candidatos:
            return str(candidatos[-1])
    return ""


class PaginaFicheiro(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("1. Ficheiro")
        self.setSubTitle(
            "Escolha o Excel da folha de ponto semanal. Nesta fase só se lê o ficheiro."
        )
        self.caminho = QLineEdit(ficheiro_por_omissao())
        procurar = QPushButton("Procurar…")
        procurar.clicked.connect(self._procurar)
        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        linha = QHBoxLayout()
        linha.addWidget(self.caminho, 1)
        linha.addWidget(procurar)
        disposicao = QVBoxLayout(self)
        disposicao.addLayout(linha)
        disposicao.addWidget(self.aviso)
        disposicao.addStretch(1)

    def initializePage(self):
        existentes = self.assistente.sessao.scalar(select(func.count()).select_from(Trabalhador))
        self.aviso.setText(
            f"Atenção: a base de dados já tem {existentes} trabalhadores. Os que tiverem o mesmo "
            "nome não são criados outra vez; só recebem as marcações."
            if existentes
            else ""
        )

    def _procurar(self):
        escolhido, _ = QFileDialog.getOpenFileName(
            self, "Folha de ponto semanal", self.caminho.text(), "Excel (*.xlsx *.xlsm)"
        )
        if escolhido:
            self.caminho.setText(escolhido)

    def validatePage(self) -> bool:
        try:
            self.assistente.ler(self.caminho.text().strip())
        except Exception as erro:  # noqa: BLE001 - qualquer falha de leitura mostra-se ao utilizador
            self.aviso.setStyleSheet("color:#B00020;")
            self.aviso.setText(f"Não consegui ler o ficheiro: {erro}")
            return False
        return True


class PaginaCodigos(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("2. Códigos antigos")
        self.setSubTitle(
            "Para cada valor encontrado nas células dos dias, confirme o código novo. "
            "«Ignorar» não importa essas células."
        )
        self.tabela = _tabela(["Valor no Excel", "Ocorrências", "Passa a ser"])
        self.aviso = QLabel()
        self.aviso.setStyleSheet("color:#B00020;")
        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.tabela)
        disposicao.addWidget(self.aviso)
        self.escolhas: dict[str, QComboBox] = {}

    def initializePage(self):
        a = self.assistente
        codigos = [
            c
            for c in a.sessao.scalars(
                select(CodigoPresenca.codigo)
                .where(CodigoPresenca.ativo)
                .order_by(CodigoPresenca.ordem)
            )
        ]
        self.escolhas = {}
        valores = sorted(a.leitura.valores.items(), key=lambda par: (-par[1], par[0]))
        self.tabela.setRowCount(len(valores))
        for n, (valor, ocorrencias) in enumerate(valores):
            caixa = QComboBox()
            caixa.addItem(POR_DECIDIR, None)
            for codigo in codigos:
                caixa.addItem(codigo, codigo)
            proposto = a.mapeamento.get(valor)
            if proposto and caixa.findData(proposto) < 0:
                caixa.addItem(proposto, proposto)  # ex.: «PF+2»
            caixa.addItem("Ignorar", importacao.IGNORAR)
            caixa.setCurrentIndex(max(caixa.findData(proposto), 0) if proposto is not None else 0)
            self.escolhas[valor] = caixa
            self.tabela.setItem(n, 0, _celula(valor))
            self.tabela.setItem(n, 1, _celula(ocorrencias))
            self.tabela.setCellWidget(n, 2, caixa)
        self.tabela.resizeColumnsToContents()
        if not valores:
            self.aviso.setStyleSheet("")
            self.aviso.setText("A folha não tem marcações: só há trabalhadores para importar.")

    def validatePage(self) -> bool:
        a = self.assistente
        a.mapeamento = {valor: caixa.currentData() for valor, caixa in self.escolhas.items()}
        por_decidir = [v for v, destino in a.mapeamento.items() if destino is None]
        if por_decidir:
            self.aviso.setStyleSheet("color:#B00020;")
            self.aviso.setText("Falta decidir: " + ", ".join(f"«{v}»" for v in por_decidir))
            return False
        return True


class PaginaDuplicados(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("3. Nomes repetidos")
        self.setSubTitle(
            "Estes nomes aparecem em mais de uma linha (comparados sem maiúsculas nem acentos). "
            "Diga se é a mesma pessoa ou se são pessoas diferentes."
        )
        self.tabela = _tabela(["Nomes", "Linhas do Excel", "Cliente / viatura / zona", "Decisão"])
        self.aviso = QLabel()
        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.tabela)
        disposicao.addWidget(self.aviso)
        self.escolhas: dict[str, QComboBox] = {}

    def initializePage(self):
        grupos = importacao.grupos_duplicados(self.assistente.leitura)
        self.escolhas = {}
        self.tabela.setRowCount(len(grupos))
        for n, (chave, linhas) in enumerate(grupos.items()):
            caixa = QComboBox()
            caixa.addItem(POR_DECIDIR, None)
            caixa.addItem("É a mesma pessoa", True)
            caixa.addItem("São pessoas diferentes", False)
            anterior = self.assistente.mesma_pessoa.get(chave)
            caixa.setCurrentIndex(max(caixa.findData(anterior), 0) if anterior is not None else 0)
            self.escolhas[chave] = caixa
            detalhes = "  |  ".join(
                " / ".join(x or "—" for x in (linha.cliente, linha.viatura, linha.zona))
                for linha in linhas
            )
            self.tabela.setItem(n, 0, _celula("  |  ".join(linha.nome for linha in linhas)))
            self.tabela.setItem(n, 1, _celula(", ".join(str(linha.linha) for linha in linhas)))
            self.tabela.setItem(n, 2, _celula(detalhes))
            self.tabela.setCellWidget(n, 3, caixa)
        self.tabela.resizeColumnsToContents()
        self.aviso.setStyleSheet("")
        self.aviso.setText("" if grupos else "Não há nomes repetidos.")

    def validatePage(self) -> bool:
        a = self.assistente
        a.mesma_pessoa = {chave: caixa.currentData() for chave, caixa in self.escolhas.items()}
        if any(decisao is None for decisao in a.mesma_pessoa.values()):
            self.aviso.setStyleSheet("color:#B00020;")
            self.aviso.setText("Falta decidir pelo menos um nome.")
            return False
        a.construir_plano()
        return True


class PaginaEmpresas(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("4. Empresa de cada trabalhador")
        self.setSubTitle(
            "A folha não diz a empresa. Selecione várias linhas (Ctrl ou Shift) e atribua a "
            "empresa de uma vez. Pode deixar por atribuir e fazê-lo depois em Trabalhadores."
        )
        self.tabela = _tabela(["Nome", "Cliente", "Viatura", "Zona", "Marcações", "Empresa"])
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.escolha = QComboBox()
        self.botao = QPushButton("Atribuir aos selecionados")
        self.botao.clicked.connect(self.atribuir_aos_selecionados)
        self.resumo = QLabel()
        linha = QHBoxLayout()
        linha.addWidget(QLabel("Empresa:"))
        linha.addWidget(self.escolha)
        linha.addWidget(self.botao)
        linha.addStretch(1)
        linha.addWidget(self.resumo)
        disposicao = QVBoxLayout(self)
        disposicao.addLayout(linha)
        disposicao.addWidget(self.tabela)

    def initializePage(self):
        a = self.assistente
        self.escolha.clear()
        self.escolha.addItem("(sem empresa)", None)
        for nome in a.empresas:
            self.escolha.addItem(nome, nome)
        self.tabela.setRowCount(len(a.pessoas))
        for n, pessoa in enumerate(a.pessoas):
            for coluna, texto in enumerate(
                (pessoa.nome, pessoa.cliente, pessoa.viatura, pessoa.zona, len(pessoa.valores))
            ):
                self.tabela.setItem(n, coluna, _celula(texto))
        self._mostrar_empresas()
        self.tabela.resizeColumnsToContents()

    def _mostrar_empresas(self):
        pessoas = self.assistente.pessoas
        for n, pessoa in enumerate(pessoas):
            self.tabela.setItem(n, 5, _celula(pessoa.empresa))
        sem = sum(1 for p in pessoas if not p.empresa)
        self.resumo.setText(f"{len(pessoas)} trabalhadores, {sem} sem empresa")

    def atribuir(self, linhas: list[int], empresa: str | None) -> None:
        for n in linhas:
            self.assistente.pessoas[n].empresa = empresa
        self._mostrar_empresas()

    def atribuir_aos_selecionados(self):
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()})
        self.atribuir(linhas, self.escolha.currentData())


class PaginaResumo(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("5. Confirmar")
        self.setSubTitle("Ainda não foi gravado nada. «Importar» grava tudo de uma vez.")
        self.setCommitPage(True)
        self.setButtonText(QWizard.WizardButton.CommitButton, "Importar")
        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.erro = QLabel()
        self.erro.setStyleSheet("color:#B00020;")
        self.erro.setWordWrap(True)
        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.texto)
        disposicao.addWidget(self.erro)

    def initializePage(self):
        self.texto.setPlainText(self.assistente.pre_visualizacao())

    def validatePage(self) -> bool:
        try:
            self.assistente.importar()
        except Exception as erro:  # noqa: BLE001 - a gravação é tudo ou nada; mostra-se o motivo
            self.erro.setText(f"Não importei nada: {erro}")
            return False
        return True


class PaginaRelatorio(QWizardPage):
    def __init__(self, assistente: "AssistenteImportacao"):
        super().__init__()
        self.assistente = assistente
        self.setTitle("Importação concluída")
        self.texto = QPlainTextEdit()
        self.texto.setReadOnly(True)
        self.local = QLabel()
        self.local.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        disposicao = QVBoxLayout(self)
        disposicao.addWidget(self.local)
        disposicao.addWidget(self.texto)

    def initializePage(self):
        a = self.assistente
        self.texto.setPlainText(a.relatorio.texto())
        self.local.setText(f"Relatório guardado em: {a.ficheiro_relatorio}")


class AssistenteImportacao(QWizard):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.setWindowTitle("Importar a folha de ponto (s-27)")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.WizardOption.NoCancelButtonOnLastPage, True)
        self.setButtonText(QWizard.WizardButton.NextButton, "Seguinte >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Anterior")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Fechar")
        self.resize(980, 640)

        self.leitura: importacao.Leitura | None = None
        self.mapeamento: dict[str, str | None] = {}
        self.mesma_pessoa: dict[str, bool] = {}
        self.pessoas: list[importacao.Pessoa] = []
        self.empresas: list[str] = []
        self.relatorio: importacao.Relatorio | None = None
        self.ficheiro_relatorio: Path | None = None

        self.pagina_ficheiro = PaginaFicheiro(self)
        self.pagina_codigos = PaginaCodigos(self)
        self.pagina_duplicados = PaginaDuplicados(self)
        self.pagina_empresas = PaginaEmpresas(self)
        self.pagina_resumo = PaginaResumo(self)
        self.pagina_relatorio = PaginaRelatorio(self)
        for pagina in (
            self.pagina_ficheiro,
            self.pagina_codigos,
            self.pagina_duplicados,
            self.pagina_empresas,
            self.pagina_resumo,
            self.pagina_relatorio,
        ):
            self.addPage(pagina)

    # --- Passos (também usados diretamente nos testes) ---

    def ler(self, caminho: str) -> None:
        if not caminho:
            raise ValueError("escolha primeiro o ficheiro.")
        self.leitura = importacao.ler_s27(caminho)
        self.mapeamento = importacao.mapeamento_inicial(
            self.leitura, presencas.codigos_ativos(self.sessao)
        )
        self.mesma_pessoa = {}
        self.pessoas = []
        existentes = list(self.sessao.scalars(select(Empresa.nome).order_by(Empresa.nome)))
        self.empresas = existentes or list(importacao.EMPRESAS_BASE)

    def construir_plano(self) -> None:
        """Junta os duplicados conforme as decisões e sugere a empresa pelos mapas de férias."""
        anteriores = {tuple(p.linhas): p.empresa for p in self.pessoas}
        self.pessoas = importacao.construir_plano(self.leitura, self.mesma_pessoa)
        folhas = importacao.folhas_dos_mapas_de_ferias(self.leitura.caminho.parent)
        for pessoa in self.pessoas:
            if tuple(pessoa.linhas) in anteriores:
                pessoa.empresa = anteriores[tuple(pessoa.linhas)]  # mantém o que já se escolheu
            else:
                pessoa.empresa = importacao.sugerir_empresa(pessoa.nome, folhas, self.empresas)

    def pre_visualizacao(self) -> str:
        leitura, pessoas = self.leitura, self.pessoas
        importadas = sum(
            1
            for p in pessoas
            for v in p.valores.values()
            if self.mapeamento.get(v) not in (None, importacao.IGNORAR)
        )
        ignoradas = sum(len(p.valores) for p in pessoas) - importadas
        linhas = [
            f"Ficheiro: {leitura.caminho}",
            f"Período da folha: {leitura.primeiro_dia:%d/%m/%Y} a {leitura.ultimo_dia:%d/%m/%Y}",
            "",
            f"Trabalhadores: {len(pessoas)} "
            f"({sum(1 for p in pessoas if not p.empresa)} sem empresa, "
            f"{sum(1 for p in pessoas if not p.cliente)} sem cliente)",
            f"Clientes: {', '.join(leitura.clientes) or '—'}",
            f"Viaturas: {', '.join(leitura.viaturas) or '—'}",
            f"Zonas: {', '.join(leitura.zonas) or '—'}",
            f"Marcações a importar: {importadas} (ignoradas: {ignoradas})",
            "",
            "Códigos:",
        ]
        for valor, n in sorted(leitura.valores.items()):
            destino = self.mapeamento.get(valor)
            linhas.append(
                f"  «{valor}» ({n}) → {'ignorar' if destino == importacao.IGNORAR else destino}"
            )
        linhas += [
            "",
            f"Discrepâncias no dia do mês: {len(leitura.discrepancias)} (vão no relatório)",
        ]
        linhas += ["", "Notas:"] + [f"  {nota}" for nota in leitura.notas or ["(nenhuma)"]]
        notas_pessoas = [f"  {p.nome}: {nota}" for p in pessoas for nota in p.notas]
        if notas_pessoas:
            linhas += ["", "Ao juntar linhas da mesma pessoa:"] + notas_pessoas
        return "\n".join(linhas)

    def importar(self) -> None:
        self.relatorio = importacao.gravar(self.sessao, self.leitura, self.pessoas, self.mapeamento)
        self.ficheiro_relatorio = (
            config.pasta_saidas() / f"importacao_s27_{datetime.now():%Y%m%d_%H%M%S}.txt"
        )
        self.ficheiro_relatorio.write_text(self.relatorio.texto(), encoding="utf-8")
