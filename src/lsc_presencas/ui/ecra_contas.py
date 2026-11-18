"""Login, criação da primeira conta, gestão de contas e mudança de palavra-passe."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import contas
from ..modelos import PERFIL_ADMIN, PERFIL_UTILIZADOR, Utilizador
from .lista import nova_lista, preencher

ESTILO_ERRO = "color:#B00020;"
ESTILO_OK = "color:#1B6E1B;"


def _campo_senha() -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    return campo


class _Dialogo(QDialog):
    """Base dos diálogos: formulário, linha de erro e botões OK/Cancelar em português."""

    def __init__(self, titulo: str, texto_ok: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(380)
        self.formulario = QFormLayout()
        self.erro = QLabel()
        self.erro.setStyleSheet(ESTILO_ERRO)
        self.erro.setWordWrap(True)
        self.botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.botoes.button(QDialogButtonBox.StandardButton.Ok).setText(texto_ok)
        self.botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.botoes.accepted.connect(self.confirmar)
        self.botoes.rejected.connect(self.reject)
        self.disposicao = QVBoxLayout(self)
        self.disposicao.addLayout(self.formulario)
        self.disposicao.addWidget(self.erro)
        self.disposicao.addWidget(self.botoes)

    def executar(self) -> None:
        raise NotImplementedError

    def confirmar(self) -> bool:
        try:
            self.executar()
        except (ValueError, PermissionError) as erro:
            self.erro.setText(str(erro))
            return False
        except SQLAlchemyError as erro:
            self.erro.setText(f"Não foi possível gravar: {erro}")
            return False
        self.accept()
        return True


class DialogoLogin(_Dialogo):
    """Pede o nome de utilizador e a palavra-passe. `self.conta` fica com a conta autenticada."""

    def __init__(self, sessao: Session, parent=None):
        super().__init__("LSC Presenças — iniciar sessão", "Entrar", parent)
        self.sessao = sessao
        self.conta: Utilizador | None = None
        self.campo_utilizador = QLineEdit()
        self.campo_senha = _campo_senha()
        self.formulario.addRow("Nome de utilizador", self.campo_utilizador)
        self.formulario.addRow("Palavra-passe", self.campo_senha)

    def executar(self) -> None:
        try:
            self.conta = contas.autenticar(
                self.sessao, self.campo_utilizador.text(), self.campo_senha.text()
            )
        finally:
            self.campo_senha.clear()


class DialogoConta(_Dialogo):
    """Cria uma conta. Com `primeira=True`, cria o primeiro administrador."""

    def __init__(self, sessao: Session, *, primeira: bool = False, parent=None):
        titulo = "Criar a conta de administrador" if primeira else "Nova conta"
        super().__init__(titulo, "Criar", parent)
        self.sessao = sessao
        self.conta: Utilizador | None = None
        if primeira:
            aviso = QLabel(
                "Ainda não há contas. Crie a conta de administrador: é com ela que se criam "
                "as outras. Guarde bem a palavra-passe."
            )
            aviso.setWordWrap(True)
            self.disposicao.insertWidget(0, aviso)
        self.campo_utilizador = QLineEdit()
        self.campo_nome = QLineEdit()
        self.caixa_perfil = QComboBox()
        for perfil, nome in contas.PERFIS.items():
            self.caixa_perfil.addItem(nome, perfil)
        self.caixa_perfil.setCurrentIndex(
            self.caixa_perfil.findData(PERFIL_ADMIN if primeira else PERFIL_UTILIZADOR)
        )
        self.caixa_perfil.setEnabled(not primeira)
        self.campo_senha = _campo_senha()
        self.campo_repetir = _campo_senha()
        self.formulario.addRow("Nome de utilizador", self.campo_utilizador)
        self.formulario.addRow("Nome da pessoa", self.campo_nome)
        self.formulario.addRow("Perfil", self.caixa_perfil)
        self.formulario.addRow(
            f"Palavra-passe (mín. {contas.TAMANHO_MINIMO} caracteres)", self.campo_senha
        )
        self.formulario.addRow("Repetir a palavra-passe", self.campo_repetir)

    def executar(self) -> None:
        if self.campo_senha.text() != self.campo_repetir.text():
            raise contas.ErroDeConta("As duas palavras-passe não são iguais.")
        self.conta = contas.criar(
            self.sessao,
            self.campo_utilizador.text(),
            self.campo_nome.text(),
            self.campo_senha.text(),
            self.caixa_perfil.currentData(),
        )


class DialogoSenha(_Dialogo):
    """Define uma palavra-passe nova para uma conta (a própria ou, sendo administrador, outra)."""

    def __init__(self, sessao: Session, conta: Utilizador, *, recuperacao=False, parent=None):
        super().__init__(f"Palavra-passe de «{conta.nome_utilizador}»", "Guardar", parent)
        self.sessao = sessao
        self.conta = conta
        self.recuperacao = recuperacao
        self.campo_senha = _campo_senha()
        self.campo_repetir = _campo_senha()
        self.formulario.addRow(
            f"Palavra-passe nova (mín. {contas.TAMANHO_MINIMO} caracteres)", self.campo_senha
        )
        self.formulario.addRow("Repetir a palavra-passe", self.campo_repetir)

    def executar(self) -> None:
        if self.campo_senha.text() != self.campo_repetir.text():
            raise contas.ErroDeConta("As duas palavras-passe não são iguais.")
        contas.definir_senha(
            self.sessao, self.conta, self.campo_senha.text(), recuperacao=self.recuperacao
        )


class EcraContas(QWidget):
    """Gestão de contas (só para administradores)."""

    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.contas: list[Utilizador] = []
        self.tabela = nova_lista()
        self.botao_nova = QPushButton("Nova conta…")
        self.botao_senha = QPushButton("Repor a palavra-passe…")
        self.botao_perfil = QPushButton("Mudar o perfil")
        self.botao_ativa = QPushButton("Ativar / desativar")
        self.mensagem = QLabel()
        self.mensagem.setWordWrap(True)
        ajuda = QLabel(
            "Administrador: faz tudo. Utilizador: marca presenças, faz lançamentos, vê e "
            "exporta; não altera fichas, salários, tabelas nem parâmetros, não fecha nem "
            "reabre meses, não importa e não gere contas. As contas não se apagam (ficam na "
            "auditoria): desativam-se."
        )
        ajuda.setWordWrap(True)

        barra = QHBoxLayout()
        for botao in (self.botao_nova, self.botao_senha, self.botao_perfil, self.botao_ativa):
            barra.addWidget(botao)
        barra.addStretch(1)
        disposicao = QVBoxLayout(self)
        disposicao.addLayout(barra)
        disposicao.addWidget(ajuda)
        disposicao.addWidget(self.tabela, 1)
        disposicao.addWidget(self.mensagem)

        self.botao_nova.clicked.connect(self.nova)
        self.botao_senha.clicked.connect(self.repor_senha)
        self.botao_perfil.clicked.connect(self.mudar_perfil)
        self.botao_ativa.clicked.connect(self.alternar_ativa)
        self.recarregar()

    def recarregar(self) -> None:
        self.contas = contas.listar(self.sessao)
        preencher(
            self.tabela,
            ["Nome de utilizador", "Nome", "Perfil", "Estado", "Último início de sessão"],
            [
                [
                    c.nome_utilizador,
                    c.nome,
                    contas.PERFIS.get(c.perfil, c.perfil),
                    "Ativa" if c.ativo else "Desativada",
                    c.ultimo_login,
                ]
                for c in self.contas
            ],
        )

    def selecionada(self) -> Utilizador | None:
        linha = self.tabela.currentRow()
        if 0 <= linha < len(self.contas):
            return self.contas[linha]
        self._dizer("Selecione primeiro uma conta na lista.", erro=True)
        return None

    def selecionar(self, nome_utilizador: str) -> None:
        for linha, conta in enumerate(self.contas):
            if conta.nome_utilizador == nome_utilizador:
                self.tabela.setCurrentCell(linha, 0)

    def _dizer(self, texto: str, erro: bool = False) -> None:
        self.mensagem.setStyleSheet(ESTILO_ERRO if erro else ESTILO_OK)
        self.mensagem.setText(texto)

    def _alterar(self, conta: Utilizador, mensagem: str, **mudancas) -> bool:
        nome = conta.nome_utilizador
        try:
            contas.alterar(self.sessao, conta, **mudancas)
        except (ValueError, PermissionError) as erro:
            self._dizer(str(erro), erro=True)
            return False
        self.recarregar()
        self.selecionar(nome)
        self._dizer(mensagem)
        return True

    def nova(self) -> None:
        dialogo = DialogoConta(self.sessao, parent=self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.recarregar()
            self._dizer(f"Conta «{dialogo.conta.nome_utilizador}» criada.")

    def repor_senha(self) -> None:
        conta = self.selecionada()
        if conta is None:
            return
        if DialogoSenha(self.sessao, conta, parent=self).exec() == QDialog.DialogCode.Accepted:
            self._dizer(f"Palavra-passe de «{conta.nome_utilizador}» alterada.")

    def mudar_perfil(self) -> bool:
        conta = self.selecionada()
        if conta is None:
            return False
        novo = PERFIL_UTILIZADOR if conta.perfil == PERFIL_ADMIN else PERFIL_ADMIN
        return self._alterar(
            conta, f"«{conta.nome_utilizador}» passou a {contas.PERFIS[novo]}.", perfil=novo
        )

    def alternar_ativa(self) -> bool:
        conta = self.selecionada()
        if conta is None:
            return False
        estado = "desativada" if conta.ativo else "ativada"
        return self._alterar(
            conta, f"Conta «{conta.nome_utilizador}» {estado}.", ativo=not conta.ativo
        )


def pedir_login(sessao: Session) -> Utilizador | None:
    """Cria a primeira conta (se ainda não houver nenhuma) ou pede o login.

    Devolve a conta autenticada, ou None se a pessoa cancelou.
    """
    if not contas.ha_contas(sessao):
        dialogo = DialogoConta(sessao, primeira=True)
        dialogo.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialogo.conta
    dialogo = DialogoLogin(sessao)
    if dialogo.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialogo.conta
