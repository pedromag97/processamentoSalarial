"""Diálogo «Ligação ao servidor» e abertura da base de dados ao arrancar."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .. import config, servidor, transferencia

ESTILO_ERRO = "color:#B00020;"
ESTILO_OK = "color:#1B6E1B;"
MENSAGEM_REABRIR = "A ligação deste PC foi alterada. O programa vai fechar: abra-o outra vez."


class DialogoLigacao(QDialog):
    """Dados do servidor PostgreSQL. A palavra-passe fica no cofre de credenciais do Windows.

    `self.mudou` fica True se a ligação deste PC foi alterada (é preciso reabrir o programa).
    """

    def __init__(self, erro: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ligação ao servidor")
        self.setMinimumWidth(520)
        self.mudou = False
        self.pode_enviar = False
        self.resultado: transferencia.Resultado | None = None
        self.situacao: servidor.Situacao | None = None
        atual = config.ler_ligacao()

        explicacao = QLabel(
            "Com um servidor, todas as pessoas trabalham sobre os mesmos dados. Peça ao "
            "administrador o endereço do servidor e as credenciais. Fora do escritório, "
            "ligue primeiro a VPN."
        )
        explicacao.setWordWrap(True)
        self.campo_servidor = QLineEdit(atual.servidor if atual else "")
        self.campo_servidor.setPlaceholderText("nome ou endereço IP do servidor")
        self.campo_porta = QSpinBox()
        self.campo_porta.setRange(1, 65535)
        self.campo_porta.setValue(atual.porta if atual else config.PORTA_POSTGRESQL)
        self.campo_base = QLineEdit(atual.base if atual else "lsc_presencas")
        self.campo_utilizador = QLineEdit(atual.utilizador if atual else "")
        self.campo_senha = QLineEdit()
        self.campo_senha.setEchoMode(QLineEdit.EchoMode.Password)
        if atual:
            self.campo_senha.setPlaceholderText("(guardada; escreva só para a mudar)")

        formulario = QFormLayout()
        formulario.addRow("Servidor", self.campo_servidor)
        formulario.addRow("Porta", self.campo_porta)
        formulario.addRow("Base de dados", self.campo_base)
        formulario.addRow("Utilizador do servidor", self.campo_utilizador)
        formulario.addRow("Palavra-passe do servidor", self.campo_senha)

        self.visto_enviar = QCheckBox(
            "Enviar para o servidor os dados que estão neste PC (o servidor está vazio)"
        )
        self.visto_enviar.setVisible(False)
        self.mensagem = QLabel(erro)
        self.mensagem.setStyleSheet(ESTILO_ERRO)
        self.mensagem.setWordWrap(True)

        self.botao_testar = QPushButton("Testar a ligação")
        self.botao_guardar = QPushButton("Guardar e usar o servidor")
        self.botao_guardar.setEnabled(False)
        self.botao_local = QPushButton("Usar o ficheiro deste PC")
        self.botao_local.setEnabled(atual is not None)
        self.botao_local.setToolTip(
            "Deixa de usar o servidor neste PC. Não apaga nada no servidor."
        )
        self.botao_fechar = QPushButton("Cancelar")
        botoes = QHBoxLayout()
        for botao in (self.botao_testar, self.botao_guardar, self.botao_local):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        botoes.addWidget(self.botao_fechar)

        disposicao = QVBoxLayout(self)
        disposicao.addWidget(explicacao)
        disposicao.addLayout(formulario)
        disposicao.addWidget(self.visto_enviar)
        disposicao.addWidget(self.mensagem)
        disposicao.addLayout(botoes)

        self.botao_testar.clicked.connect(self.testar)
        self.botao_guardar.clicked.connect(self.guardar)
        self.botao_local.clicked.connect(self.usar_local)
        self.botao_fechar.clicked.connect(self.reject)
        for campo in (self.campo_servidor, self.campo_base, self.campo_utilizador):
            campo.textEdited.connect(self._dados_mudaram)
        self.campo_senha.textEdited.connect(self._dados_mudaram)
        self.campo_porta.valueChanged.connect(self._dados_mudaram)

    def _dizer(self, texto: str, erro: bool = False) -> None:
        self.mensagem.setStyleSheet(ESTILO_ERRO if erro else ESTILO_OK)
        self.mensagem.setText(texto)

    def _dados_mudaram(self, *_args) -> None:
        self.situacao = None
        self.pode_enviar = False
        self.botao_guardar.setEnabled(False)
        self.visto_enviar.setVisible(False)

    def ligacao(self) -> config.Ligacao:
        valores = {
            "servidor": self.campo_servidor.text().strip(),
            "base": self.campo_base.text().strip(),
            "utilizador": self.campo_utilizador.text().strip(),
        }
        em_falta = [nome for nome, valor in valores.items() if not valor]
        if em_falta:
            raise servidor.ErroDeLigacao("Falta preencher: " + ", ".join(em_falta) + ".")
        return config.Ligacao(porta=self.campo_porta.value(), **valores)

    def senha(self, ligacao: config.Ligacao) -> str:
        """A que foi escrita; se o campo estiver vazio, a que já estava guardada."""
        return self.campo_senha.text() or config.ler_senha(ligacao)

    def testar(self) -> bool:
        try:
            ligacao = self.ligacao()
            self.situacao = servidor.verificar(ligacao, self.senha(ligacao))
        except ValueError as erro:
            self._dados_mudaram()
            self._dizer(str(erro), erro=True)
            return False
        s = self.situacao
        self.botao_guardar.setEnabled(True)
        self.pode_enviar = s.local_tem_dados and not s.servidor_tem_dados
        self.visto_enviar.setVisible(self.pode_enviar)
        self.visto_enviar.setChecked(self.pode_enviar)
        if s.servidor_tem_dados and s.local_tem_dados:
            texto = (
                "Ligação boa. O servidor já tem dados: este PC passa a usá-los. Os dados que "
                "estão no ficheiro deste PC ficam guardados, mas deixam de ser usados."
            )
        elif s.servidor_tem_dados:
            texto = "Ligação boa. O servidor já tem dados: este PC passa a usá-los."
        elif s.local_tem_dados:
            texto = "Ligação boa. O servidor está vazio: pode enviar os dados deste PC."
        else:
            texto = "Ligação boa. O servidor está vazio."
        self._dizer(texto)
        return True

    def guardar(self) -> bool:
        try:
            ligacao = self.ligacao()
            resultado = servidor.ligar(
                ligacao,
                self.senha(ligacao),
                enviar_dados_locais=self.pode_enviar and self.visto_enviar.isChecked(),
            )
        except (ValueError, PermissionError) as erro:
            self._dizer(str(erro), erro=True)
            return False
        self.campo_senha.clear()
        self.mudou = True
        self.resultado = resultado
        self.accept()
        return True

    def usar_local(self) -> None:
        config.remover_ligacao()
        self.mudou = True
        self.accept()
