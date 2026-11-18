"""Conversão entre texto escrito pelo utilizador e valores (números, datas)."""

import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

FORMATOS_DATA = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y")


def texto_decimal(valor: Decimal | None) -> str:
    return "" if valor is None else f"{Decimal(valor):f}".replace(".", ",")


def ler_decimal(texto: str) -> Decimal | None:
    """Aceita vírgula ou ponto decimal. Texto vazio = None (valor por preencher)."""
    limpo = texto.strip().replace("€", "").replace(" ", "").replace(",", ".")
    if not limpo:
        return None
    try:
        valor = Decimal(limpo)
    except InvalidOperation:
        raise ValueError(f"«{texto.strip()}» não é um número válido.") from None
    if not valor.is_finite():
        raise ValueError(f"«{texto.strip()}» não é um número válido.")
    return valor


def ler_inteiro(texto: str) -> int | None:
    limpo = texto.strip()
    if not limpo:
        return None
    try:
        return int(limpo)
    except ValueError:
        raise ValueError(f"«{limpo}» não é um número inteiro.") from None


def texto_data(valor: date | None) -> str:
    return "" if valor is None else valor.strftime("%d/%m/%Y")


def ler_data(texto: str) -> date | None:
    limpo = texto.strip()
    if not limpo:
        return None
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(limpo, formato).date()
        except ValueError:
            continue
    raise ValueError(f"«{limpo}» não é uma data válida (use dd/mm/aaaa).")


def sem_acentos(texto: str) -> str:
    """Minúsculas e sem acentos, para pesquisar e comparar nomes."""
    decomposto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").casefold()
