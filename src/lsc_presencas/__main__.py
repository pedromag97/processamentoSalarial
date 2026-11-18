"""Entrada da app.

python -m lsc_presencas           abre a app
python -m lsc_presencas migrar    cria/atualiza a base de dados e os dados base
python -m lsc_presencas repor-admin   define uma palavra-passe nova para um administrador
"""

import sys

from sqlalchemy.exc import IntegrityError

from . import config, db
from .dados_base import carregar_dados_base


def copia_ao_abrir() -> None:
    """Cópia de segurança antes de mexer na base de dados (se já existir).

    Uma falha aqui não impede a app de abrir: fica registada em `erro.log`.
    """
    from . import backups

    if config.usa_servidor():
        return  # as cópias do servidor fazem-se no servidor (e antes de fechar um mês)
    caminho = config.caminho_bd()
    if not caminho.is_file() or caminho.stat().st_size == 0:
        return
    engine = db.criar_engine()
    try:
        backups.fazer_backup(engine, "abertura")
    except Exception:  # noqa: BLE001
        import traceback

        (config.pasta_app() / "erro.log").write_text(
            "A cópia de segurança ao abrir falhou.\n" + traceback.format_exc(), encoding="utf-8"
        )
    finally:
        engine.dispose()


def preparar_bd(com_copia: bool = False):
    if com_copia:
        copia_ao_abrir()
    db.migrar()
    fabrica = db.criar_fabrica_sessoes(db.criar_engine())
    with fabrica() as sessao:
        try:
            carregar_dados_base(sessao)
            sessao.commit()
        except IntegrityError:
            # Outro PC abriu o programa ao mesmo tempo e já os carregou.
            sessao.rollback()
    return fabrica


def abrir_base_de_dados():
    """Prepara a base de dados para a app. Se o servidor não responder, mostra o diálogo
    da ligação para corrigir, tentar outra vez ou voltar ao ficheiro deste PC.

    Devolve None se a pessoa desistiu.
    """
    from . import servidor
    from .ui.app import aplicacao
    from .ui.ecra_ligacao import DialogoLigacao

    while True:
        try:
            return preparar_bd(com_copia=True)
        except Exception as erro:  # noqa: BLE001
            if not config.usa_servidor():
                raise
            _registar_erro()  # o detalhe técnico fica em erro.log; o ecrã mostra o resumo
            app = aplicacao()
            dialogo = DialogoLigacao(
                erro=servidor.explicar(erro)
                + " Corrija a ligação e guarde, ou feche esta janela e tente mais tarde."
            )
            dialogo.exec()
            del app
            if not dialogo.mudou:
                return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["migrar"]:
        try:
            preparar_bd()
        except Exception:
            print(_registar_erro(), file=sys.stderr)
            return 1
        print(f"Base de dados atualizada: {config.descricao_bd()}")
        return 0

    try:
        from .ui.app import correr, recuperar_administrador

        fabrica = abrir_base_de_dados()
        if fabrica is None:
            return 0
        if argv[:1] == ["repor-admin"]:
            return recuperar_administrador(fabrica)
        return correr(fabrica)
    except Exception:
        _mostrar_erro_de_arranque()
        return 1


def _registar_erro() -> str:
    """Grava o erro em curso em `erro.log`, na pasta de dados, e devolve o texto."""
    import traceback

    detalhe = traceback.format_exc()
    try:
        (config.pasta_app() / "erro.log").write_text(detalhe, encoding="utf-8")
    except OSError:
        pass
    return detalhe


def _mostrar_erro_de_arranque() -> None:
    """Sem consola (pythonw), um erro ao arrancar não se via: grava-se e mostra-se numa caixa."""
    detalhe = _registar_erro()
    registo = config.pasta_app() / "erro.log"
    print(detalhe, file=sys.stderr)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "LSC Presenças",
            f"A app não conseguiu arrancar.\n\nO detalhe ficou em:\n{registo}\n\n"
            f"{detalhe.splitlines()[-1]}",
        )
        del app
    except Exception:  # noqa: BLE001 - se nem a caixa abre, fica o ficheiro de registo
        pass


if __name__ == "__main__":
    sys.exit(main())
