"""Janela principal: navegação à esquerda e um ecrã de cada vez à direita."""

import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .. import __version__, backups, config, contas
from ..modelos import (
    PERFIL_ADMIN,
    CodigoPresenca,
    Empresa,
    Feriado,
    Marcacao,
    Trabalhador,
    Utilizador,
)
from .ecra_auditoria import EcraAuditoria
from .ecra_contas import DialogoSenha, EcraContas, pedir_login
from .ecra_fecho import EcraFecho
from .ecra_importacao import AssistenteImportacao
from .ecra_lancamentos import EcraLancamentos
from .ecra_ligacao import MENSAGEM_REABRIR, DialogoLigacao
from .ecra_presencas import EcraPresencas
from .ecra_relatorios import EcraRelatorios
from .ecra_tabelas import EcraTabelas
from .ecra_trabalhadores import EcraTrabalhadores


def resumo_bd(sessao: Session) -> dict[str, int]:
    def contar(modelo) -> int:
        return sessao.scalar(select(func.count()).select_from(modelo)) or 0

    return {
        "Empresas": contar(Empresa),
        "Trabalhadores": contar(Trabalhador),
        "Marcações": contar(Marcacao),
        "Códigos de presença": contar(CodigoPresenca),
        "Feriados": contar(Feriado),
    }


class EcraInicio(QWidget):
    """Estado da base de dados e a importação inicial da folha de ponto."""

    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.texto = QLabel()
        self.texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.texto.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.botao_importar = QPushButton("Importar a folha de ponto (s-27)…")
        self.botao_importar.clicked.connect(self.importar)
        self.botao_backup = QPushButton("Fazer uma cópia de segurança agora")
        self.botao_backup.clicked.connect(self.fazer_backup)
        self.botao_servidor = QPushButton("Ligação ao servidor…")
        self.botao_servidor.clicked.connect(self.ligacao_ao_servidor)
        self.botao_pasta = QPushButton("Abrir a pasta das cópias de segurança")
        self.botao_pasta.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.pasta_backups())))
        )
        self.mensagem = QLabel()
        self.mensagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disposicao = QVBoxLayout(self)
        disposicao.addStretch(1)
        disposicao.addWidget(self.texto)
        for botao in (
            self.botao_importar,
            self.botao_servidor,
            self.botao_backup,
            self.botao_pasta,
        ):
            disposicao.addWidget(botao, 0, Qt.AlignmentFlag.AlignCenter)
        disposicao.addWidget(self.mensagem)
        disposicao.addStretch(1)
        self.recarregar()

    def recarregar(self) -> None:
        linhas = [f"{nome}: {total}" for nome, total in resumo_bd(self.sessao).items()]
        copias = backups.listar()
        ultima = copias[-1].name if copias else "nenhuma"
        self.texto.setText(
            "\n".join(
                [
                    f"LSC Presenças {__version__}",
                    "",
                    *linhas,
                    "",
                    f"Base de dados: {config.descricao_bd()}",
                    f"Cópias de segurança: {len(copias)} (guardam-se as últimas "
                    f"{backups.MAX_BACKUPS}); a mais recente: {ultima}",
                ]
            )
        )

    def fazer_backup(self) -> bool:
        try:
            self.sessao.commit()
            destino = backups.fazer_backup(self.sessao.get_bind(), "manual")
        except Exception as erro:  # noqa: BLE001 - mostra-se a causa
            self.mensagem.setStyleSheet("color:#B00020;")
            self.mensagem.setText(f"A cópia de segurança falhou: {erro}")
            return False
        self.recarregar()
        self.mensagem.setStyleSheet("color:#1B6E1B;")
        self.mensagem.setText(f"Cópia guardada em {destino}")
        return True

    def importar(self) -> None:
        AssistenteImportacao(self.sessao, self).exec()
        self.recarregar()

    def ligacao_ao_servidor(self) -> None:
        self.sessao.commit()  # liberta o ficheiro local, que pode ser lido para enviar os dados
        dialogo = DialogoLigacao(parent=self)
        dialogo.exec()
        if dialogo.mudou:
            QMessageBox.information(self, "LSC Presenças", MENSAGEM_REABRIR)
            self.window().close()


class JanelaPrincipal(QMainWindow):
    def __init__(self, fabrica: sessionmaker[Session]):
        super().__init__()
        self.setWindowTitle(f"LSC Presenças {__version__}")
        self.resize(1280, 760)
        # Uma única sessão para toda a interface (app de um só utilizador).
        self.sessao = fabrica(expire_on_commit=True)

        self.terminou_sessao = False

        self.ecras: dict[str, QWidget] = {
            "Presenças": EcraPresencas(self.sessao),
            "Lançamentos": EcraLancamentos(self.sessao),
            "Fecho do mês": EcraFecho(self.sessao),
            "Relatórios": EcraRelatorios(self.sessao),
            "Trabalhadores": EcraTrabalhadores(self.sessao),
            "Tabelas": EcraTabelas(self.sessao),
        }
        if contas.e_admin():  # ecrãs só para administradores
            self.ecras["Contas"] = EcraContas(self.sessao)
            self.ecras["Auditoria"] = EcraAuditoria(self.sessao)
            self.ecras["Base de dados"] = EcraInicio(self.sessao)
        self.navegacao = QListWidget()
        self.pilha = QStackedWidget()
        for nome, ecra in self.ecras.items():
            self.navegacao.addItem(nome)
            self.pilha.addWidget(ecra)

        # Por baixo da navegação: quem tem a sessão iniciada.
        em_sessao = contas.atual()
        self.rotulo_sessao = QLabel(
            f"{em_sessao.nome}\n{contas.PERFIS.get(em_sessao.perfil, em_sessao.perfil)}"
            if em_sessao
            else "Sem login"
        )
        self.rotulo_sessao.setWordWrap(True)
        self.botao_senha = QPushButton("Mudar a palavra-passe…")
        self.botao_sair = QPushButton("Terminar sessão")
        self.botao_senha.setVisible(em_sessao is not None)
        self.botao_sair.setVisible(em_sessao is not None)
        self.botao_senha.clicked.connect(self.mudar_senha)
        self.botao_sair.clicked.connect(self.terminar_sessao)
        lateral = QWidget()
        lateral.setFixedWidth(170)
        coluna = QVBoxLayout(lateral)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(self.navegacao, 1)
        for w in (self.rotulo_sessao, self.botao_senha, self.botao_sair):
            coluna.addWidget(w)

        centro = QWidget()
        disposicao = QHBoxLayout(centro)
        disposicao.addWidget(lateral)
        disposicao.addWidget(self.pilha, 1)
        self.setCentralWidget(centro)

        self.navegacao.currentRowChanged.connect(self._mudar_ecra)
        self.navegacao.setCurrentRow(0)

    def _mudar_ecra(self, linha: int) -> None:
        ecra = self.pilha.widget(linha)
        ecra.recarregar()  # os dados podem ter mudado noutro ecrã
        self.pilha.setCurrentIndex(linha)

    def mostrar(self, nome: str) -> QWidget:
        self.navegacao.setCurrentRow(list(self.ecras).index(nome))
        return self.ecras[nome]

    def mudar_senha(self) -> None:
        em_sessao = contas.atual()
        conta = self.sessao.get(Utilizador, em_sessao.id) if em_sessao else None
        if conta is not None:
            DialogoSenha(self.sessao, conta, parent=self).exec()

    def terminar_sessao(self) -> None:
        """Fecha a janela e volta ao ecrã de login (ver `correr`)."""
        self.terminou_sessao = True
        self.close()

    def closeEvent(self, evento) -> None:
        self.sessao.close()
        super().closeEvent(evento)


def correr(fabrica: sessionmaker[Session]) -> int:
    """Pede o login e abre a janela; «Terminar sessão» volta ao login."""
    app = QApplication.instance() or QApplication(sys.argv)
    while True:
        contas.terminar_sessao()
        with fabrica() as sessao:
            conta = pedir_login(sessao)
            if conta is None:
                return 0
            contas.iniciar_sessao(conta)
        janela = JanelaPrincipal(fabrica)
        janela.show()
        codigo = app.exec()
        if not janela.terminou_sessao:
            contas.terminar_sessao()
            return codigo


def recuperar_administrador(fabrica: sessionmaker[Session]) -> int:
    """Comando de recuperação (`repor-admin`): define uma palavra-passe nova para um
    administrador, sem login. Só serve a quem já tem acesso ao PC e à base de dados."""
    app = QApplication.instance() or QApplication(sys.argv)
    with fabrica() as sessao:
        admins = [c for c in contas.listar(sessao) if c.perfil == PERFIL_ADMIN and c.ativo]
        if not admins:
            QMessageBox.information(
                None,
                "LSC Presenças",
                "Não há nenhum administrador ativo. Abra a app normalmente para criar a "
                "primeira conta."
                if not contas.ha_contas(sessao)
                else "Não há nenhum administrador ativo. Contacte o suporte.",
            )
            return 1
        nomes = [c.nome_utilizador for c in admins]
        escolhido, ok = QInputDialog.getItem(
            None, "Recuperar o administrador", "Conta de administrador:", nomes, 0, False
        )
        if not ok:
            return 0
        conta = admins[nomes.index(escolhido)]
        aceite = DialogoSenha(sessao, conta, recuperacao=True).exec()
    del app
    return 0 if aceite else 1
