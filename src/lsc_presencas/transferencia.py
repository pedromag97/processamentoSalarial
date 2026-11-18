"""Copia todos os dados de uma base de dados para outra (SQLite ou PostgreSQL).

Serve para duas coisas:
- passar os dados do ficheiro local para o servidor, quando a app passa a usar um servidor;
- fazer cópias de segurança de um servidor para um ficheiro SQLite local.

A base de dados de destino tem de ter já as tabelas (migrações feitas). Os identificadores são
preservados, por isso todas as referências entre tabelas ficam iguais.
"""

from dataclasses import dataclass, field

from sqlalchemy import Engine, delete, func, insert, select, text

from .modelos import Base

LOTE = 500
# Tabelas que a app preenche sozinha (dados base): não contam como "dados do utilizador".
TABELAS_BASE = {"codigo_presenca", "feriado"}
# Estado do momento (quem está a mexer em quem): não se copia nem conta como dados.
TABELAS_TRANSITORIAS = {"bloqueio_trabalhador"}


class DestinoComDados(ValueError):
    """A base de dados de destino já tem dados e não foi pedido para os substituir."""


@dataclass
class Resultado:
    linhas: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.linhas.values())


def contar(engine: Engine) -> dict[str, int]:
    """Número de linhas de cada tabela do modelo."""
    with engine.connect() as ligacao:
        return {
            tabela.name: ligacao.scalar(select(func.count()).select_from(tabela)) or 0
            for tabela in Base.metadata.sorted_tables
            if tabela.name not in TABELAS_TRANSITORIAS
        }


def tem_dados(engine: Engine) -> bool:
    """True se houver alguma coisa além dos dados base (códigos e feriados)."""
    return any(n for nome, n in contar(engine).items() if nome not in TABELAS_BASE)


def copiar(origem: Engine, destino: Engine, *, substituir: bool = False) -> Resultado:
    """Copia todas as tabelas de `origem` para `destino`, numa só transação (tudo ou nada).

    Se o destino já tiver dados do utilizador, levanta `DestinoComDados`, a não ser que
    `substituir` seja True. Os dados base do destino são sempre substituídos pelos da origem.
    """
    if not substituir and tem_dados(destino):
        raise DestinoComDados(
            "A base de dados de destino já tem dados. Não foi copiado nada, para não os perder."
        )
    tabelas = Base.metadata.sorted_tables  # por ordem de dependência
    resultado = Resultado()
    with origem.connect() as de, destino.begin() as para:
        for tabela in reversed(tabelas):
            para.execute(delete(tabela))
        for tabela in tabelas:
            if tabela.name in TABELAS_TRANSITORIAS:
                continue
            n = 0
            lote: list[dict] = []
            for linha in de.execute(select(tabela)).mappings():
                lote.append(dict(linha))
                if len(lote) >= LOTE:
                    para.execute(insert(tabela), lote)
                    n += len(lote)
                    lote = []
            if lote:
                para.execute(insert(tabela), lote)
                n += len(lote)
            resultado.linhas[tabela.name] = n
        if destino.dialect.name == "postgresql":
            _acertar_sequencias(para, tabelas)
    return resultado


def _acertar_sequencias(ligacao, tabelas) -> None:
    """No PostgreSQL, o próximo `id` automático tem de ficar acima dos que foram copiados."""
    for tabela in tabelas:
        if "id" not in tabela.c:
            continue
        ligacao.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                f'COALESCE((SELECT MAX(id) FROM "{tabela.name}"), 1), '
                f'(SELECT MAX(id) FROM "{tabela.name}") IS NOT NULL)'
            )
        )
