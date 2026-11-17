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

    from .ui.app import correr

    return correr(preparar_bd())


if __name__ == "__main__":
    sys.exit(main())
