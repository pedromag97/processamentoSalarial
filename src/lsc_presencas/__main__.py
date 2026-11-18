"""Entrada da app.

python -m lsc_presencas           abre a app
python -m lsc_presencas migrar    cria/atualiza a base de dados e os dados base
"""

import sys

from . import config, db
from .dados_base import carregar_dados_base


def preparar_bd():
    db.migrar()
    fabrica = db.criar_fabrica_sessoes(db.criar_engine())
    with fabrica() as sessao:
        carregar_dados_base(sessao)
        sessao.commit()
    return fabrica


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["migrar"]:
        preparar_bd()
        print(f"Base de dados atualizada: {config.caminho_bd()}")
        return 0

    try:
        from .ui.app import correr

        return correr(preparar_bd())
    except Exception:
        _mostrar_erro_de_arranque()
        return 1


def _mostrar_erro_de_arranque() -> None:
    """Sem consola (pythonw), um erro ao arrancar não se via: grava-se e mostra-se numa caixa."""
    import traceback

    detalhe = traceback.format_exc()
    registo = config.pasta_app() / "erro.log"
    registo.write_text(detalhe, encoding="utf-8")
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
