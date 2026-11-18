"""Ecrã «Lançamentos»: adiantamentos, descontos, prémios e outros valores manuais, por mês."""

from decimal import Decimal

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import lancamentos
from ..modelos import Empresa, LancamentoManual, Trabalhador
from ..presencas import meses_fechados
from . import definicoes as d
from .formatos import texto_decimal
from .periodo import SeletorMes
from .tabela import ModeloTabela, VistaTabela

TIPOS_QUE_SUBTRAEM = ("adiantamento", "desconto")


class EcraLancamentos(QWidget):
    def __init__(self, sessao: Session, parent=None):
        super().__init__(parent)
        self.sessao = sessao
        self.seletor = SeletorMes()
        self.modelo = ModeloTabela(
            sessao,
            LancamentoManual,
            d.COLUNAS_LANCAMENTO,
            consulta=self._consulta,
            ao_criar=self._preparar,
            ao_gravar=lancamentos.registar,
        )
        self.vista = VistaTabela(self.modelo, nome_registo="lançamento")

        self.ajuda = QLabel(
            "O valor soma ao total do trabalhador se for positivo e subtrai se for negativo: "
            "adiantamentos e descontos escrevem-se com o sinal menos (ex.: -100)."
        )
        self.ajuda.setWordWrap(True)
        self.aviso = QLabel()
        self.aviso.setStyleSheet("background:#FFF3B0; padding:4px; border:1px solid #E0C040;")
        self.aviso.setWordWrap(True)
        self.total = QLabel()

        barra = QHBoxLayout()
        barra.addWidget(QLabel("Mês:"))
        barra.addWidget(self.seletor)
        barra.addStretch(1)
        barra.addWidget(self.total)

        disposicao = QVBoxLayout(self)
        disposicao.addLayout(barra)
        disposicao.addWidget(self.ajuda)
        disposicao.addWidget(self.aviso)
        disposicao.addWidget(self.vista, 1)

        self.seletor.mudou.connect(self.recarregar)
        self.modelo.alterado.connect(self._atualizar_resumo)
        self._atualizar_resumo()

    def _consulta(self):
        return (
            select(LancamentoManual)
            .join(Trabalhador)
            .where(
                LancamentoManual.ano == self.seletor.ano, LancamentoManual.mes == self.seletor.mes
            )
            .order_by(Trabalhador.nome, LancamentoManual.id)
        )

    def _preparar(self, lancamento: LancamentoManual, _sessao: Session) -> None:
        lancamento.ano = self.seletor.ano
        lancamento.mes = self.seletor.mes
        lancamento.tipo = "adiantamento"

    def recarregar(self) -> None:
        self.vista.recarregar()

    def _atualizar_resumo(self) -> None:
        gravados = [x for x in self.modelo.linhas if not self.modelo.pendente(x)]
        soma = sum((x.valor for x in gravados if x.valor is not None), Decimal(0))
        self.total.setText(
            f"{len(gravados)} lançamento(s) · soma: {texto_decimal(soma.quantize(Decimal('0.01')))}"
            " €"
        )

        avisos = []
        ao_contrario = sum(
            1
            for x in gravados
            if x.tipo in TIPOS_QUE_SUBTRAEM and x.valor is not None and x.valor > 0
        )
        if ao_contrario:
            avisos.append(
                f"Há {ao_contrario} adiantamento(s) ou desconto(s) com valor positivo: assim "
                "somam ao total em vez de subtrair. Confirme o sinal."
            )
        fechados = {
            e
            for e, ano, mes in meses_fechados(self.sessao)
            if (ano, mes) == (self.seletor.ano, self.seletor.mes)
        }
        if fechados:
            nomes = self.sessao.scalars(
                select(Empresa.nome).where(Empresa.id.in_(fechados)).order_by(Empresa.nome)
            ).all()
            avisos.append(
                f"Mês fechado para: {', '.join(nomes)}. Os lançamentos dos trabalhadores "
                "dessa(s) empresa(s) não podem ser alterados sem reabrir o mês."
            )
        self.aviso.setText("\n".join(avisos))
        self.aviso.setVisible(bool(avisos))
