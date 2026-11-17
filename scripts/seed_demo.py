"""Carrega os dados de demonstração na base de dados configurada (LSC_APP_DIR).

Por segurança só corre numa base de dados sem trabalhadores: nunca escreve por cima de dados.
"""

import sys

from lsc_presencas import config, db
from lsc_presencas.demo import ja_tem_dados, semear


def main() -> int:
    db.migrar()
    fabrica = db.criar_fabrica_sessoes(db.criar_engine())
    with fabrica() as sessao:
        if ja_tem_dados(sessao):
            print(f"A base de dados {config.caminho_bd()} já tem trabalhadores; não alterei nada.")
            print("Para recomeçar, apaga esse ficheiro e corre este script outra vez.")
            return 0
        total = semear(sessao)
        sessao.commit()
    print(f"Dados de demonstração carregados: {total} trabalhadores em {config.caminho_bd()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
