"""Exportação do mês de uma empresa: Excel-resumo, um PDF por trabalhador e um PDF conjunto.

Os ficheiros ficam em `saidas/AAAA-MM_<EMPRESA>/`, na pasta de dados da app (fora do Git).
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .exportar_excel import gerar_excel
from .exportar_pdf import gerar_pdf
from .mapa import MapaMes

_PROIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def nome_limpo(texto: str) -> str:
    """Texto que pode ser usado no nome de um ficheiro do Windows."""
    return re.sub(r"\s+", " ", _PROIBIDOS.sub("", texto)).strip(" .") or "sem nome"


@dataclass
class Exportacao:
    pasta: Path
    excel: Path
    conjunto: Path
    pdfs: list[Path] = field(default_factory=list)


def prefixo(mapa: MapaMes) -> str:
    return f"{mapa.periodo}_{nome_limpo(mapa.empresa)}"


def exportar(mapa: MapaMes, base: Path | None = None) -> Exportacao:
    """Gera todos os ficheiros do mês. Os que já existirem são substituídos."""
    if not mapa.trabalhadores:
        raise ValueError("Não há trabalhadores para exportar neste mês.")
    inicio = prefixo(mapa)
    if not mapa.fechado:
        inicio_pasta = f"{inicio} (provisório)"
    else:
        inicio_pasta = inicio
    pasta = (base or config.pasta_saidas()) / inicio_pasta
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        resultado = Exportacao(
            pasta=pasta,
            excel=gerar_excel(mapa, pasta / f"{inicio}_resumo.xlsx"),
            conjunto=gerar_pdf(mapa, mapa.trabalhadores, pasta / f"{inicio}_todos.pdf"),
        )
        for t in mapa.trabalhadores:
            destino = pasta / f"{inicio}_{t.numero}_{nome_limpo(t.nome)}.pdf"
            resultado.pdfs.append(gerar_pdf(mapa, [t], destino))
    except PermissionError as erro:
        raise ValueError(
            f"Não foi possível escrever «{Path(erro.filename or '').name}»: o ficheiro está "
            "aberto noutro programa. Feche-o e exporte outra vez."
        ) from None
    return resultado
