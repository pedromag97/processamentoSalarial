"""Importação única da folha «s-27» do Excel de ponto semanal.

Três passos, sem interface:
1. `ler_s27()` lê o ficheiro e devolve o que encontrou (não toca na base de dados);
2. `construir_plano()` junta ou separa os nomes duplicados conforme as decisões do utilizador;
3. `gravar()` cria clientes, viaturas, zonas, trabalhadores e marcações, tudo ou nada.

A data de cada coluna calcula-se pela posição (a linha com o dia do mês tem erros no ficheiro
real); as diferenças ficam no relatório.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import contas, presencas
from .modelos import PAIS_FRANCA, Cliente, Empresa, Trabalhador, Viatura, Zona
from .presencas import Alteracao
from .ui.formatos import sem_acentos

IGNORAR = ""  # destino de um valor antigo que não se quer importar

# Códigos antigos com destino conhecido. «s» fica de fora de propósito: tem de ser decidido.
MAPEAMENTO_BASE = {
    "x": "P",
    "ferias": "FE",
    "falta": "FI",
    "baixa": "B",
    "b": "B",
}

EMPRESAS_BASE = ["LOUSACABO CONSTRUÇÕES LDA", "+INNOVATION"]
# Rótulos dos mapas de férias -> texto a procurar no nome da empresa.
ROTULOS_EMPRESA = {"LOUSA": "lousa", "LUSOC": "innovation"}


@dataclass(frozen=True)
class Estrutura:
    folha: str = "s-27"
    blocos: tuple[tuple[int, int], ...] = ((7, 46), (55, 78))
    linhas_dia_do_mes: tuple[int, ...] = (5, 53)
    col_numero: int = 1  # A
    col_cliente: int = 3  # C
    col_viatura: int = 4  # D
    col_nome: int = 5  # E
    primeira_col_dia: int = 11  # K
    ultima_col_dia: int = 381  # NQ
    data_inicial: date = date(2026, 12, 28)

    def data_da_coluna(self, coluna: int) -> date:
        return self.data_inicial + timedelta(days=coluna - self.primeira_col_dia)


@dataclass
class LinhaLida:
    linha: int
    bloco: int
    numero_antigo: object
    nome: str
    cliente: str | None
    viatura: str | None
    zona: str | None
    valores: dict[date, str] = field(default_factory=dict)  # dia -> valor normalizado


@dataclass
class Leitura:
    caminho: Path
    linhas: list[LinhaLida] = field(default_factory=list)
    clientes: list[str] = field(default_factory=list)
    viaturas: list[str] = field(default_factory=list)
    zonas: list[str] = field(default_factory=list)
    valores: Counter = field(default_factory=Counter)  # valor normalizado -> ocorrências
    discrepancias: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    primeiro_dia: date | None = None
    ultimo_dia: date | None = None


@dataclass
class Pessoa:
    """Um trabalhador a importar (uma ou mais linhas do Excel, se forem a mesma pessoa)."""

    nome: str
    linhas: list[int]
    cliente: str | None
    viatura: str | None
    zona: str | None
    valores: dict[date, str]
    empresa: str | None = None
    notas: list[str] = field(default_factory=list)


@dataclass
class Relatorio:
    linhas: list[str] = field(default_factory=list)
    trabalhadores_criados: int = 0
    trabalhadores_existentes: int = 0
    marcacoes: int = 0

    def texto(self) -> str:
        return "\n".join(self.linhas)


def normalizar_valor(valor) -> str:
    """Valor de uma célula de dia, comparável: sem espaços, minúsculas e sem acentos."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return sem_acentos(str(valor).strip())


def chave_nome(nome: str) -> str:
    return " ".join(sem_acentos(nome).split())


def _texto(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


# --- 1. Leitura -------------------------------------------------------------------------------


def ler_s27(caminho: str | Path, estrutura: Estrutura | None = None) -> Leitura:
    e = estrutura or Estrutura()
    caminho = Path(caminho)
    livro = openpyxl.load_workbook(caminho, data_only=True)
    if e.folha not in livro.sheetnames:
        raise ValueError(f"O ficheiro não tem a folha «{e.folha}».")
    folha = livro[e.folha]
    ultima = min(e.ultima_col_dia, folha.max_column)
    colunas_dia = range(e.primeira_col_dia, ultima + 1)
    leitura = Leitura(
        caminho=caminho,
        primeiro_dia=e.data_da_coluna(e.primeira_col_dia),
        ultimo_dia=e.data_da_coluna(ultima),
    )

    for linha_dia in e.linhas_dia_do_mes:
        for coluna in colunas_dia:
            valor = folha.cell(linha_dia, coluna).value
            if isinstance(valor, datetime):
                valor = valor.day
            esperado = e.data_da_coluna(coluna)
            if valor is not None and valor != esperado.day:
                leitura.discrepancias.append(
                    f"{get_column_letter(coluna)}{linha_dia}: tem {valor!r}, "
                    f"mas a coluna é o dia {esperado:%d/%m/%Y}"
                )

    clientes, viaturas, zonas = [], [], []
    for n_bloco, (primeira, ultima_linha) in enumerate(e.blocos, start=1):
        zona_atual = None
        for linha in range(primeira, min(ultima_linha, folha.max_row) + 1):
            numero = folha.cell(linha, e.col_numero).value
            cliente = _texto(folha.cell(linha, e.col_cliente).value)
            viatura = _texto(folha.cell(linha, e.col_viatura).value)
            nome = _texto(folha.cell(linha, e.col_nome).value)
            dias = {
                e.data_da_coluna(c): folha.cell(linha, c).value
                for c in colunas_dia
                if _texto(folha.cell(linha, c).value) is not None
            }
            if viatura and viatura not in viaturas:
                viaturas.append(viatura)

            if nome:
                if cliente and cliente not in clientes:
                    clientes.append(cliente)
                valores = {dia: normalizar_valor(v) for dia, v in dias.items()}
                leitura.valores.update(valores.values())
                leitura.linhas.append(
                    LinhaLida(linha, n_bloco, numero, nome, cliente, viatura, zona_atual, valores)
                )
            elif dias and numero is None and not cliente and not viatura:
                # Título de zona: o nome da zona está repetido nas colunas dos dias.
                titulo = Counter(str(v).strip() for v in dias.values()).most_common(1)[0][0]
                zona_atual = titulo
                if titulo not in zonas:
                    zonas.append(titulo)
                leitura.notas.append(f"Linha {linha}: título de zona «{titulo}».")
            elif viatura:
                leitura.notas.append(f"Linha {linha}: sem nome; importei só a viatura «{viatura}».")
            elif numero is not None or cliente or dias:
                leitura.notas.append(f"Linha {linha}: sem nome nem viatura; ignorada.")

    leitura.clientes, leitura.viaturas, leitura.zonas = clientes, viaturas, zonas
    return leitura


def mapeamento_inicial(leitura: Leitura, codigos: dict[str, int]) -> dict[str, str | None]:
    """Destino proposto para cada valor encontrado. None = o utilizador tem de decidir."""
    proposta: dict[str, str | None] = {}
    for valor in leitura.valores:
        if valor in MAPEAMENTO_BASE:
            proposta[valor] = MAPEAMENTO_BASE[valor]
            continue
        try:  # já é um código novo válido (ex.: «pf» ou «p+2»)
            estado = presencas.interpretar_celula(valor, codigos)
        except ValueError:
            proposta[valor] = None
        else:
            nomes = {id_: nome for nome, id_ in codigos.items()}
            proposta[valor] = presencas.texto_celula(nomes[estado[0]], estado[1])
    return proposta


def grupos_duplicados(leitura: Leitura) -> dict[str, list[LinhaLida]]:
    """Nomes que aparecem em mais de uma linha (sem distinguir maiúsculas nem acentos)."""
    grupos: dict[str, list[LinhaLida]] = {}
    for linha in leitura.linhas:
        grupos.setdefault(chave_nome(linha.nome), []).append(linha)
    return {chave: linhas for chave, linhas in grupos.items() if len(linhas) > 1}


# --- 2. Plano ---------------------------------------------------------------------------------


def construir_plano(leitura: Leitura, mesma_pessoa: dict[str, bool]) -> list[Pessoa]:
    """Lista de trabalhadores a criar.

    `mesma_pessoa[chave]` diz, para cada grupo de nomes duplicados, se é a mesma pessoa (junta
    as linhas) ou pessoas diferentes (uma por linha). Falta de decisão é um erro.
    """
    duplicados = grupos_duplicados(leitura)
    em_falta = [chave for chave in duplicados if chave not in mesma_pessoa]
    if em_falta:
        raise ValueError(f"Falta decidir {len(em_falta)} nome(s) duplicado(s).")

    pessoas: list[Pessoa] = []
    juntas: dict[str, Pessoa] = {}
    for linha in leitura.linhas:
        chave = chave_nome(linha.nome)
        if chave in duplicados and mesma_pessoa[chave] and chave in juntas:
            pessoa = juntas[chave]
            pessoa.linhas.append(linha.linha)
            for campo in ("cliente", "viatura", "zona"):
                novo, atual = getattr(linha, campo), getattr(pessoa, campo)
                if novo and not atual:
                    setattr(pessoa, campo, novo)
                elif novo and atual and novo != atual:
                    pessoa.notas.append(
                        f"{campo} diferente na linha {linha.linha} («{novo}»); "
                        f"ficou «{atual}» (linha {pessoa.linhas[0]})."
                    )
            for dia, valor in linha.valores.items():
                if dia in pessoa.valores and pessoa.valores[dia] != valor:
                    pessoa.notas.append(
                        f"{dia:%d/%m/%Y}: «{pessoa.valores[dia]}» e «{valor}» nas duas linhas; "
                        f"ficou «{pessoa.valores[dia]}»."
                    )
                else:
                    pessoa.valores[dia] = valor
            continue
        pessoa = Pessoa(
            nome=linha.nome,
            linhas=[linha.linha],
            cliente=linha.cliente,
            viatura=linha.viatura,
            zona=linha.zona,
            valores=dict(linha.valores),
        )
        pessoas.append(pessoa)
        if chave in duplicados and mesma_pessoa[chave]:
            juntas[chave] = pessoa
    return pessoas


# --- Sugestão de empresa a partir dos mapas de férias ------------------------------------------


def folhas_dos_mapas_de_ferias(pasta: Path) -> dict[str, set[str]]:
    """Nomes das folhas (uma por trabalhador) dos mapas de férias, por rótulo de empresa."""
    encontrados: dict[str, set[str]] = {}
    if not pasta or not pasta.is_dir():
        return encontrados
    for ficheiro in pasta.glob("*Mapa de Ferias*.xls*"):
        if ficheiro.name.startswith("~$"):
            continue
        rotulo = next((r for r in ROTULOS_EMPRESA if r in ficheiro.name.upper()), None)
        if rotulo is None:
            continue
        try:
            livro = openpyxl.load_workbook(ficheiro, read_only=True)
        except Exception:  # noqa: BLE001 - é só uma sugestão; um ficheiro ilegível não impede nada
            continue
        encontrados.setdefault(rotulo, set()).update(
            sem_acentos(nome).replace(".", "").replace(" ", "") for nome in livro.sheetnames
        )
        livro.close()
    return encontrados


def nome_corresponde(nome: str, folha: str) -> bool:
    """A folha «BrunoR», «JMoreira» ou «M.Teix» corresponde ao nome completo?"""
    partes = sem_acentos(nome).split()
    if not partes or not folha:
        return False
    primeiro, resto = partes[0], partes[1:]
    if folha == primeiro:
        return True
    if any(folha == primeiro + apelido[0] for apelido in resto):
        return True
    return (
        len(folha) >= 4
        and folha[0] == primeiro[0]
        and any(apelido.startswith(folha[1:]) for apelido in resto)
    )


def sugerir_empresa(nome: str, folhas: dict[str, set[str]], empresas: list[str]) -> str | None:
    """Empresa sugerida para um nome, se corresponder a um só mapa de férias."""
    rotulos = [r for r, nomes in folhas.items() if any(nome_corresponde(nome, f) for f in nomes)]
    if len(rotulos) != 1:
        return None
    procurado = ROTULOS_EMPRESA[rotulos[0]]
    return next((e for e in empresas if procurado in sem_acentos(e)), None)


# --- 3. Gravação ------------------------------------------------------------------------------


def _obter_ou_criar(sessao: Session, classe, campo: str, valor: str, **extra):
    existente = sessao.scalars(select(classe).where(getattr(classe, campo) == valor)).first()
    if existente:
        return existente, False
    novo = classe(**{campo: valor}, **extra)
    sessao.add(novo)
    sessao.flush()
    return novo, True


def gravar(
    sessao: Session,
    leitura: Leitura,
    pessoas: list[Pessoa],
    mapeamento: dict[str, str | None],
) -> Relatorio:
    """Grava a importação (tudo ou nada) e devolve o relatório."""
    contas.exigir_admin("importar a folha de ponto")
    usados = {v for p in pessoas for v in p.valores.values()}
    por_decidir = sorted(v for v in usados if mapeamento.get(v) is None)
    if por_decidir:
        raise ValueError("Falta decidir o destino de: " + ", ".join(f"«{v}»" for v in por_decidir))

    r = Relatorio()
    escrever = r.linhas.append
    escrever(f"Importação da folha s-27 — {datetime.now():%d/%m/%Y %H:%M}")
    escrever(f"Ficheiro: {leitura.caminho}")
    escrever(f"Período da folha: {leitura.primeiro_dia:%d/%m/%Y} a {leitura.ultimo_dia:%d/%m/%Y}")
    try:
        codigos = presencas.codigos_ativos(sessao)
        estados = {
            valor: presencas.interpretar_celula(destino, codigos)
            for valor, destino in mapeamento.items()
            if destino not in (None, IGNORAR)
        }

        escrever("")
        escrever("TABELAS")
        for classe, campo, valores, extra, nome in (
            (Cliente, "codigo", leitura.clientes, {}, "Clientes"),
            (Viatura, "codigo", leitura.viaturas, {}, "Viaturas"),
            (Zona, "nome", leitura.zonas, {"pais": PAIS_FRANCA}, "Zonas"),
            (Empresa, "nome", sorted({p.empresa for p in pessoas if p.empresa}), {}, "Empresas"),
        ):
            criados = [v for v in valores if _obter_ou_criar(sessao, classe, campo, v, **extra)[1]]
            escrever(
                f"{nome}: {len(valores)} na folha, {len(criados)} criados. " + ", ".join(criados)
            )
        if leitura.zonas:
            escrever("As zonas novas ficaram com o país França; confirme na tabela de zonas.")

        ids = {
            "cliente": dict(sessao.execute(select(Cliente.codigo, Cliente.id)).all()),
            "viatura": dict(sessao.execute(select(Viatura.codigo, Viatura.id)).all()),
            "zona": dict(sessao.execute(select(Zona.nome, Zona.id)).all()),
            "empresa": dict(sessao.execute(select(Empresa.nome, Empresa.id)).all()),
        }
        existentes: dict[str, Trabalhador] = {}
        for t in sessao.scalars(select(Trabalhador)):
            existentes.setdefault(chave_nome(t.nome), t)
        numero = sessao.scalar(select(func.max(Trabalhador.numero))) or 0

        escrever("")
        escrever("TRABALHADORES")
        alteracoes: list[Alteracao] = []
        ignorados = Counter()
        for pessoa in pessoas:
            linhas = ", ".join(str(n) for n in pessoa.linhas)
            trabalhador = existentes.get(chave_nome(pessoa.nome))
            if trabalhador is not None and _primeira_com_o_nome(pessoa, pessoas):
                r.trabalhadores_existentes += 1
                escrever(f"nº {trabalhador.numero} {pessoa.nome} (linha {linhas}): já existia.")
            else:
                numero += 1
                trabalhador = Trabalhador(
                    numero=numero,
                    nome=pessoa.nome,
                    empresa_id=ids["empresa"].get(pessoa.empresa),
                    cliente_id=ids["cliente"].get(pessoa.cliente),
                    viatura_id=ids["viatura"].get(pessoa.viatura),
                    zona_id=ids["zona"].get(pessoa.zona),
                )
                sessao.add(trabalhador)
                sessao.flush()
                r.trabalhadores_criados += 1
                em_falta = [
                    nome
                    for nome, valor in (("empresa", pessoa.empresa), ("cliente", pessoa.cliente))
                    if not valor
                ]
                sufixo = f" — sem {' nem '.join(em_falta)}" if em_falta else ""
                escrever(f"nº {numero} {pessoa.nome} (linha {linhas}){sufixo}")
            for nota in pessoa.notas:
                escrever(f"    {nota}")
            for dia, valor in sorted(pessoa.valores.items()):
                if valor in estados:
                    alteracoes.append(Alteracao(trabalhador.id, dia, estados[valor]))
                else:
                    ignorados[valor] += 1

        gravadas = presencas.aplicar_alteracoes(sessao, alteracoes, utilizador="importação s-27")
        sessao.commit()
        r.marcacoes = len(gravadas)
    except Exception:
        sessao.rollback()
        raise

    escrever("")
    escrever("MARCAÇÕES")
    escrever(f"{r.marcacoes} marcações gravadas.")
    for valor, n in sorted(leitura.valores.items()):
        destino = mapeamento.get(valor)
        descricao = "ignorado" if destino == IGNORAR else f"→ {destino}"
        escrever(f"«{valor}» ({n} ocorrências): {descricao}")
    escrever("")
    escrever(f"DISCREPÂNCIAS NO DIA DO MÊS ({len(leitura.discrepancias)})")
    escrever("As datas foram calculadas pela posição da coluna, por isso não afetam a importação.")
    r.linhas.extend(leitura.discrepancias)
    escrever("")
    escrever("OUTRAS NOTAS")
    r.linhas.extend(leitura.notas or ["(nenhuma)"])
    escrever("")
    escrever(
        f"Resumo: {r.trabalhadores_criados} trabalhadores criados, "
        f"{r.trabalhadores_existentes} já existiam, {r.marcacoes} marcações."
    )
    return r


def _primeira_com_o_nome(pessoa: Pessoa, pessoas: list[Pessoa]) -> bool:
    """Um trabalhador que já está na base de dados só é reaproveitado pela primeira pessoa
    com esse nome; as seguintes (decididas como «pessoas diferentes») são criadas."""
    mesmas = [p for p in pessoas if chave_nome(p.nome) == chave_nome(pessoa.nome)]
    return mesmas[0] is pessoa
