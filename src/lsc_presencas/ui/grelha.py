"""Modelos da grelha de presenças: linhas = trabalhadores agrupados, colunas = dias.

Colunas: 4 fixas à esquerda (nº, nome, cliente, viatura), uma por dia do período, e os totais
à direita. As linhas de grupo (empresa e cliente) podem ser recolhidas.

Para a grelha abrir depressa, não se usam objetos do modelo de dados: lêem-se só as colunas
necessárias, com uma consulta para os trabalhadores e outra para as marcações do período.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import bloqueios, presencas
from ..modelos import Cliente, CodigoPresenca, Empresa, Feriado, Trabalhador, Viatura
from ..presencas import Alteracao
from .formatos import sem_acentos, texto_decimal
from .tabela import mensagem_de_erro

DIAS_SEMANA = ["2ª", "3ª", "4ª", "5ª", "6ª", "sáb", "dom"]
MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]  # fmt: skip

COLUNAS_ESQUERDA = ["Nº", "Nome", "Cliente", "Viatura"]
CODIGOS_TOTAIS = ["P", "PF", "DF", "FE", "FI", "B"]
COLUNAS_TOTAIS = [*CODIGOS_TOTAIS, "H. extra"]
DICAS_ESQUERDA = [
    "Número interno do trabalhador",
    "Nome do trabalhador. Arraste a divisória do cabeçalho para alargar a coluna.",
    "Cliente atual do trabalhador (ficha)",
    "Viatura atual do trabalhador (ficha)",
]
DIAS_SEMANA_LONGOS = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]
N_ESQ = len(COLUNAS_ESQUERDA)
N_DIR = len(COLUNAS_TOTAIS)

CADEADO = "\U0001f512"  # cadeado fechado
COR_FIM_DE_SEMANA = QColor("#E9E9E9")
COR_FERIADO = QColor("#D6D6E8")
COR_EMPRESA = QColor("#BFC8D6")
COR_CLIENTE = QColor("#DCE2EA")
COR_FECHADO = QColor("#F4F4F4")

LIMITE_DESFAZER = 200

Papel = Qt.ItemDataRole
PAPEL_HORAS = Papel.UserRole + 1

EMPRESA = "empresa"
CLIENTE = "cliente"
TRABALHADOR = "trabalhador"


@dataclass
class Filtros:
    empresa_id: int | None = None
    cliente_id: int | None = None
    viatura_id: int | None = None
    zona_id: int | None = None
    mostrar_inativos: bool = False
    texto: str = ""


@dataclass(frozen=True)
class LinhaTrab:
    id: int
    numero: int
    nome: str
    empresa_id: int | None
    empresa: str | None
    cliente_id: int | None
    cliente: str | None
    viatura: str | None


@dataclass(frozen=True)
class Linha:
    tipo: str
    texto: str = ""
    chave: tuple = ()
    trab: LinhaTrab | None = None


@dataclass(frozen=True)
class InfoCodigo:
    codigo: str
    cor: QColor
    conta_trabalhado: bool
    descricao: str = ""
    efeitos: str = ""

    @property
    def explicacao(self) -> str:
        """«PF — Presente em França» e, por baixo, o que o código faz no cálculo."""
        return f"{self.codigo} — {self.descricao}" + (f"\n{self.efeitos}" if self.efeitos else "")


def efeitos_do_codigo(trabalhado, subsidio, ajuda, desconta, prevencao) -> str:
    """O que um código de presença faz no cálculo, em palavras."""
    partes = ["Conta como dia trabalhado" if trabalhado else "Não conta como dia trabalhado"]
    if subsidio:
        partes.append("dá subsídio de alimentação")
    if ajuda == "sim":
        partes.append("dá ajuda de custo França")
    elif ajuda == "zona":
        partes.append("dá ajuda de custo França se a zona for em França")
    if desconta:
        partes.append("desconta no salário base")
    if prevencao:
        partes.append("soma o valor da prevenção")
    return "; ".join(partes) + "."


class ModeloGrelha(QAbstractTableModel):
    erro = Signal(str)
    alterado = Signal()

    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.filtros = Filtros()
        self.dias: list[date] = []
        self.trabalhadores: list[LinhaTrab] = []
        self.linhas: list[Linha] = []
        self.recolhidos: set[tuple] = set()
        self.marcacoes: dict[tuple[int, date], presencas.Celula] = {}
        self.codigos: dict[int, InfoCodigo] = {}
        self.por_codigo: dict[str, InfoCodigo] = {}
        self.codigos_ativos: dict[str, int] = {}
        self.feriados: dict[date, str] = {}
        self.fechados: set[tuple[int, int, int]] = set()
        self.cadeados: dict[int, bloqueios.Cadeado] = {}  # funcionários em uso por outros
        self._totais: dict[int, Counter] = {}
        self._horas: dict[int, Decimal] = {}
        self._desfazer: list[list[Alteracao]] = []
        self._negrito = QFont()
        self._negrito.setBold(True)

    # --- Carregamento ---

    def configurar(self, inicio: date, fim: date, filtros: Filtros | None = None) -> None:
        self.dias = [inicio + timedelta(days=n) for n in range((fim - inicio).days + 1)]
        if filtros is not None:
            self.filtros = filtros
        self.recarregar()

    def recarregar(self) -> None:
        self.beginResetModel()
        self._carregar_trabalhadores()
        self._carregar_apoio()
        self._carregar_marcacoes()
        self._montar_linhas()
        self.endResetModel()
        self.alterado.emit()

    def _carregar_trabalhadores(self) -> None:
        f = self.filtros
        consulta = (
            select(
                Trabalhador.id,
                Trabalhador.numero,
                Trabalhador.nome,
                Trabalhador.empresa_id,
                Empresa.nome,
                Trabalhador.cliente_id,
                Cliente.codigo,
                Viatura.codigo,
            )
            .outerjoin(Empresa, Trabalhador.empresa_id == Empresa.id)
            .outerjoin(Cliente, Trabalhador.cliente_id == Cliente.id)
            .outerjoin(Viatura, Trabalhador.viatura_id == Viatura.id)
        )
        if not f.mostrar_inativos:
            consulta = consulta.where(Trabalhador.ativo)
        for coluna, valor in (
            (Trabalhador.empresa_id, f.empresa_id),
            (Trabalhador.cliente_id, f.cliente_id),
            (Trabalhador.viatura_id, f.viatura_id),
            (Trabalhador.zona_id, f.zona_id),
        ):
            if valor is not None:
                consulta = consulta.where(coluna == valor)
        texto = sem_acentos(f.texto.strip())
        trabalhadores = [LinhaTrab(*linha) for linha in self.sessao.execute(consulta)]
        if texto:
            trabalhadores = [t for t in trabalhadores if texto in sem_acentos(t.nome)]
        trabalhadores.sort(
            key=lambda t: (
                t.empresa is None,
                sem_acentos(t.empresa or ""),
                t.cliente is None,
                sem_acentos(t.cliente or ""),
                t.numero,
            )
        )
        self.trabalhadores = trabalhadores

    def _carregar_apoio(self) -> None:
        self.codigos = {
            id_: InfoCodigo(
                codigo,
                QColor(cor),
                trabalhado,
                descricao,
                efeitos_do_codigo(trabalhado, subsidio, ajuda, desconta, prevencao),
            )
            for (
                id_,
                codigo,
                cor,
                trabalhado,
                descricao,
                subsidio,
                ajuda,
                desconta,
                prevencao,
            ) in self.sessao.execute(
                select(
                    CodigoPresenca.id,
                    CodigoPresenca.codigo,
                    CodigoPresenca.cor,
                    CodigoPresenca.conta_trabalhado,
                    CodigoPresenca.descricao,
                    CodigoPresenca.subsidio_alimentacao,
                    CodigoPresenca.ajuda_custo_franca,
                    CodigoPresenca.desconta_salario,
                    CodigoPresenca.soma_prevencao,
                ).order_by(CodigoPresenca.ordem, CodigoPresenca.codigo)
            )
        }
        self.por_codigo = {info.codigo: info for info in self.codigos.values()}
        self.codigos_ativos = presencas.codigos_ativos(self.sessao)
        self.fechados = presencas.meses_fechados(self.sessao)
        self.cadeados = bloqueios.de_outros(self.sessao)
        self.feriados = {}
        if self.dias:
            for dia, nome in self.sessao.execute(
                select(Feriado.data, Feriado.nome).where(
                    Feriado.data.between(self.dias[0], self.dias[-1])
                )
            ):
                self.feriados[dia] = nome

    def _carregar_marcacoes(self) -> None:
        self.marcacoes = (
            presencas.carregar_marcacoes(self.sessao, self.dias[0], self.dias[-1])
            if self.dias
            else {}
        )
        self._totais = defaultdict(Counter)
        self._horas = defaultdict(Decimal)
        for (tid, _dia), celula in self.marcacoes.items():
            self._totais[tid][self.codigos[celula.codigo_id].codigo] += 1
            self._horas[tid] += celula.horas_extra

    def _montar_linhas(self) -> None:
        linhas: list[Linha] = []
        for (emp_id, emp), da_empresa in groupby(
            self.trabalhadores, key=lambda t: (t.empresa_id, t.empresa)
        ):
            da_empresa = list(da_empresa)
            chave_e = (EMPRESA, emp_id)
            seta = "▸" if chave_e in self.recolhidos else "▾"
            linhas.append(
                Linha(EMPRESA, f"{seta} {emp or '(sem empresa)'} ({len(da_empresa)})", chave_e)
            )
            if chave_e in self.recolhidos:
                continue
            for (cli_id, cli), do_cliente in groupby(
                da_empresa, key=lambda t: (t.cliente_id, t.cliente)
            ):
                do_cliente = list(do_cliente)
                chave_c = (CLIENTE, emp_id, cli_id)
                seta = "▸" if chave_c in self.recolhidos else "▾"
                linhas.append(
                    Linha(
                        CLIENTE, f"   {seta} {cli or '(sem cliente)'} ({len(do_cliente)})", chave_c
                    )
                )
                if chave_c not in self.recolhidos:
                    linhas.extend(Linha(TRABALHADOR, trab=t) for t in do_cliente)
        self.linhas = linhas

    def alternar_grupo(self, linha: int) -> None:
        """Recolhe ou expande o grupo da linha indicada (se for uma linha de grupo)."""
        chave = self.linhas[linha].chave
        if not chave:
            return
        self.recolhidos ^= {chave}
        self.beginResetModel()
        self._montar_linhas()
        self.endResetModel()

    # --- Colunas e células ---

    def dia_da_coluna(self, coluna: int) -> date | None:
        n = coluna - N_ESQ
        return self.dias[n] if 0 <= n < len(self.dias) else None

    def coluna_do_dia(self, dia: date) -> int:
        return N_ESQ + self.dias.index(dia)

    def celula(self, indice: QModelIndex) -> tuple[LinhaTrab, date] | None:
        """(trabalhador, dia) de uma célula de marcação, ou None se não for uma."""
        if not indice.isValid():
            return None
        linha = self.linhas[indice.row()]
        dia = self.dia_da_coluna(indice.column())
        if linha.tipo != TRABALHADOR or dia is None:
            return None
        return linha.trab, dia

    def codigos_para_escolher(self) -> list[InfoCodigo]:
        """Os códigos ativos, pela ordem da tabela (para a lista pendente das células)."""
        return [c for c in self.codigos.values() if c.codigo.upper() in self.codigos_ativos]

    def motivo_so_leitura(self, trab: LinhaTrab, dia: date) -> str | None:
        """Porque é que a célula não pode ser alterada (None se pode)."""
        if self.fechado(trab, dia):
            return "Mês fechado: só de leitura"
        if trab.id in self.cadeados:
            return f"{CADEADO} {self.cadeados[trab.id].descricao}"
        return None

    def fechado(self, trab: LinhaTrab, dia: date) -> bool:
        return (trab.empresa_id, dia.year, dia.month) in self.fechados

    def texto(self, trab: LinhaTrab, dia: date) -> str:
        celula = self.marcacoes.get((trab.id, dia))
        if celula is None:
            return ""
        return presencas.texto_celula(self.codigos[celula.codigo_id].codigo, celula.horas_extra)

    # --- Interface do Qt ---

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.linhas)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else N_ESQ + len(self.dias) + N_DIR

    def headerData(self, seccao, orientacao, papel=Papel.DisplayRole):
        if orientacao != Qt.Orientation.Horizontal:
            return None
        dia = self.dia_da_coluna(seccao)
        if papel == Papel.DisplayRole:
            if seccao < N_ESQ:
                return COLUNAS_ESQUERDA[seccao]
            if dia is None:
                return COLUNAS_TOTAIS[seccao - N_ESQ - len(self.dias)]
            numero = f"{dia.day:02d}/{dia.month:02d}" if len(self.dias) <= 7 else str(dia.day)
            return f"{DIAS_SEMANA[dia.weekday()]}\n{numero}"
        if papel == Papel.ToolTipRole:
            if dia is not None:
                texto = f"{DIAS_SEMANA_LONGOS[dia.weekday()]}, {dia:%d/%m/%Y}"
                return f"{texto}\nFeriado: {self.feriados[dia]}" if dia in self.feriados else texto
            if seccao < N_ESQ:
                return DICAS_ESQUERDA[seccao]
            n = seccao - N_ESQ - len(self.dias)
            if n < len(CODIGOS_TOTAIS):
                info = self.por_codigo.get(CODIGOS_TOTAIS[n])
                return "Número de dias no período com o código " + (
                    info.explicacao if info else CODIGOS_TOTAIS[n]
                )
            return "Total de horas extra no período (o +2 de «PF+2»)."
        if papel == Papel.BackgroundRole and dia is not None:
            return self._cor_do_dia(dia)
        return None

    def _cor_do_dia(self, dia: date) -> QColor | None:
        if dia in self.feriados:
            return COR_FERIADO
        if dia.weekday() >= 5:
            return COR_FIM_DE_SEMANA
        return None

    def flags(self, indice):
        celula = self.celula(indice)
        if celula is None:
            return Qt.ItemFlag.ItemIsEnabled
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        so_leitura = self.fechado(*celula) or celula[0].id in self.cadeados
        return base if so_leitura else base | Qt.ItemFlag.ItemIsEditable

    def data(self, indice, papel=Papel.DisplayRole):
        if not indice.isValid():
            return None
        linha = self.linhas[indice.row()]
        coluna = indice.column()
        if linha.tipo != TRABALHADOR:
            if papel == Papel.DisplayRole and coluna == 1:
                return linha.texto
            if papel == Papel.ToolTipRole:
                return f"{linha.texto.strip()}\nClique para recolher ou expandir este grupo."
            if papel == Papel.BackgroundRole:
                return COR_EMPRESA if linha.tipo == EMPRESA else COR_CLIENTE
            if papel == Papel.FontRole:
                return self._negrito
            return None

        trab = linha.trab
        dia = self.dia_da_coluna(coluna)
        if dia is None:
            return self._dado_fixo(trab, coluna, papel)

        celula = self.marcacoes.get((trab.id, dia))
        if papel == Papel.DisplayRole:
            return self.codigos[celula.codigo_id].codigo if celula else ""
        if papel == Papel.EditRole:
            return self.texto(trab, dia)
        if papel == PAPEL_HORAS:
            return (
                texto_decimal(celula.horas_extra.normalize())
                if celula and celula.horas_extra
                else ""
            )
        if papel == Papel.BackgroundRole:
            if celula:
                return self.codigos[celula.codigo_id].cor
            so_leitura = self.fechado(trab, dia) or trab.id in self.cadeados
            return self._cor_do_dia(dia) or (COR_FECHADO if so_leitura else None)
        if papel == Papel.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if papel == Papel.ToolTipRole:
            partes = [f"{trab.nome} — {DIAS_SEMANA[dia.weekday()]} {dia:%d/%m/%Y}"]
            if celula:
                partes.append(self.codigos[celula.codigo_id].explicacao)
                if celula.horas_extra:
                    horas = texto_decimal(celula.horas_extra.normalize())
                    partes.append(f"Horas extra neste dia: {horas}")
            else:
                partes.append(
                    "Sem marcação. Escreva um código (ex.: P, PF, PF+2) ou faça duplo clique "
                    "para escolher da lista."
                )
            if dia in self.feriados:
                partes.append(f"Feriado: {self.feriados[dia]}")
            if self.fechado(trab, dia):
                partes.append("Mês fechado (só de leitura)")
            if trab.id in self.cadeados:
                partes.append(f"{CADEADO} {self.cadeados[trab.id].descricao} (só de leitura)")
            return "\n".join(partes)
        return None

    def _dado_fixo(self, trab: LinhaTrab, coluna: int, papel):
        if coluna < N_ESQ:
            if papel == Papel.DisplayRole:
                nome = f"{CADEADO} {trab.nome}" if trab.id in self.cadeados else trab.nome
                return (str(trab.numero), nome, trab.cliente or "", trab.viatura or "")[coluna]
            if papel == Papel.TextAlignmentRole and coluna == 0:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if papel == Papel.ToolTipRole:
                dica = (
                    f"N.º {trab.numero} — {trab.nome}\nCliente: {trab.cliente or '—'} · "
                    f"Viatura: {trab.viatura or '—'}"
                )
                if trab.id in self.cadeados:
                    dica += f"\n{CADEADO} {self.cadeados[trab.id].descricao}"
                return dica
            return None
        n = coluna - N_ESQ - len(self.dias)
        if papel == Papel.ToolTipRole:
            if n < len(CODIGOS_TOTAIS):
                info = self.por_codigo.get(CODIGOS_TOTAIS[n])
                nome = info.descricao if info else CODIGOS_TOTAIS[n]
                return f"{trab.nome}: {self._totais[trab.id][CODIGOS_TOTAIS[n]]} dia(s) — {nome}"
            return f"{trab.nome}: horas extra no período"
        if papel == Papel.DisplayRole:
            if n < len(CODIGOS_TOTAIS):
                return str(self._totais[trab.id][CODIGOS_TOTAIS[n]] or "")
            horas = self._horas[trab.id]
            return texto_decimal(horas.normalize()) if horas else ""
        if papel == Papel.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def setData(self, indice, valor, papel=Papel.EditRole) -> bool:
        if papel != Papel.EditRole or self.celula(indice) is None:
            return False
        return self.aplicar_texto([indice], str(valor or ""))

    # --- Alterações ---

    def _celulas(self, indices) -> list[tuple[LinhaTrab, date]]:
        return [c for c in (self.celula(i) for i in indices) if c is not None]

    def aplicar_estados(self, alteracoes: list[Alteracao], *, desfazivel: bool = True) -> bool:
        """Grava as alterações, atualiza a grelha e guarda o estado anterior para desfazer."""
        # O que esta grelha estava a mostrar nas células que vai alterar: se entretanto
        # outra pessoa as mudou, não se grava por cima.
        esperados = {}
        if self.dias:
            for a in alteracoes:
                if self.dias[0] <= a.data <= self.dias[-1]:
                    celula = self.marcacoes.get((a.trabalhador_id, a.data))
                    esperados[(a.trabalhador_id, a.data)] = (
                        (celula.codigo_id, celula.horas_extra) if celula else None
                    )
        try:
            anteriores = presencas.aplicar_alteracoes(self.sessao, alteracoes, esperados=esperados)
        except presencas.Conflito as erro:
            self.atualizar()
            self.erro.emit(str(erro))
            return False
        except (presencas.MesFechado, ValueError) as erro:
            self.atualizar()  # ex.: o mês foi fechado por outra pessoa
            self.erro.emit(str(erro))
            return False
        except SQLAlchemyError as erro:
            self.sessao.rollback()
            self.erro.emit(mensagem_de_erro(erro))
            return False
        if anteriores and desfazivel:
            self._desfazer.append(anteriores)
            del self._desfazer[:-LIMITE_DESFAZER]
        self._mostrar_marcacoes()
        return True

    def _mostrar_marcacoes(self) -> None:
        self._carregar_marcacoes()
        if self.linhas:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.linhas) - 1, self.columnCount() - 1)
            )
        self.alterado.emit()

    def atualizar(self) -> bool:
        """Vai buscar o que as outras pessoas gravaram (marcações e meses fechados), sem
        mexer na seleção nem na posição. Devolve True se alguma coisa mudou.

        Se não houver ligação ao servidor, não muda nada e devolve False.
        """
        if not self.dias:
            return False
        antes = (self.marcacoes, self.fechados, self.cadeados)
        try:
            self.fechados = presencas.meses_fechados(self.sessao)
            self.cadeados = bloqueios.de_outros(self.sessao)
            self._mostrar_marcacoes()
        except SQLAlchemyError:
            self.sessao.rollback()
            return False
        return (self.marcacoes, self.fechados, self.cadeados) != antes

    def aplicar_texto(self, indices, texto: str) -> bool:
        """Aplica o mesmo texto (ex.: «PF» ou «P+2»; vazio = limpar) a várias células."""
        try:
            estado = presencas.interpretar_celula(texto, self.codigos_ativos)
        except ValueError as erro:
            self.erro.emit(str(erro))
            return False
        return self.aplicar_estados([Alteracao(t.id, d, estado) for t, d in self._celulas(indices)])

    def linhas_de_trabalhadores(self, a_partir_de: int) -> list[int]:
        return [
            n for n in range(a_partir_de, len(self.linhas)) if self.linhas[n].tipo == TRABALHADOR
        ]

    def colar(self, indice: QModelIndex, matriz: list[list[str]]) -> bool:
        """Cola uma matriz de textos a partir de uma célula, saltando as linhas de grupo.

        O que sair da grelha é ignorado. Se algum texto for inválido, não se cola nada.
        """
        if self.celula(indice) is None:
            self.erro.emit("Selecione primeiro a célula onde colar.")
            return False
        linhas = self.linhas_de_trabalhadores(indice.row())
        primeiro_dia = indice.column() - N_ESQ
        alteracoes = []
        try:
            for n_linha, valores in zip(linhas, matriz, strict=False):
                trab = self.linhas[n_linha].trab
                for n_col, texto in enumerate(valores):
                    if primeiro_dia + n_col >= len(self.dias):
                        break
                    estado = presencas.interpretar_celula(texto, self.codigos_ativos)
                    alteracoes.append(Alteracao(trab.id, self.dias[primeiro_dia + n_col], estado))
        except ValueError as erro:
            self.erro.emit(f"Não colei nada: {erro}")
            return False
        return self.aplicar_estados(alteracoes)

    def texto_para_copiar(self, indices) -> str:
        """Texto (separado por tabulações) do retângulo que envolve as células selecionadas."""
        celulas = [i for i in indices if self.celula(i) is not None]
        if not celulas:
            return ""
        selecionadas = {(i.row(), i.column()) for i in celulas}
        linhas = sorted({i.row() for i in celulas})
        colunas = range(min(i.column() for i in celulas), max(i.column() for i in celulas) + 1)
        return "\n".join(
            "\t".join(
                self.data(self.index(linha, c), Papel.EditRole)
                if (linha, c) in selecionadas
                else ""
                for c in colunas
            )
            for linha in linhas
        )

    def pode_desfazer(self) -> bool:
        return bool(self._desfazer)

    def desfazer(self) -> bool:
        if not self._desfazer:
            return False
        anteriores = self._desfazer.pop()
        if not self.aplicar_estados(anteriores, desfazivel=False):
            self._desfazer.append(anteriores)
            return False
        return True

    def copiar_semana_anterior(self, dia: date, trabalhador_ids=None) -> int:
        """Copia a semana anterior para a semana de `dia`. Devolve o nº de células copiadas."""
        ids = (
            list(trabalhador_ids)
            if trabalhador_ids is not None
            else [t.id for t in self.trabalhadores]
        )
        alteracoes = presencas.alteracoes_copiar_semana(self.sessao, ids, dia)
        if not alteracoes:
            self.erro.emit("A semana anterior não tem marcações para copiar.")
            return 0
        return len(alteracoes) if self.aplicar_estados(alteracoes) else 0


class ModeloTotaisDia(QAbstractTableModel):
    """Rodapé: pessoas presentes por dia, no total e por cliente.

    Conta as marcações com um código que «conta como trabalhado», dos trabalhadores filtrados
    (mesmo que o grupo esteja recolhido). O cliente é o da marcação.
    """

    def __init__(self, grelha: ModeloGrelha, parent=None):
        super().__init__(parent)
        self.grelha = grelha
        self.rotulos: list[str] = []
        self.contagens: list[dict[date, int]] = []
        grelha.modelReset.connect(self.recalcular)
        grelha.alterado.connect(self.recalcular)
        self.recalcular()

    def recalcular(self) -> None:
        self.beginResetModel()
        g = self.grelha
        visiveis = {t.id for t in g.trabalhadores}
        nomes = {
            id_: codigo for id_, codigo in g.sessao.execute(select(Cliente.id, Cliente.codigo))
        }
        total: dict[date, int] = Counter()
        por_cliente: dict[int | None, dict[date, int]] = defaultdict(Counter)
        for (tid, dia), celula in g.marcacoes.items():
            if tid in visiveis and g.codigos[celula.codigo_id].conta_trabalhado:
                total[dia] += 1
                por_cliente[celula.cliente_id][dia] += 1
        ordenados = sorted(
            por_cliente, key=lambda c: (c is None, sem_acentos(nomes.get(c, "") or ""))
        )
        self.rotulos = ["Presentes (total)"] + [nomes.get(c) or "(sem cliente)" for c in ordenados]
        self.contagens = [total] + [por_cliente[c] for c in ordenados]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rotulos)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self.grelha.columnCount()

    def flags(self, indice):
        return Qt.ItemFlag.ItemIsEnabled

    def data(self, indice, papel=Papel.DisplayRole):
        if not indice.isValid():
            return None
        dia = self.grelha.dia_da_coluna(indice.column())
        if papel == Papel.DisplayRole:
            if indice.column() == 1:
                return self.rotulos[indice.row()]
            if dia is not None:
                return str(self.contagens[indice.row()].get(dia) or "")
        if papel == Papel.TextAlignmentRole and dia is not None:
            return int(Qt.AlignmentFlag.AlignCenter)
        if papel == Papel.FontRole and indice.row() == 0:
            return self.grelha._negrito
        if papel == Papel.BackgroundRole and dia is not None:
            return self.grelha._cor_do_dia(dia)
        return None
